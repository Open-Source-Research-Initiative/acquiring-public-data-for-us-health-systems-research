"""Transient whole-session watchdog with strictly scoped FUSE recovery.

The trusted coordinator must use PILOT_SESSION_ROOT as both CaseSession parents.
This is experimental infrastructure, not pilot authorization or a hard real-time
bound. Preserve failed cleanup for manual reconciliation.
"""
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import uuid
import time

from executor.supervisor import execute

MAX_DISK = 100 * 1024**3


def _unescape_mount(value):
    return re.sub(r'\\([0-7]{3})', lambda m: chr(int(m.group(1), 8)), value)


def _mount_at(path):
    matches = []
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        left, right = line.split(' - ', 1)
        fields, filesystem = left.split(), right.split()
        if _unescape_mount(fields[4]) == str(path):
            matches.append((filesystem[0], _unescape_mount(filesystem[1])))
    return matches


def _proc_start(pid):
    try:
        # comm can contain spaces and parentheses; fields after the last ')' start at 3.
        return Path('/proc', str(pid), 'stat').read_text().rsplit(')', 1)[1].split()[19]
    except (FileNotFoundError, ProcessLookupError):
        return None


def _registered_scopes(root):
    registry = root / 'guard-scopes.jsonl'
    if not registry.exists():
        return []
    if registry.is_symlink() or not registry.is_file():
        raise ValueError('unsafe scope registry')
    scopes = []
    for line in registry.read_text().splitlines():
        name = json.loads(line)['scope']
        if not re.fullmatch(r'osri-[a-f0-9]{32}\.scope', name):
            raise ValueError('invalid registered scope')
        scopes.append(name)
    return scopes


def _stop_scope(name):
    subprocess.run(['systemctl','--user','kill','--kill-whom=all','--signal=KILL',name],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2, check=False)
    status = subprocess.run(['systemctl','--user','show',name,'--property=ActiveState','--value'],
                            capture_output=True, text=True, timeout=2, check=False)
    return status.returncode == 0 and status.stdout.strip() in {'inactive', 'failed'}


def recover(root):
    """Recover only a recorded quota image beneath a fresh guard-owned root.

    Call after the coordinator has stopped. Unexpected paths, active daemons,
    nested mounts or failed unmounts are reported and preserved.
    """
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('invalid guard root')
    root = root.resolve(strict=True)
    if not root.is_relative_to('/workspace') or not root.name.startswith('guard-') or root.stat().st_uid != os.getuid():
        raise ValueError('not an owned guard root')
    lockfile = root / 'guard.lock'
    if lockfile.is_symlink():
        raise ValueError('invalid guard lock')
    with lockfile.open('r+') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'status': 'blocked', 'reason': 'guard still active', 'root': str(root)}
        meta = root / 'guard-session.json'
        if meta.is_symlink() or not meta.is_file():
            return {'status':'blocked', 'reason':'missing session metadata', 'root':str(root)}
        try:
            session = json.loads(meta.read_text())
            boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
            if session['boot'] != boot:
                return {'status':'blocked', 'reason':'boot changed; reconcile scope manually', 'root':str(root)}
            if not session['completed'] and time.monotonic() < session['recover_after']:
                return {'status':'blocked', 'reason':'watchdog interval not elapsed', 'root':str(root)}
        except (OSError, KeyError, TypeError, ValueError):
            return {'status':'blocked', 'reason':'invalid session metadata', 'root':str(root)}
        try:
            for scope in _registered_scopes(root):
                if not _stop_scope(scope):
                    return {'status':'blocked', 'reason':'registered scope still active', 'root':str(root)}
        except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired):
            return {'status':'blocked', 'reason':'scope registry could not be reconciled', 'root':str(root)}
        return _recover_locked(root)


