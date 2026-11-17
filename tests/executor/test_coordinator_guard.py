import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import time
import unittest

from executor.coordinator_guard import recover, run_guarded

BASE = Path('/workspace/repos/builderbob')
RUNTIME = os.environ.get('PILOT_FUSE_RUNTIME')

class CoordinatorGuardTests(unittest.TestCase):
    def test_hung_coordinator_is_stopped(self):
        with tempfile.TemporaryDirectory(dir=BASE) as temp:
            marker = str(Path(temp)/'late')
            code = "import time; time.sleep(2); open(%r,'w').write('bad')" % marker
            result = run_guarded([sys.executable, '-c', code], workspace_parent=temp, timeout=.4)
            self.assertTrue(result['coordinator']['timed_out'], result)
            self.assertEqual(result['cleanup']['status'], 'clean', result)
            time.sleep(2.1)
            self.assertFalse(Path(marker).exists())

    def test_session_deadline_kills_registered_nested_scope(self):
        with tempfile.TemporaryDirectory(dir=BASE) as temp:
            marker=str(Path(temp)/'late')
            payload="import time; time.sleep(2); open(%r,'w').write('bad')" % marker
            code="from executor.supervisor import execute; import sys; execute([sys.executable,'-c',%r],timeout=8)" % payload
            result=run_guarded([sys.executable,'-c',code], workspace_parent=temp, timeout=.8)
            registry=Path(result['session_root'])/'guard-scopes.jsonl'
            self.assertTrue(registry.exists(),result)
            time.sleep(2.1)
            self.assertFalse(Path(marker).exists(),result)

    def test_guarded_scope_memory_partition_and_cpu_affinity(self):
        with tempfile.TemporaryDirectory(dir=BASE) as temp:
            inspect = "import os,json; p='/sys/fs/cgroup'+open('/proc/self/cgroup').read().split('::')[1].strip(); print(json.dumps({'memory':int(open(p+'/memory.max').read()),'cpus':sorted(os.sched_getaffinity(0))}))"
            code = "import json,os,sys; from executor.supervisor import execute; print('OUTER',end=' '); exec(%r); r=execute([sys.executable,'-c',%r],timeout=3); print('INNER',r['stdout'].strip())" % (inspect, inspect)
            r = run_guarded([sys.executable,'-c',code], workspace_parent=temp, timeout=5)
            lines = r['coordinator']['stdout'].splitlines()
            self.assertEqual(r['coordinator']['returncode'], 0, r)
            outer=json.loads(lines[0].split(' ',1)[1]); inner=json.loads(lines[1].split(' ',1)[1])
            self.assertEqual(outer['memory'],2*1024**3)
            self.assertEqual(inner['memory'],14*1024**3)
            self.assertEqual(outer['cpus'],inner['cpus'])
            self.assertLessEqual(len(inner['cpus']),4)

    def test_recovery_rejects_forged_path_and_active_guard(self):
        with tempfile.TemporaryDirectory(dir=BASE) as temp:
            root = Path(temp)/'guard-fake'; root.mkdir(); (root/'guard.lock').touch()
            (root/'guard-session.json').write_text(json.dumps({'boot':Path('/proc/sys/kernel/random/boot_id').read_text().strip(), 'completed':True}))
            target = Path(temp)/'outside'; target.write_bytes(b'preserve')
            (root/'guard-resources.json').write_text(json.dumps({'image':str(target),'mount':str(root/'mount'),'daemon_pid':None,'daemon_starttime':None}))
            result = recover(root)
            self.assertEqual(result['status'], 'blocked')
            self.assertEqual(target.read_bytes(), b'preserve')

    @unittest.skipUnless(RUNTIME, 'set PILOT_FUSE_RUNTIME to extracted runtime directory')
    def test_guard_crash_recovery_waits_for_watchdog(self):
        with tempfile.TemporaryDirectory(dir=BASE) as temp:
            runtime=Path(RUNTIME).resolve()
            payload = """import os,time
from executor.quota_fs import QuotaFS
root=os.environ['PILOT_SESSION_ROOT']
q=QuotaFS(root, 32*1024**2, fuse2fs=FUSE, library_dir=LIB)
q.__enter__()
open(root+'/mounted','w').write('ready')
time.sleep(30)
""".replace('FUSE',repr(str(runtime/'usr/bin/fuse2fs'))).replace('LIB',repr(str(runtime/'lib/x86_64-linux-gnu')))
            wrapper = "from executor.coordinator_guard import run_guarded; import sys; run_guarded([sys.executable,'-c',%r],workspace_parent=%r,timeout=1)" % (payload, temp)
            proc=subprocess.Popen([sys.executable,'-c',wrapper], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                deadline=time.monotonic()+3
                root=None
                while time.monotonic()<deadline:
                    roots=list(Path(temp).glob('guard-*'))
                    if roots and (roots[0]/'mounted').exists(): root=roots[0]; break
                    time.sleep(.02)
                self.assertIsNotNone(root)
                proc.kill(); proc.wait()
                self.assertEqual(recover(root)['status'], 'blocked')
                time.sleep(11.3)
                result=recover(root)
                self.assertEqual(result['status'],'clean',result)
            finally:
                if proc.poll() is None: proc.kill(); proc.wait()

    @unittest.skipUnless(RUNTIME, 'set PILOT_FUSE_RUNTIME to extracted runtime directory')
    def test_killed_coordinator_unmounts_recorded_quota(self):
        with tempfile.TemporaryDirectory(dir=BASE) as temp:
            runtime=Path(RUNTIME).resolve()
            code = """import os,time
from executor.quota_fs import QuotaFS
root=os.environ['PILOT_SESSION_ROOT']
q=QuotaFS(root, 32*1024**2, fuse2fs=FUSE, library_dir=LIB)
q.__enter__()
open(root+'/mounted','w').write(str(q.mount))
time.sleep(10)
""".replace('FUSE',repr(str(runtime/'usr/bin/fuse2fs'))).replace('LIB',repr(str(runtime/'lib/x86_64-linux-gnu')))
            result=run_guarded([sys.executable,'-c',code], workspace_parent=temp, timeout=1.5)
            self.assertTrue(result['coordinator']['timed_out'], result)
            self.assertTrue((Path(result['session_root'])/'mounted').exists(), result)
            self.assertEqual(result['cleanup']['status'], 'clean', result)
            self.assertFalse(list(Path(result['session_root']).glob('quota-*')))

if __name__ == '__main__': unittest.main()
