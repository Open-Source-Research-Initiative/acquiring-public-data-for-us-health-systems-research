"""Synthetic FUSE quota checks; requires explicitly provisioned local runtime."""
import errno
import os
from pathlib import Path
import subprocess
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor

from executor.quota_fs import QuotaFS

RUNTIME = os.environ.get('PILOT_FUSE_RUNTIME')


@unittest.skipUnless(RUNTIME, 'set PILOT_FUSE_RUNTIME to extracted runtime directory')
class QuotaFSTest(unittest.TestCase):
    def test_concurrent_writes_and_lifecycle(self):
        root = Path(RUNTIME).resolve()
        parent = root.parent
        with QuotaFS(parent, 32 * 1024**2, fuse2fs=root/'usr/bin/fuse2fs',
                     library_dir=root/'lib/x86_64-linux-gnu') as fs:
            image = fs.mount.parent / 'scratch.ext4'
            self.assertEqual(image.stat().st_size, 32 * 1024**2)
            def writer(i):
                total = 0
                try:
                    with (fs.mount / str(i)).open('wb', buffering=0) as out:
                        while True:
                            total += out.write(b'x' * 65536)
                except OSError as error:
                    self.assertEqual(error.errno, errno.ENOSPC)
                return total
            with ThreadPoolExecutor(max_workers=4) as pool:
                total = sum(pool.map(writer, range(4)))
            self.assertLessEqual(total, 32 * 1024**2)
            self.assertGreater(total, 0)
            self.assertLessEqual(image.stat().st_blocks * 512, 32 * 1024**2)
            mount = fs.mount
        self.assertFalse(mount.exists())
        self.assertIsNotNone(fs.process.poll())

    def test_open_unlinked_allocation_stays_bounded(self):
        root = Path(RUNTIME).resolve()
        with QuotaFS(root.parent, 32 * 1024**2, fuse2fs=root/'usr/bin/fuse2fs',
                     library_dir=root/'lib/x86_64-linux-gnu') as fs:
            path = fs.mount / 'held'
            with path.open('wb', buffering=0) as file:
                file.write(b'a' * (4 * 1024**2))
                os.unlink(path)
                with self.assertRaises(OSError) as caught:
                    with (fs.mount / 'fill').open('wb', buffering=0) as out:
                        while True:
                            out.write(b'b' * 65536)
                self.assertEqual(caught.exception.errno, errno.ENOSPC)
                self.assertLessEqual((fs.mount.parent/'scratch.ext4').stat().st_blocks * 512, 32 * 1024**2)

    def test_sparse_links_truncate_and_mmap(self):
        import mmap
        root = Path(RUNTIME).resolve()
        with QuotaFS(root.parent, 32 * 1024**2, fuse2fs=root/'usr/bin/fuse2fs',
                     library_dir=root/'lib/x86_64-linux-gnu') as fs:
            path = fs.mount / 'file'
            with path.open('w+b') as file:
                file.truncate(8 * 1024**2)
                with mmap.mmap(file.fileno(), 4096) as mapping:
                    mapping[0:4] = b'test'
                    mapping.flush()
            os.link(path, fs.mount / 'hardlink')
            os.symlink('file', fs.mount / 'symlink')
            self.assertEqual((fs.mount/'hardlink').stat().st_ino, path.stat().st_ino)
            self.assertEqual((fs.mount/'symlink').read_bytes()[:4], b'test')
            with path.open('r+b') as file:
                file.truncate(1024)
            self.assertEqual((fs.mount/'hardlink').stat().st_size, 1024)
            self.assertLessEqual((fs.mount.parent/'scratch.ext4').stat().st_blocks * 512, 32 * 1024**2)

    def test_daemon_failure_fails_closed(self):
        root = Path(RUNTIME).resolve()
        with QuotaFS(root.parent, 32 * 1024**2, fuse2fs=root/'usr/bin/fuse2fs',
                     library_dir=root/'lib/x86_64-linux-gnu') as fs:
            fs.process.kill()
            fs.process.wait(timeout=5)
            with self.assertRaises(OSError):
                (fs.mount/'must-not-write').write_text('x')

    def test_fallocate_cannot_allocate_beyond_image(self):
        root = Path(RUNTIME).resolve()
        with QuotaFS(root.parent, 32 * 1024**2, fuse2fs=root/'usr/bin/fuse2fs',
                     library_dir=root/'lib/x86_64-linux-gnu') as fs:
            with (fs.mount/'preallocated').open('wb') as file:
                with self.assertRaises(OSError) as caught:
                    os.posix_fallocate(file.fileno(), 0, 64 * 1024**2)
                self.assertIn(caught.exception.errno, (errno.ENOSPC, errno.EOPNOTSUPP, errno.ENOSYS))
            self.assertLessEqual((fs.mount.parent/'scratch.ext4').stat().st_blocks * 512, 32 * 1024**2)

    def test_100gib_image_sparse_smoke(self):
        root = Path(RUNTIME).resolve()
        with QuotaFS(root.parent, 100 * 1024**3, fuse2fs=root/'usr/bin/fuse2fs',
                     library_dir=root/'lib/x86_64-linux-gnu') as fs:
            image = fs.mount.parent/'scratch.ext4'
            self.assertEqual(image.stat().st_size, 100 * 1024**3)
            self.assertLess(image.stat().st_blocks * 512, 1024**3)
            (fs.mount/'smoke').write_bytes(b'x' * (1024 * 1024))
            self.assertEqual((fs.mount/'smoke').stat().st_size, 1024 * 1024)
            self.assertLessEqual(image.stat().st_blocks * 512, 100 * 1024**3)

    def test_sandbox_backing_and_daemon_isolation(self):
        import json
        from executor.sandbox import run
        root = Path(RUNTIME).resolve()
        with QuotaFS(root.parent, 32 * 1024**2, fuse2fs=root/'usr/bin/fuse2fs',
                     library_dir=root/'lib/x86_64-linux-gnu') as fs:
            script = '''import json,os,signal
r={}
for name,path in [('image',IMAGE),('daemon_proc','/proc/'+str(PID)),('root','/outside'),('tmp','/tmp/synthetic'),('home',os.environ['HOME']+'/synthetic')]:
 try:
  if name in ('image','daemon_proc'): r[name]=os.path.exists(path)
  else:
   with open(path,'w') as f: f.write('x')
   r[name]=True
 except OSError: r[name]=False
try: os.kill(PID,signal.SIGSTOP); r['signal']=True
except OSError: r['signal']=False
print(json.dumps(r))'''.replace('IMAGE', repr(str(fs.mount.parent/'scratch.ext4'))).replace('PID',str(fs.process.pid))
            result = run(['/usr/bin/python3','-c',script], scratch=fs.mount, timeout=10)
            self.assertEqual(result['returncode'], 0, result)
            data = json.loads(result['stdout'])
            self.assertEqual(data, {'image':False, 'daemon_proc':False, 'root':False,
                                    'tmp':True, 'home':True, 'signal':False})
            self.assertIsNone(fs.process.poll())
            self.assertTrue((fs.mount/'synthetic').is_file())
            self.assertTrue((fs.mount/'.sandbox-home/synthetic').is_file())
