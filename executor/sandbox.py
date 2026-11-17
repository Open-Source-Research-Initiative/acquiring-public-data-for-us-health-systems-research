"""Experimental rootless Linux executor; not a security certification.

Only caller-selected inputs are mounted. Do not run third-party code until the
separate agent, egress and resource controls have been qualified.
"""
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import socket as sockets
import time
import subprocess
import sys
import tempfile


WORKSPACE = Path('/workspace').resolve()


def _workspace_dir(path):
    p = Path(path).resolve(strict=True)
    if not p.is_dir() or p == WORKSPACE or WORKSPACE not in p.parents:
        raise ValueError('scratch must be an existing directory below /workspace')
    return p


def _audit_input(path):
    """Reject links, special files and nested filesystem mounts in trusted inputs.

    This is a preflight check, not a defense against concurrent host mutation.
    """
    root = Path(path)
    device = root.lstat().st_dev
    pending = [root]
    while pending:
        entry = pending.pop()
        st = entry.lstat()
        if st.st_dev != device or stat.S_ISLNK(st.st_mode):
            raise ValueError('input contains symlink or nested filesystem')
        if stat.S_ISDIR(st.st_mode):
            pending.extend(entry.iterdir())
        elif not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
            raise ValueError('input contains nonregular or hard-linked file')