def _recover_locked(root):
    registration = root / 'guard-resources.json'
    if not registration.exists():
        leftovers = list(root.glob('quota-*'))
        return {'status': 'blocked' if leftovers else 'clean',
                'reason': 'unregistered quota resources' if leftovers else None, 'root': str(root)}
    if registration.is_symlink() or not registration.is_file():
        return {'status': 'blocked', 'reason': 'unsafe registration', 'root': str(root)}
    try:
        data = json.loads(registration.read_text())
        image, mount = Path(data['image']), Path(data['mount'])
        base = image.parent
        if (not image.is_absolute() or base.parent != root or not base.name.startswith('quota-')
                or image.name != 'scratch.ext4' or mount != base / 'mount'
                or base.is_symlink() or not base.is_dir() or base.stat().st_uid != os.getuid()):
            raise ValueError('paths outside recorded session')
        if image.is_symlink():
            raise ValueError('linked image')
        if image.exists():
            st = image.stat()
            if not image.is_file() or st.st_uid != os.getuid() or st.st_nlink != 1 or st.st_size > MAX_DISK:
                raise ValueError('unsafe image')
        mounts = _mount_at(mount)
        if len(mounts) > 1 or (mounts and mounts[0] != ('fuse.ext4', str(image))):
            raise ValueError('unexpected mounted filesystem')
        pid, start = data.get('daemon_pid'), data.get('daemon_starttime')
        if pid is not None and (not isinstance(pid, int) or pid <= 0 or not isinstance(start, str)):
            raise ValueError('invalid daemon identity')
        # Only unmount the recorded exact filesystem; no signal is sent to a PID.
        if mounts:
            unmount = subprocess.run(['fusermount3', '-u', str(mount)], capture_output=True, timeout=10)
            if unmount.returncode or _mount_at(mount):
                return {'status':'blocked', 'reason':'unmount failed', 'root':str(root)}
        if pid is not None and _proc_start(pid) == start:
            return {'status':'blocked', 'reason':'recorded daemon still running', 'root':str(root)}
        # Never recursively delete arbitrary content from an untrusted path.
        if mount.is_symlink():
            raise ValueError('linked mount path')
        if mount.exists():
            mount.rmdir()
        if image.exists():
            image.unlink()
        base.rmdir()
        registration.unlink()
        return {'status':'clean', 'reason':None, 'root':str(root)}
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError, subprocess.TimeoutExpired) as e:
        return {'status':'blocked', 'reason':str(e), 'root':str(root)}


def run_guarded(argv, *, workspace_parent, timeout=21600, output_bytes=8*1024**2):
    """Run a coordinator under a transient watchdog and recover its resources.

    Coordinator receives PILOT_SESSION_ROOT. It must use this directory for
    CaseSession workspace_parent and state_parent and register its quota image.
    The parent scope does not contain separately created case scopes; those have
    their own watchdogs. A blocked cleanup is retained and explicitly reported.
    """
    parent = Path(workspace_parent).resolve(strict=True)
    if not parent.is_dir() or not parent.is_relative_to('/workspace') or not argv:
        raise ValueError('invalid workspace parent or command')
    if not 0 < timeout <= 21600:
        raise ValueError('invalid deadline')
    root = Path(tempfile.mkdtemp(prefix='guard-', dir=parent))
    root.chmod(0o700)
    lock = (root / 'guard.lock').open('x+')
    fcntl.flock(lock, fcntl.LOCK_EX)
    started = time.monotonic()
    metadata = {'boot':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                'recover_after':time.monotonic() + timeout + 10,
                'completed':False}
    meta_path = root / 'guard-session.json'
    def save_meta():
        temporary = root / 'guard-session.tmp'
        with temporary.open('w') as out:
            json.dump(metadata, out)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, meta_path)
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(directory)
        finally: os.close(directory)
    save_meta()
    result = None
    scope = 'osri-' + uuid.uuid4().hex + '.scope'
    with (root / 'guard-scopes.jsonl').open('x') as registry:
        registry.write(json.dumps({'scope': scope}) + '\n')
        registry.flush()
        os.fsync(registry.fileno())
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try: os.fsync(directory)
    finally: os.close(directory)
    watchdog_stop = threading.Event()
    deadline = time.clock_gettime(time.CLOCK_BOOTTIME) + timeout
    def stop_scopes():
        try:
            scopes = {scope, *_registered_scopes(root)}
        except (OSError, ValueError, KeyError, TypeError):
            scopes = {scope}
        for name in scopes:
            try:
                _stop_scope(name)
            except (OSError, subprocess.TimeoutExpired):
                pass
    def watchdog():
        while not watchdog_stop.is_set():
            remaining = deadline - time.clock_gettime(time.CLOCK_BOOTTIME)
            if remaining > 0:
                watchdog_stop.wait(min(remaining, .1))
                continue
            stop_scopes()
            watchdog_stop.wait(.1)
    thread = threading.Thread(target=watchdog, daemon=True)
    thread.start()
    try:
        result = execute(['/usr/bin/env', 'PILOT_SESSION_ROOT=' + str(root), *argv],
                         timeout=timeout, output_bytes=output_bytes, memory_bytes=2 * 1024**3,
                         trusted_coordinator=True, unit_name=scope)
        metadata['completed'] = True
        save_meta()
    finally:
        # After an exception the watchdog still bounds a surviving session;
        # preserve the root rather than guessing whether it stopped.
        watchdog_stop.set()
        thread.join(timeout=5)
        stop_scopes()
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()
    cleanup = recover(root)
    return {'session_root':str(root), 'elapsed_seconds':time.monotonic()-started,
            'coordinator':result, 'cleanup':cleanup}
