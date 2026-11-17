"""Experimental process supervision and tamper-evident output capture.

This does not impose a storage or network quota and does not establish a
security boundary. Output copies are read-only, not immutable to the owner.
"""
import ctypes
import errno
import fcntl
import re
import hashlib
import json
import math
import threading
import sys
import os
from pathlib import Path, PurePosixPath
import selectors
import signal
import stat
import subprocess
import time
import uuid


def execute(argv, *, timeout, memory_bytes=16 * 1024**3, cpu_quota=400,
            tasks_max=256, allowed_cpus=None, output_bytes=1024**2,
            trusted_coordinator=False, unit_name=None):
    """Run a command in a transient user cgroup; capture bounded output.

    The trusted launcher restricts CPU affinity, then denies later affinity
    changes using an inherited seccomp filter. CPUQuota limits CPU rate.
    Aggregate case budgets and disk/network limits require separate controls.
    """
    if not argv or not 0 < timeout <= 21600 or memory_bytes <= 0 or not 0 < cpu_quota <= 400 or tasks_max < 1 or output_bytes < 1:
        raise ValueError('invalid resource limit')
    unit = unit_name or ('osri-' + uuid.uuid4().hex + '.scope')
    if not re.fullmatch(r'osri-[a-f0-9]{32}\.scope', unit):
        raise ValueError('invalid transient scope name')
    guard = os.environ.get('PILOT_SESSION_ROOT')
    if guard and not trusted_coordinator:
        # Guarded profiles reserve 2 GiB for coordinator/FUSE and 14 GiB for
        # the one serialized case scope. Other unmetered host services are not
        # included in this cgroup accounting.
        memory_bytes = min(memory_bytes, 14 * 1024**3)
    if guard:
        root = Path(guard).resolve(strict=True)
        if not root.is_relative_to('/workspace') or not root.name.startswith('guard-'):
            raise ValueError('invalid session scope registry')
        with (root / 'guard-scopes.jsonl').open('a') as registry:
            fcntl.flock(registry, fcntl.LOCK_EX)
            registry.write(json.dumps({'scope': unit}) + '\n')
            registry.flush()
            os.fsync(registry.fileno())
            fcntl.flock(registry, fcntl.LOCK_UN)
    args = ['systemd-run', '--user', '--scope', '--quiet', '--unit=' + unit,
            '-p', 'MemoryMax=' + str(memory_bytes), '-p', 'MemorySwapMax=0',
            '-p', 'TasksMax=' + str(tasks_max), '-p', 'CPUQuota=' + str(cpu_quota) + '%',
            '-p', 'RuntimeMaxSec=' + str(timeout), '-p', 'TimeoutStopSec=1s',
            '-p', 'KillMode=control-group', '-p', 'KillSignal=SIGKILL']
    if allowed_cpus is None:
        allowed_cpus = sorted(os.sched_getaffinity(0))[:4]
    if allowed_cpus is not None:
        if not allowed_cpus or any(not isinstance(n, int) or n < 0 for n in allowed_cpus) or len(set(allowed_cpus)) > 4:
            raise ValueError('invalid CPU set')
        args += ['-p', 'AllowedCPUs=' + ','.join(map(str, allowed_cpus))]
    if trusted_coordinator:
        # FUSE requires setuid fusermount, which no_new_privs would disable.
        # Only trusted orchestration may use this path; workloads must not.
        args += ['--', '/usr/bin/taskset', '-c', ','.join(map(str, allowed_cpus)), *argv]
    else:
        args += ['--', sys.executable, str(Path(__file__).resolve()), '--affinity-exec', json.dumps(allowed_cpus), *argv]
    start = time.monotonic()
    proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, start_new_session=True, close_fds=True)
    sel = selectors.DefaultSelector()
    data = {'stdout': bytearray(), 'stderr': bytearray()}
    for name in data:
        sel.register(getattr(proc, name), selectors.EVENT_READ, name)
    timed_out = False
    truncated = False
    try:
        while sel.get_map():
            if time.monotonic() - start >= timeout:
                timed_out = True
                break
            for key, _ in sel.select(min(.1, max(0, timeout - (time.monotonic() - start)))):
                chunk = os.read(key.fd, 65536)
                if not chunk:
                    sel.unregister(key.fileobj)
                    continue
                room = max(0, output_bytes - sum(map(len, data.values())))
                data[key.data].extend(chunk[:room])
                if len(chunk) > room:
                    truncated = True
                    break
            if truncated:
                break
        if timed_out or truncated:
            # The scope, rather than the process group, covers setsid descendants.
            subprocess.run(['systemctl', '--user', 'kill', '--kill-whom=all', '--signal=KILL', unit],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5, check=False)
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        try:
            proc.wait(timeout=max(0, timeout - (time.monotonic() - start)))
        except subprocess.TimeoutExpired:
            timed_out = True
            subprocess.run(['systemctl', '--user', 'kill', '--kill-whom=all', '--signal=KILL', unit],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5, check=False)
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait(timeout=5)
        # A successful leader can leave detached children that closed its pipes.
        # The whole transient scope must be stopped on every return path.
        subprocess.run(['systemctl', '--user', 'kill', '--kill-whom=all', '--signal=KILL', unit],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5, check=False)
        return {'returncode': proc.returncode, 'stdout': data['stdout'].decode('utf-8', 'replace'),
                'stderr': data['stderr'].decode('utf-8', 'replace'), 'timed_out': timed_out,
                'output_limit_exceeded': truncated, 'elapsed_seconds': time.monotonic() - start,
                'effective_requested_limits': {'memory_max_bytes': memory_bytes,
                    'memory_swap_max_bytes': 0, 'cpu_quota_percent': cpu_quota,
                    'tasks_max': tasks_max, 'allowed_cpus': allowed_cpus,
                    'combined_output_bytes': output_bytes, 'trusted_coordinator': trusted_coordinator}, 'scope': unit}
    finally:
        # Also covers caller exceptions; systemd RuntimeMaxSec is the fallback
        # if this coordinator itself is killed and cannot run cleanup.
        try:
            subprocess.run(['systemctl', '--user', 'kill', '--kill-whom=all', '--signal=KILL', unit],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5, check=False)
        finally:
            if proc.poll() is None:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait(timeout=5)
        sel.close()
        for stream in (proc.stdout, proc.stderr):
            stream.close()