def _run(command, *, mounts=None, scratch, timeout, env=None, proxy_socket=None):
    """Run argv in a fresh namespace. mounts maps host source to absolute target.

    Scratch is writable at /work; all other explicitly mounted inputs are
    read-only. Combined stdout/stderr is capped at 8 MiB.
    This function does not enforce CPU, memory, disk, or network byte quotas.
    """
    from executor.supervisor import execute
    scratch = _workspace_dir(scratch)
    _audit_input(scratch)
    if not command or not all(isinstance(x, str) and '\0' not in x for x in command):
        raise ValueError('command must be a nonempty argv')
    if not isinstance(timeout, (int, float)) or not 0 < timeout <= 21600:
        raise ValueError('timeout must be between zero and six hours')
    pairs = []
    for src, dst in (mounts or {}).items():
        original = Path(src)
        if original.is_symlink():
            raise ValueError('input root must not be a symlink')
        source = original.resolve(strict=True)
        _audit_input(source)
        target = PurePosixPath(dst)
        if not target.is_absolute() or '..' in target.parts or str(target) == '/' or target.parts[1] in {'usr','bin','lib','lib64','dev','proc','work','etc','tmp','run','home'}:
            raise ValueError('invalid or reserved mount target')
        if source == scratch or source in scratch.parents or scratch in source.parents:
            raise ValueError('input and scratch must not overlap')
        if not (source.is_file() or source.is_dir()):
            raise ValueError('input must be a regular file or directory')
        if any(target == t or target in t.parents or t in target.parents for _, t in pairs):
            raise ValueError('overlapping mount targets')
        pairs.append((source, target))
    if proxy_socket is not None:
        socket = Path(proxy_socket).resolve(strict=True)
        if not socket.is_socket():
            raise ValueError('proxy_socket must be a Unix socket')
    else:
        socket = None
    environment = {'PATH': '/usr/bin:/bin', 'HOME': '/home/builderbob', 'TMPDIR': '/work', 'LANG': 'C.UTF-8'}
    if env:
        for key, value in env.items():
            if not isinstance(key, str) or not isinstance(value, str) or not key or '=' in key or '\0' in key + value:
                raise ValueError('invalid environment')
            if key == 'HOME' and value != '/home/builderbob':
                raise ValueError('HOME must remain the private sandbox home')
            environment[key] = value
    if socket:
        proxy = 'http://127.0.0.1:18763'
        environment.update({key: proxy for key in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy')})
        environment.update({'NO_PROXY': '', 'no_proxy': ''})
    home = scratch / '.sandbox-home'
    home.mkdir(mode=0o700, exist_ok=True)
    # Root assembly directory is a sibling of scratch, never a host-wide mount.
    root = Path(tempfile.mkdtemp(prefix='.executor-root-', dir=scratch.parent))
    config = {'root': str(root), 'scratch': str(scratch), 'mounts': [(str(s), str(t)) for s,t in pairs], 'command': command, 'env': environment, 'socket': str(socket) if socket else None}
    namespaces = ['unshare', '--user', '--map-root-user', '--mount', '--net', '--ipc', '--uts', '--fork', '--kill-child=KILL', '--propagation', 'private']
    if socket:
        argv = namespaces + [sys.executable, str(Path(__file__).resolve()), '--outer', json.dumps(config)]
    else:
        argv = namespaces + ['unshare', '--pid', '--fork', '--kill-child=KILL', sys.executable, str(Path(__file__).resolve()), '--init', json.dumps(config)]
    try:
        cpus = sorted(os.sched_getaffinity(0))[:4]
        result = execute(argv, timeout=timeout, allowed_cpus=cpus, output_bytes=8 * 1024 * 1024)
        result['output_limit'] = result['output_limit_exceeded']
        return result
    finally:
        shutil.rmtree(root, ignore_errors=True)


def run(command, *, mounts=None, scratch, timeout, env=None, proxy_socket=None,
        budget=None, active=True, budget_margin_seconds=5):
    """Run a sandbox command; optionally charge preparation and cleanup too.

    Reserve the execution timeout plus a fixed cleanup margin before any work.
    Failures retain the complete reservation for conservative reconciliation.
    """
    started = time.monotonic()
    reservation = None
    if budget is not None:
        if not isinstance(budget_margin_seconds, (int, float)) or budget_margin_seconds < 0:
            raise ValueError('invalid budget margin')
        reservation = budget.reserve(timeout + budget_margin_seconds, active=active)
    try:
        result = _run(command, mounts=mounts, scratch=scratch, timeout=timeout,
                      env=env, proxy_socket=proxy_socket)
        if reservation is not None:
            elapsed = time.monotonic() - started
            budget.finish(reservation, elapsed)
            result['budget_charged_seconds'] = elapsed
            result['budget_cleanup_overrun_seconds'] = max(0, elapsed - timeout)
        return result
    except BaseException:
        if reservation is not None:
            budget.abandon(reservation)
        raise



def _init(config):
    root = Path(config['root'])
    def call(*args):
        subprocess.run(args, check=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
    def bind(src, target, readonly=True):
        dst = root / target.lstrip('/')
        dst.parent.mkdir(parents=True, exist_ok=True)
        if Path(src).is_dir():
            dst.mkdir(exist_ok=True)
        else:
            dst.touch()
        call('mount', '--bind', src, str(dst))
        if readonly:
            call('mount', '-o', 'remount,bind,ro,nosuid,nodev', str(dst))
    # Give the root its own mount so it can be sealed read-only after setup.
    call('mount', '--bind', str(root), str(root))
    # Bind only runtime directories; bind does not include nested submounts.
    for component in ('bin', 'sbin', 'lib', 'lib64'):
        source = '/usr/' + component
        if Path(source).is_dir():
            bind(source, source)
    bind('/etc/ssl/certs', '/etc/ssl/certs')
    for link in ('bin', 'lib', 'lib64', 'sbin'):
        src = Path('/') / link
        if src.is_symlink():
            (root / link).symlink_to(os.readlink(src))
        elif src.exists():
            bind(str(src), '/' + link)
    for directory in ('proc', 'dev', 'etc', 'work'):
        (root / directory).mkdir(exist_ok=True)
    (root / 'tmp').symlink_to('/work')
    for dev in ('null', 'zero', 'random', 'urandom'):
        bind('/dev/' + dev, '/dev/' + dev, readonly=False)
    bind(config['scratch'], '/work', readonly=False)
    bind(str(Path(config['scratch']) / '.sandbox-home'), '/home/builderbob', readonly=False)
    for src, dst in config['mounts']:
        bind(src, dst)
    if config['socket']:
        bind(config['socket'], '/run/executor-proxy.sock', readonly=False)
    call('mount', '-t', 'proc', '-o', 'nosuid,nodev,noexec', 'proc', str(root / 'proc'))
    call('mount', '-o', 'remount,bind,ro,nosuid,nodev', str(root))
    os.chroot(root)
    os.chdir('/')
    # PID 1 in the new namespace; on its death the kernel kills remaining tasks.
    os.execve('/usr/bin/setpriv', ['setpriv', '--bounding-set=-all', '--inh-caps=-all', '--ambient-caps=-all', '--no-new-privs', '--'] + config['command'], config['env'])


def _outer(config):
    """Start the relay outside the candidate PID namespace and then enter it."""
    subprocess.run(['/usr/sbin/ip', 'link', 'set', 'lo', 'up'], check=True)
    relay = subprocess.Popen(['/usr/bin/setpriv', '--bounding-set=-all', '--inh-caps=-all',
                              '--ambient-caps=-all', '--no-new-privs', '--', '/usr/bin/python3',
                              str(Path(__file__).with_name('egress.py')), 'forward',
                              '--socket', config['socket'], '--port', '18763'],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, close_fds=True,
                             env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'})
    try:
        for _ in range(100):
            if relay.poll() is not None:
                raise RuntimeError('proxy relay failed to start')
            try:
                with sockets.create_connection(('127.0.0.1', 18763), timeout=.1):
                    break
            except OSError:
                time.sleep(.02)
        else:
            raise RuntimeError('proxy relay did not become ready')
        child = subprocess.run(['unshare', '--pid', '--fork', '--kill-child=KILL',
                                sys.executable, str(Path(__file__).resolve()), '--init',
                                json.dumps(config)], check=False)
        return child.returncode
    finally:
        relay.terminate()
        try:
            relay.wait(timeout=2)
        except subprocess.TimeoutExpired:
            relay.kill()
            relay.wait()


if __name__ == '__main__' and len(sys.argv) == 3 and sys.argv[1] == '--init':
    _init(json.loads(sys.argv[2]))
elif __name__ == '__main__' and len(sys.argv) == 3 and sys.argv[1] == '--outer':
    sys.exit(_outer(json.loads(sys.argv[2])))
