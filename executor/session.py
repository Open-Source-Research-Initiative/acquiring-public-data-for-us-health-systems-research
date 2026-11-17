"""Trusted coordinator composition for a single experimental pilot case.

No code in this module qualifies the runtime or authorizes a case. Host callers
must separately supervise model calls and route every reference operation through
the shared ledger. Closing the session destroys its quota image and contents.
"""
from contextlib import contextmanager
import hashlib
import fcntl
from pathlib import Path
import os
import shutil
import sys
import tempfile
import threading
import time

from executor.egress import EgressBroker, create_tls_material
from executor.quota_fs import QuotaFS
from executor.sandbox import _alias_source, _audit_input, run
from executor.archive import stage_archive
from executor.supervisor import CaseBudget


class CaseSession:
    """One bounded image, separate visible trees, one ledger and one broker.

    Input maps are trusted regular files to absolute sandbox targets. Files are
    copied into the quota image, audited before copying, and mounted read-only.
    Reference inputs and scratch are never mounted in executor invocations.
    Scratch and input trees must not be concurrently modified by host processes.
    """
    def __init__(self, *, workspace_parent, state_parent, ledger_path, fuse2fs,
                 library_dir, allowed_hosts, case_inputs=None, reference_inputs=None, guest_aliases=None, reference_aliases=None,
                 disk_bytes=100 * 1024**3, network_bytes=20 * 1024**3,
                 broker_timeout=15, allowed_schemes=('http', 'https'), budget_options=None, setup_reservation=120, _test_broker_options=None):
        self.workspace_parent = Path(workspace_parent).resolve(strict=True)
        self.state_parent = Path(state_parent).resolve(strict=True)
        for path in (self.workspace_parent, self.state_parent):
            if not path.is_dir() or not path.is_relative_to('/workspace'):
                raise ValueError('session parents must be workspace directories')
        guard_root = os.environ.get('PILOT_SESSION_ROOT')
        if guard_root:
            guard_path = Path(guard_root)
            if guard_path.is_symlink():
                raise ValueError('guard root cannot be a symlink')
            guard_path = guard_path.resolve(strict=True)
            if not guard_path.is_relative_to('/workspace') or self.workspace_parent != guard_path or self.state_parent != guard_path:
                raise ValueError('session parents must equal the guarded workspace root')
        self.guard_path = guard_path if guard_root else None
        if (not isinstance(disk_bytes, int) or isinstance(disk_bytes, bool)
                or not 16 * 1024**2 <= disk_bytes <= 100 * 1024**3):
            raise ValueError('disk limit must be between 16 MiB and 100 GiB')
        if self.guard_path and disk_bytes > 48 * 1024**3:
            raise ValueError('guarded disk limit cannot exceed 48 GiB')
        if (not isinstance(network_bytes, int) or isinstance(network_bytes, bool)
                or not 0 < network_bytes <= 20 * 1024**3):
            raise ValueError('network limit must be between 1 byte and 20 GiB')
        self.ledger_path = Path(ledger_path)
        self.fuse2fs, self.library_dir = fuse2fs, library_dir
        self.allowed_hosts = list(allowed_hosts)
        self.case_inputs = dict(case_inputs or {})
        self.reference_inputs = dict(reference_inputs or {})
        self.guest_aliases = dict(guest_aliases or {})
        self.reference_aliases = dict(reference_aliases or {})
        self.disk_bytes, self.network_bytes = disk_bytes, network_bytes
        self.broker_timeout = broker_timeout
        self.allowed_schemes = tuple(allowed_schemes)
        self.budget_options = dict(budget_options or {})
        self.setup_reservation = setup_reservation
        self.test_options = dict(_test_broker_options or {})
        self.budget = self.fs = self.broker = self.state = None
        self.open = False
        self._busy = threading.Lock()
        self.cleanup_token = None
        self.cleanup_unmetered = False
        self._guard_lock = None
        self.input_manifest = {'case': [], 'reference': []}

    def _copy_inputs(self, mapping, directory, label):
        directory.mkdir()
        result = {}
        for index, (original, target) in enumerate(mapping.items()):
            source = Path(original)
            if source.is_symlink():
                raise ValueError('input root must not be a symlink')
            source = source.resolve(strict=True)
            _audit_input(source)
            copied = directory / str(index)
            if not source.is_file():
                raise ValueError('session inputs must be regular files')
            shutil.copyfile(source, copied)
            copied.chmod(source.stat().st_mode & 0o777)
            files = [copied] if copied.is_file() else sorted(p for p in copied.rglob('*') if p.is_file())
            for path in files:
                digest = hashlib.sha256()
                with path.open('rb') as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                        digest.update(chunk)
                self.input_manifest[label].append({'target': target,
                    'path': '.' if path == copied else path.relative_to(copied).as_posix(),
                    'bytes': path.stat().st_size, 'mode': oct(path.stat().st_mode & 0o777), 'sha256': digest.hexdigest()})
            result[str(copied)] = target
        return result

    def __enter__(self):
        if self.budget is not None:
            raise RuntimeError('session cannot be re-entered')
        started = time.monotonic()
        token = None
        try:
            if self.guard_path:
                fd = os.open(self.guard_path / '.case-session.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BaseException:
                    os.close(fd)
                    raise RuntimeError('guard root already has a case session')
                self._guard_lock = fd
            self.budget = CaseBudget(self.ledger_path, network_bytes=self.network_bytes, **self.budget_options)
            token = self.budget.reserve(self.setup_reservation, active=False)
            self.state = tempfile.TemporaryDirectory(prefix='pilot-', dir=self.state_parent)
            state = Path(self.state.name)
            sock = state / 'proxy.sock'
            if len(os.fsencode(sock)) >= 108:
                raise ValueError('proxy socket path is too long; use a shorter workspace state parent')
            self.fs = QuotaFS(self.workspace_parent, self.disk_bytes, fuse2fs=self.fuse2fs,
                              library_dir=self.library_dir)
            self.fs.__enter__()
            self.executor_scratch = self.fs.mount / 'executor'
            self.reference_scratch = self.fs.mount / 'reference'
            self.executor_scratch.mkdir()
            self.reference_scratch.mkdir()
            self.executor_mounts = self._copy_inputs(self.case_inputs, self.fs.mount / 'case-input', 'case')
            self.reference_mounts = self._copy_inputs(self.reference_inputs, self.fs.mount / 'reference-input', 'reference')
            bundle = create_tls_material(state / 'private-tls', self.allowed_hosts)
            self.public_bundle = state / 'ca.pem'
            shutil.copyfile(bundle, self.public_bundle)
            self.broker = EgressBroker(sock, self.allowed_hosts, self.network_bytes, timeout=self.broker_timeout,
                                       tls_dir=state / 'private-tls', budget=self.budget,
                                       allowed_schemes=self.allowed_schemes,
                                       **self.test_options)
            self.broker.start()
            elapsed = time.monotonic() - started
            self.budget.finish(token, elapsed)
            if elapsed > self.setup_reservation:
                raise TimeoutError('session setup exceeded its reserved time')
            self.open = True
            return self
        except BaseException:
            # Retain the charge, but revoke its authority for further traffic.
            if token is not None and self.budget is not None:
                self.budget.abandon(token)
            self.close()
            raise

    def execute(self, argv, *, timeout, reference=False, env=None, network=True):
        if not self.open:
            raise RuntimeError('session is not open')
        if not self._busy.acquire(blocking=False):
            raise RuntimeError('session already has an active operation')
        try:
            if not self.open:
                raise RuntimeError('session is not open')
            mounts = dict(self.reference_mounts if reference else self.executor_mounts)
            if '/trust/ca.pem' in mounts.values():
                raise ValueError('reserved trust target')
            mounts[str(self.public_bundle)] = '/trust/ca.pem'
            environment = dict(env or {})
            for name in ('SSL_CERT_FILE', 'REQUESTS_CA_BUNDLE', 'CURL_CA_BUNDLE'):
                environment[name] = '/trust/ca.pem'
            return run(argv, mounts=mounts,
                       scratch=self.reference_scratch if reference else self.executor_scratch,
                       timeout=timeout, env=environment, proxy_socket=self.broker.socket_path if network else None,
                       budget=self.budget, active=not reference,
                       aliases=self.reference_aliases if reference else self.guest_aliases)
        finally:
            self._busy.release()

    def stage_runtime(self, input_target, *, destination, timeout, reference=False):
        """Stage a copied runtime archive under /work; no candidate code runs."""
        from pathlib import PurePosixPath
        relative = PurePosixPath(destination)
        if relative.is_absolute() or not relative.parts or '..' in relative.parts:
            raise ValueError('invalid runtime destination')
        mounts = self.reference_mounts if reference else self.executor_mounts
        scratch = self.reference_scratch if reference else self.executor_scratch
        aliases = self.reference_aliases if reference else self.guest_aliases
        matches = [source for source, target in mounts.items() if target == input_target]
        if len(matches) != 1:
            raise ValueError('runtime archive target must identify one case input')
        with self.external_reservation(timeout, active=False):
            parent = scratch
            if len(relative.parts) > 1:
                parent = Path(_alias_source(scratch, str(PurePosixPath(*relative.parts[:-1]))))
            return stage_archive(matches[0], parent / relative.parts[-1],
                                 guest_root='/work/' + str(relative),
                                 allowed_guest_roots=tuple(aliases),
                                 max_bytes=self.disk_bytes)

    @contextmanager
    def external_reservation(self, timeout, *, active=True):
        """Charge externally supervised work; caller must enforce its timeout.

        Exceptions retain the full reservation. This does not interrupt model calls.
        """
        if not self.open:
            raise RuntimeError('session is not open')
        if not self._busy.acquire(blocking=False):
            raise RuntimeError('session already has an active operation')
        try:
            if not self.open:
                raise RuntimeError('session is not open')
            token = self.budget.reserve(timeout, active=active)
            started = time.monotonic()
            try:
                yield
            except BaseException:
                self.budget.abandon(token)
                raise
            else:
                elapsed = time.monotonic() - started
                self.budget.finish(token, elapsed)
                if elapsed > timeout:
                    raise TimeoutError('externally supervised operation exceeded its reservation')
        finally:
            self._busy.release()

    def close(self):
        if not self._busy.acquire(blocking=False):
            raise RuntimeError('cannot close while an operation is active')
        try:
            self._close()
        finally:
            self._busy.release()

    def _close(self):
        started = time.monotonic()
        if self.open and self.budget:
            try:
                self.cleanup_token = self.budget.reserve(5, active=False)
            except RuntimeError:
                # Always remove the live sandbox even when no budget remains.
                self.cleanup_unmetered = True
        self.open = False
        try:
            if self.broker:
                self.broker.close()
                self.broker = None
        finally:
            try:
                if self.fs:
                    self.fs.__exit__(None, None, None)
                    self.fs = None
            finally:
                if self.state:
                    self.state.cleanup()
                    self.state = None
                if self.budget:
                    if self.cleanup_token is not None:
                        if sys.exc_info()[0] is not None:
                            self.budget.abandon(self.cleanup_token)
                        else:
                            try:
                                self.budget.finish(self.cleanup_token, time.monotonic() - started)
                            except BaseException:
                                self.budget.abandon(self.cleanup_token)
                                raise
                        self.cleanup_token = None
                    self.budget.close()
                    self.budget = None
        if self._guard_lock is not None:
            fcntl.flock(self._guard_lock, fcntl.LOCK_UN)
            os.close(self._guard_lock)
            self._guard_lock = None

    def __exit__(self, *_):
        self.close()