def lock_outputs(source, destination, paths, *, max_bytes=None, max_files=10000, max_path_bytes=4096):
    """Copy regular single-link files to a fresh directory and hash their bytes.

    Call only after the executor and all writers have stopped. Host owner can
    modify copies; retain the returned manifest in a separately controlled store.
    """
    if max_bytes is not None and (not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes < 0):
        raise ValueError('invalid aggregate output cap')
    if not isinstance(max_files, int) or max_files < 0 or not isinstance(max_path_bytes, int) or max_path_bytes < 1:
        raise ValueError('invalid output count or path cap')
    copied_total = 0
    source = Path(source).resolve(strict=True)
    destination = Path(destination)
    destination.mkdir(mode=0o700)  # fails if it already exists
    rootfd = os.open(source, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    records = []
    try:
        seen = set()
        for name in paths:
            if len(seen) >= max_files:
                raise ValueError('output file count cap exceeded')
            if not isinstance(name, str) or len(os.fsencode(name)) > max_path_bytes:
                raise ValueError('output path cap exceeded')
            p = PurePosixPath(name)
            if p.is_absolute() or not p.parts or any(x in ('.', '..') for x in p.parts) or str(p) in seen:
                raise ValueError('invalid or duplicate output path')
            seen.add(str(p))
            fd = os.dup(rootfd)
            try:
                for component in p.parts[:-1]:
                    child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                    os.close(fd)
                    fd = child
                f = os.open(p.parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
                try:
                    before = os.fstat(f)
                    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                        raise ValueError('output must be a regular file with one link')
                    if max_bytes is not None and before.st_size > max_bytes - copied_total:
                        raise ValueError('aggregate output cap exceeded')
                    target = destination.joinpath(*p.parts)
                    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    digest = hashlib.sha256()
                    count = 0
                    with target.open('xb') as out:
                        while True:
                            remaining = None if max_bytes is None else max_bytes - copied_total - count
                            chunk = os.read(f, 1024 * 1024 if remaining is None else min(1024 * 1024, remaining + 1))
                            if remaining is not None and len(chunk) > remaining:
                                raise ValueError('aggregate output cap exceeded')
                            if not chunk:
                                break
                            out.write(chunk)
                            digest.update(chunk)
                            count += len(chunk)
                    after = os.fstat(f)
                    if (before.st_size, before.st_mtime_ns, before.st_ctime_ns, before.st_nlink) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns, after.st_nlink) or count != before.st_size:
                        raise ValueError('output changed during capture')
                    target.chmod(0o400)
                    copied_total += count
                    records.append({'path': str(p), 'bytes': count, 'sha256': digest.hexdigest()})
                finally:
                    os.close(f)
            finally:
                os.close(fd)
        return records
    finally:
        os.close(rootfd)


def _affinity_exec(cpus, argv):
    """Set affinity before exec and prevent the process tree from widening it."""
    os.sched_setaffinity(0, cpus)
    if os.sched_getaffinity(0) != set(cpus):
        raise RuntimeError('requested CPU affinity not effective')
    lib = ctypes.CDLL('libseccomp.so.2', use_errno=True)
    lib.seccomp_init.argtypes = [ctypes.c_uint32]
    lib.seccomp_init.restype = ctypes.c_void_p
    lib.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    lib.seccomp_syscall_resolve_name.restype = ctypes.c_int
    lib.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
    lib.seccomp_rule_add.restype = ctypes.c_int
    lib.seccomp_load.argtypes = [ctypes.c_void_p]
    lib.seccomp_load.restype = ctypes.c_int
    lib.seccomp_release.argtypes = [ctypes.c_void_p]
    ctx = lib.seccomp_init(0x7fff0000)  # SCMP_ACT_ALLOW
    if not ctx:
        raise RuntimeError('seccomp initialization failed')
    try:
        syscall = lib.seccomp_syscall_resolve_name(b'sched_setaffinity')
        if syscall < 0 or lib.seccomp_rule_add(ctx, 0x00050000 | errno.EPERM, syscall, 0) != 0:
            raise RuntimeError('cannot install affinity rule')
        if lib.seccomp_load(ctx) != 0:
            raise RuntimeError('cannot load affinity rule')
    finally:
        lib.seccomp_release(ctx)
    os.execvpe(argv[0], argv, os.environ)


if __name__ == '__main__' and len(sys.argv) >= 4 and sys.argv[1] == '--affinity-exec':
    _affinity_exec(json.loads(sys.argv[2]), sys.argv[3:])


class CaseBudget:
    """Durable coordinator-owned case ledger; callers must route every action here.

    A reservation charges its entire maximum immediately. Completion refunds the
    unused part; a crash leaves the charge in place. Elapsed time uses a
    boot-time clock including suspend and fails closed after reboot. This object does not itself
    supervise processes or meter network traffic.
    """
    def __init__(self, path, *, elapsed_seconds=21600, vm_seconds=14400,
                 active_seconds=10800, network_bytes=20 * 1024**3):
        import sqlite3
        ledger_path = Path(path)
        parent = ledger_path.parent.resolve(strict=True)
        if Path('/workspace') not in parent.parents and parent != Path('/workspace'):
            raise ValueError('case ledger must be below /workspace')
        if ledger_path.is_symlink():
            raise ValueError('case ledger cannot be a symlink')
        self.path = str(parent / ledger_path.name)
        self.boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        self._lock = threading.RLock()
        self._live_reservations = {}
        self._closed = False
        self.db = sqlite3.connect(self.path, timeout=10, isolation_level=None, check_same_thread=False)
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS budget (id INTEGER PRIMARY KEY CHECK(id=1), boot TEXT, started REAL, elapsed REAL, vm REAL, active REAL, network INTEGER, vm_used REAL, active_used REAL, network_used INTEGER)')
        self.db.execute('CREATE TABLE IF NOT EXISTS reservations (token TEXT PRIMARY KEY, seconds REAL, active INTEGER)')
        limits = (elapsed_seconds, vm_seconds, active_seconds, network_bytes)
        if any(not isinstance(x, (int, float)) or isinstance(x, bool) or not math.isfinite(x) or x <= 0 for x in limits) or not isinstance(network_bytes, int):
            raise ValueError('case limits must be positive')
        self.db.execute('INSERT OR IGNORE INTO budget VALUES (1, ?, ?, ?, ?, ?, ?, 0, 0, 0)', (self.boot, time.clock_gettime(time.CLOCK_BOOTTIME), *limits))
        row = self.db.execute('SELECT boot, elapsed, vm, active, network FROM budget WHERE id=1').fetchone()
        if row != (self.boot, *limits):
            raise ValueError('case budget boot or limits differ; reconciliation required')
        started = self.db.execute('SELECT started FROM budget WHERE id=1').fetchone()[0]
        self._case_deadline = started + elapsed_seconds

    def close(self):
        with self._lock:
            self._live_reservations.clear()
            self._closed = True
            self.db.close()

    def transfer_allowed(self):
        """Check current-instance live reservations and BOOTTIME deadlines without writes."""
        with self._lock:
            now = time.clock_gettime(time.CLOCK_BOOTTIME)
            return (not self._closed and now < self._case_deadline and
                    any(now < deadline for deadline in self._live_reservations.values()))

    def abandon(self, token):
        """Idempotently revoke authority without refunding the durable charge."""
        with self._lock:
            return self._live_reservations.pop(token, None) is not None

    def _transaction(self, fn):
        with self._lock:
            self.db.execute('BEGIN IMMEDIATE')
            try:
                result = fn()
                self.db.execute('COMMIT')
                return result
            except BaseException:
                self.db.execute('ROLLBACK')
                raise

    def reserve(self, seconds, *, active):
        """Reserve a maximum VM duration; pass it as the supervisor timeout."""
        if not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or not 0 < seconds <= 21600:
            raise ValueError('invalid reservation')
        def reserve_tx():
            boot, started, elapsed, vm, active_limit, vm_used, active_used = self.db.execute('SELECT boot, started, elapsed, vm, active, vm_used, active_used FROM budget WHERE id=1').fetchone()
            if boot != self.boot or time.clock_gettime(time.CLOCK_BOOTTIME) - started + seconds > elapsed or vm_used + seconds > vm or (active and active_used + seconds > active_limit):
                raise RuntimeError('case time budget exhausted')
            token = uuid.uuid4().hex
            self.db.execute('UPDATE budget SET vm_used=vm_used+?, active_used=active_used+? WHERE id=1', (seconds, seconds if active else 0))
            self.db.execute('INSERT INTO reservations VALUES (?, ?, ?)', (token, seconds, int(active)))
            return token
        with self._lock:
            start = time.clock_gettime(time.CLOCK_BOOTTIME)
            token = self._transaction(reserve_tx)
            self._live_reservations[token] = min(start + seconds, self._case_deadline)
            return token

    def finish(self, token, elapsed_seconds):
        """Charge actual observed time; never trust a workload-supplied duration."""
        def finish_tx():
            row = self.db.execute('SELECT seconds, active FROM reservations WHERE token=?', (token,)).fetchone()
            if row is None or not isinstance(elapsed_seconds, (int, float)) or not math.isfinite(elapsed_seconds) or elapsed_seconds < 0:
                raise ValueError('invalid reservation completion')
            refund = row[0] - elapsed_seconds  # Negative when cleanup overruns.
            self.db.execute('UPDATE budget SET vm_used=vm_used-?, active_used=active_used-? WHERE id=1', (refund, refund if row[1] else 0))
            self.db.execute('DELETE FROM reservations WHERE token=?', (token,))
        with self._lock:
            if token not in self._live_reservations:
                raise ValueError('reservation is not live in this instance')
            try:
                self._transaction(finish_tx)
            finally:
                self._live_reservations.pop(token, None)

    def consume_network(self, count):
        """Atomically debit bytes before transfer. Return False on exhaustion."""
        if not isinstance(count, int) or count < 0:
            raise ValueError('invalid byte count')
        def consume_tx():
            used, maximum, started, elapsed, boot = self.db.execute('SELECT network_used, network, started, elapsed, boot FROM budget WHERE id=1').fetchone()
            open_reservations = self.db.execute('SELECT COUNT(*) FROM reservations').fetchone()[0]
            if boot != self.boot or not self.transfer_allowed() or time.clock_gettime(time.CLOCK_BOOTTIME) - started >= elapsed or not open_reservations or used + count > maximum:
                return False
            self.db.execute('UPDATE budget SET network_used=network_used+? WHERE id=1', (count,))
            return True
        with self._lock:
            if not self.transfer_allowed():
                return False
            return self._transaction(consume_tx)

    def snapshot(self):
        """Return consistent charged totals and conservative remaining budgets."""
        def read_tx():
            boot, started, elapsed, vm, active, network, vm_used, active_used, network_used = self.db.execute('SELECT boot, started, elapsed, vm, active, network, vm_used, active_used, network_used FROM budget WHERE id=1').fetchone()
            if boot != self.boot:
                raise RuntimeError('case crossed a reboot')
            elapsed_used = time.clock_gettime(time.CLOCK_BOOTTIME) - started
            elapsed_remaining = max(0, elapsed - elapsed_used)
            vm_remaining = max(0, vm - vm_used)
            active_remaining = max(0, active - active_used)
            return {'elapsed_seconds': elapsed_used, 'elapsed_limit': elapsed,
                    'elapsed_remaining_seconds': elapsed_remaining,
                    'vm_charged_seconds': vm_used, 'vm_limit': vm,
                    'vm_remaining_seconds': vm_remaining,
                    'active_charged_seconds': active_used, 'active_limit': active,
                    'active_remaining_seconds': active_remaining,
                    'max_next_active_seconds': min(elapsed_remaining, vm_remaining, active_remaining),
                    'max_next_inactive_seconds': min(elapsed_remaining, vm_remaining),
                    'network_bytes': network_used, 'network_limit': network,
                    'network_remaining_bytes': max(0, network - network_used),
                    'open_reservations': self.db.execute('SELECT COUNT(*) FROM reservations').fetchone()[0]}
        return self._transaction(read_tx)

    def remaining(self, *, active=True):
        """Return the largest conservative new reservation (may race another caller)."""
        state = self.snapshot()
        return state['max_next_active_seconds' if active else 'max_next_inactive_seconds']
