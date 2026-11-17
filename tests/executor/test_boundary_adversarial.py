"""Independent synthetic checks; passing is not sandbox qualification."""
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import unittest

from executor.sandbox import run
from executor.egress import EgressBroker

BASE = Path(__file__).resolve().parents[2]

class BoundaryAdversarial(unittest.TestCase):
    def test_host_process_environment_and_inherited_fd(self):
        with tempfile.TemporaryDirectory(dir=BASE) as td:
            root = Path(td)
            scratch = root / 'scratch'; scratch.mkdir()
            canary = root / 'canary'; canary.write_text('SYNTHETIC_SECRET_48372')
            fd = os.open(canary, os.O_RDONLY)
            old = os.environ.get('SYNTHETIC_SECRET_ENV')
            os.environ['SYNTHETIC_SECRET_ENV'] = 'SYNTHETIC_SECRET_48372'
            try:
                script = r'''import os,json
paths = ['/proc/1/root' + HOST, '/proc/1/cwd' + HOST, '/proc/1/fd/FD', '/proc/self/fd/FD', HOST, '/workspace', '/home/builderbob']
r = {}
for p in paths:
 try:
  with open(p) as f: r[p] = f.read(100)
 except OSError: r[p] = None
print(json.dumps({'paths':r,'env':os.environ.get('SYNTHETIC_SECRET_ENV')}))'''.replace('HOST',repr(str(canary))).replace('FD', str(fd))
                result = run(['/usr/bin/python3','-c',script], scratch=scratch, timeout=5)
                self.assertEqual(result['returncode'], 0, result)
                data = json.loads(result['stdout'])
                self.assertIsNone(data['env'])
                self.assertTrue(all(v is None for v in data['paths'].values()), data)
            finally:
                os.close(fd)
                if old is None: os.environ.pop('SYNTHETIC_SECRET_ENV', None)
                else: os.environ['SYNTHETIC_SECRET_ENV'] = old

    def test_connect_without_tls_inspection_is_denied(self):
        # Regression for the historical opaque CONNECT tunnel. Keep the original
        # finding in evidence; current broker must refuse uninspected tunnels.
        with tempfile.TemporaryDirectory(dir='/workspace/repos/builderbob', prefix='.br-') as td:
            path = str(Path(td) / 'p.sock')
            with EgressBroker(path, {'allowed.example'}, 10000):
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                    client.settimeout(3)
                    client.connect(path)
                    client.sendall(b'CONNECT allowed.example:443 HTTP/1.1\r\nHost: allowed.example:443\r\n\r\n')
                    self.assertIn(b'403', client.recv(4096))

if __name__ == '__main__': unittest.main()
