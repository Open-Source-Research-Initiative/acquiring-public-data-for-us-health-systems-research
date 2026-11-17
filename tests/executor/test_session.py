"""Synthetic session integration; no third-party code or public data."""
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest

from executor.session import CaseSession

RUNTIME = os.environ.get('PILOT_FUSE_RUNTIME')


@unittest.skipUnless(RUNTIME, 'set PILOT_FUSE_RUNTIME to extracted runtime directory')
class CaseSessionTests(unittest.TestCase):
    def test_shared_quota_separate_reference_and_accounting(self):
        runtime = Path(RUNTIME).resolve()
        with tempfile.TemporaryDirectory(dir='/workspace/repos/builderbob') as temp:
            base = Path(temp)
            case = base / 'source.tar'
            with tarfile.open(case, 'w') as archive:
                data = b'synthetic-source'
                info = tarfile.TarInfo('source.txt')
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
            executable = base / 'unzip'
            executable.write_text('#!/bin/sh\nprintf executable-ok')
            executable.chmod(0o755)
            ref = base / 'reference.txt'
            ref.write_text('synthetic-reference-secret')
            with CaseSession(workspace_parent=runtime.parent, state_parent=base,
                             ledger_path=base/'case.sqlite', fuse2fs=runtime/'usr/bin/fuse2fs',
                             library_dir=runtime/'lib/x86_64-linux-gnu',
                             allowed_hosts=['example.test'], case_inputs={case:'/inputs/source.tar', executable:'/inputs/unzip'},
                             reference_inputs={ref:'/inputs/reference.txt'}, disk_bytes=32*1024**2,
                             network_bytes=10000, setup_reservation=10,
                             budget_options={'elapsed_seconds':300, 'vm_seconds':120, 'active_seconds':60}) as session:
                executor = "import tarfile,os,json; t=tarfile.open('/inputs/source.tar'); print(json.dumps({'source':t.extractfile('source.txt').read().decode(),'ref':os.path.exists('/inputs/reference.txt'), 'other':os.path.exists('/work/../reference')}))"
                result = session.execute(['/usr/bin/python3','-c',executor], timeout=5)
                self.assertEqual(result['returncode'], 0, result)
                self.assertEqual(json.loads(result['stdout']), {'source':'synthetic-source','ref':False,'other':False})
                exe = session.execute(['/inputs/unzip'], timeout=5)
                self.assertEqual(exe['stdout'], 'executable-ok', exe)
                with session.external_reservation(5):
                    with self.assertRaises(RuntimeError):
                        session.execute(['/usr/bin/true'], timeout=5)
                    with self.assertRaises(RuntimeError):
                        session.close()
                with self.assertRaisesRegex(RuntimeError, 'synthetic failure'):
                    with session.external_reservation(5):
                        raise RuntimeError('synthetic failure')
                self.assertFalse(session.budget.consume_network(1))
                before = session.budget.snapshot()
                result = session.execute(['/usr/bin/cat','/inputs/reference.txt'], timeout=5, reference=True)
                self.assertEqual(result['returncode'], 0, result)
                self.assertEqual(result['stdout'], 'synthetic-reference-secret')
                after = session.budget.snapshot()
                self.assertGreater(after['vm_charged_seconds'], before['vm_charged_seconds'])
                self.assertEqual(after['active_charged_seconds'], before['active_charged_seconds'])
                with session.external_reservation(5, active=True):
                    pass
                self.assertGreater(session.budget.snapshot()['active_charged_seconds'], after['active_charged_seconds'])
                self.assertEqual((session.fs.mount.parent/'scratch.ext4').stat().st_size, 32*1024**2)
                self.assertNotEqual(session.executor_scratch, session.reference_scratch)
            self.assertFalse(session.open)
            self.assertTrue((base/'case.sqlite').exists())

    def test_shared_network_accounting(self):
        import socket
        import socketserver
        import threading
        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                self.request.recv(4096)
                self.request.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok')
        server = socketserver.TCPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        runtime = Path(RUNTIME).resolve()
        try:
            with tempfile.TemporaryDirectory(dir='/workspace/repos/builderbob') as temp:
                base = Path(temp)
                def resolver(host, port):
                    return [(socket.AF_INET, socket.SOCK_STREAM, 0, '', server.server_address)]
                with CaseSession(workspace_parent=runtime.parent, state_parent=base,
                                 ledger_path=base/'case.sqlite', fuse2fs=runtime/'usr/bin/fuse2fs',
                                 library_dir=runtime/'lib/x86_64-linux-gnu',
                                 allowed_hosts=['example.test'], disk_bytes=32*1024**2,
                                 setup_reservation=10, _test_broker_options={'_test_resolver':resolver}) as session:
                    command = ['/usr/bin/python3','-c', "import urllib.request; print(urllib.request.urlopen('http://example.test/').read().decode())"]
                    first = session.execute(command, timeout=5)
                    self.assertEqual(first['stdout'].strip(), 'ok', first)
                    first_bytes = session.broker.transferred
                    second = session.execute(command, timeout=5, reference=True)
                    self.assertEqual(second['stdout'].strip(), 'ok', second)
                    self.assertGreater(session.broker.transferred, first_bytes)
                    self.assertGreaterEqual(session.budget.snapshot()['network_bytes'], session.broker.transferred)
        finally:
            server.shutdown()
            server.server_close()

    def test_guard_root_registration_and_validation(self):
        from unittest.mock import patch
        runtime = Path(RUNTIME).resolve()
        with tempfile.TemporaryDirectory(dir='/workspace/repos/builderbob') as temp:
            base = Path(temp)
            with patch.dict(os.environ, {'PILOT_SESSION_ROOT': str(base)}):
                with self.assertRaises(ValueError):
                    CaseSession(workspace_parent=runtime.parent, state_parent=base,
                                ledger_path=base/'case.sqlite', fuse2fs=runtime/'usr/bin/fuse2fs',
                                library_dir=runtime/'lib/x86_64-linux-gnu', allowed_hosts=['example.test'])
                with self.assertRaises(ValueError):
                    CaseSession(workspace_parent=base, state_parent=base,
                                ledger_path=base/'case.sqlite', fuse2fs=runtime/'usr/bin/fuse2fs',
                                library_dir=runtime/'lib/x86_64-linux-gnu', allowed_hosts=['example.test'],
                                disk_bytes=48*1024**3 + 1)
                with CaseSession(workspace_parent=base, state_parent=base,
                                 ledger_path=base/'case.sqlite', fuse2fs=runtime/'usr/bin/fuse2fs',
                                 library_dir=runtime/'lib/x86_64-linux-gnu', allowed_hosts=['example.test'],
                                 disk_bytes=32*1024**2, setup_reservation=10, broker_timeout=30,
                                 allowed_schemes=('http',)) as session:
                    record = json.loads((base/'guard-resources.json').read_text())
                    self.assertEqual(record['phase'], 'started')
                    self.assertEqual(record['daemon_pid'], session.fs.process.pid)
                    self.assertTrue(record['daemon_starttime'].isdigit())
                    self.assertEqual(Path(record['image']), session.fs.mount.parent/'scratch.ext4')
                    self.assertEqual(Path(record['mount']), session.fs.mount)
                    self.assertEqual(session.broker.timeout, 30)
                    self.assertEqual(session.broker.allowed_schemes, frozenset({'http'}))
                    with self.assertRaises(RuntimeError):
                        with CaseSession(workspace_parent=base, state_parent=base,
                                         ledger_path=base/'other.sqlite', fuse2fs=runtime/'usr/bin/fuse2fs',
                                         library_dir=runtime/'lib/x86_64-linux-gnu', allowed_hosts=['example.test'],
                                         disk_bytes=32*1024**2, setup_reservation=10):
                            pass
                self.assertFalse((base/'guard-resources.json').exists())

    def test_rejects_protocol_resource_excess(self):
        runtime = Path(RUNTIME).resolve()
        with tempfile.TemporaryDirectory(dir='/workspace/repos/builderbob') as temp:
            base = Path(temp)
            args = dict(workspace_parent=base, state_parent=base, ledger_path=base/'case.sqlite',
                        fuse2fs=runtime/'usr/bin/fuse2fs', library_dir=runtime/'lib/x86_64-linux-gnu',
                        allowed_hosts=['example.test'])
            with self.assertRaises(ValueError):
                CaseSession(**args, disk_bytes=100*1024**3 + 1)
            with self.assertRaises(ValueError):
                CaseSession(**args, network_bytes=20*1024**3 + 1)

    def test_reject_linked_source(self):
        runtime = Path(RUNTIME).resolve()
        with tempfile.TemporaryDirectory(dir='/workspace/repos/builderbob') as temp:
            base = Path(temp)
            source = base/'source'
            source.mkdir()
            (source/'link').symlink_to('/etc/passwd')
            with self.assertRaises(ValueError):
                with CaseSession(workspace_parent=runtime.parent, state_parent=base,
                                 ledger_path=base/'case.sqlite', fuse2fs=runtime/'usr/bin/fuse2fs',
                                 library_dir=runtime/'lib/x86_64-linux-gnu',
                                 allowed_hosts=['example.test'], case_inputs={source:'/inputs'},
                                 disk_bytes=32*1024**2, setup_reservation=10):
                    pass
