"""Disposable ext4-in-FUSE scratch; independently qualify before pilot use."""
import os
import json
from pathlib import Path
import subprocess
import tempfile
import time


class QuotaFS:
    def __init__(self, parent, size_bytes, *, fuse2fs, library_dir):
        self.parent = Path(parent).resolve(strict=True)
        if not self.parent.is_dir() or not self.parent.is_relative_to('/workspace'):
            raise ValueError('parent must be an existing workspace directory')
        if not isinstance(size_bytes, int) or size_bytes < 16 * 1024**2:
            raise ValueError('image must be at least 16 MiB')
        self.size_bytes = size_bytes
        self.fuse2fs = Path(fuse2fs).resolve(strict=True)
        self.library_dir = Path(library_dir).resolve(strict=True)
        self.temp = None
        self.process = None
        self.mount = None
        self.registration = None
        guard = os.environ.get('PILOT_SESSION_ROOT')
        if guard:
            guard_path = Path(guard)
            if guard_path.is_symlink():
                raise ValueError('guard root cannot be a symlink')
            guard_path = guard_path.resolve(strict=True)
            if not guard_path.is_relative_to('/workspace') or self.parent != guard_path:
                raise ValueError('quota parent must equal guarded workspace root')
            self.registration = guard_path / 'guard-resources.json'
            if self.registration.exists() or self.registration.is_symlink():
                raise FileExistsError('guard already has registered quota resources')

    def _register(self, image, phase):
        if self.registration is None:
            return
        pid = self.process.pid if self.process else None
        starttime = None
        if pid:
            statline = Path(f'/proc/{pid}/stat').read_text()
            starttime = statline.rsplit(')', 1)[1].split()[19]
        record = {'image': str(image), 'mount': str(self.mount), 'daemon_pid': pid,
                  'daemon_starttime': starttime, 'phase': phase}
        fd, name = tempfile.mkstemp(prefix='.guard-resources-', dir=self.parent)
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(record, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.registration)
            dirfd = os.open(self.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(dirfd)
            finally:
                os.close(dirfd)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def __enter__(self):
        self.temp = tempfile.TemporaryDirectory(prefix='quota-', dir=self.parent)
        base = Path(self.temp.name)
        image, self.mount = base / 'scratch.ext4', base / 'mount'
        self.mount.mkdir()
        try:
            self._register(image, 'prepared')
            with image.open('xb') as f:
                f.truncate(self.size_bytes)
            subprocess.run(['mke2fs', '-q', '-t', 'ext4', '-F', '-m', '0', '-E',
                            f'root_owner={os.getuid()}:{os.getgid()}', str(image)],
                           check=True, capture_output=True)
            subprocess.run(['debugfs', '-w', '-R', 'rmdir /lost+found', str(image)],
                           check=True, capture_output=True)
            env = {'PATH': '/usr/bin:/bin', 'LD_LIBRARY_PATH': str(self.library_dir)}
            self.process = subprocess.Popen([str(self.fuse2fs), str(image), str(self.mount), '-f'],
                                            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self._register(image, 'started')
            for _ in range(100):
                if self.process.poll() is not None:
                    raise RuntimeError('fuse2fs exited during mount')
                if subprocess.run(['mountpoint', '-q', str(self.mount)]).returncode == 0:
                    return self
                time.sleep(.05)
            raise TimeoutError('fuse2fs mount timed out')
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, exc_type, exc, tb):
        if self.mount and self.process:
            unmount = subprocess.run(['fusermount3', '-u', str(self.mount)], capture_output=True)
            mounts = Path('/proc/self/mountinfo').read_text()
            escaped = str(self.mount).replace('\\', '\\134').replace(' ', '\\040').replace('\t', '\\011').replace('\n', '\\012')
            still_mounted = any(line.split(' ')[4] == escaped for line in mounts.splitlines())
            if still_mounted:
                # Preserve the image if the mount could not be removed.
                self.temp._finalizer.detach()
                raise RuntimeError('failed to unmount quota filesystem: ' + unmount.stderr.decode(errors='replace'))
        if self.process:
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
        if self.temp:
            self.temp.cleanup()
        if self.registration:
            try:
                self.registration.unlink()
            except FileNotFoundError:
                pass
            dirfd = os.open(self.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(dirfd)
            finally:
                os.close(dirfd)
