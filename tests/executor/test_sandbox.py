import json
import os
from pathlib import Path
import tempfile
import time
import unittest

from executor.sandbox import run

BASE = Path(__file__).resolve().parents[2]

class SandboxBoundary(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=BASE)
        self.base = Path(self.tmp.name)
        self.scratch = self.base / 'scratch'
        self.scratch.mkdir()
        self.case = self.base / 'case'
        self.case.mkdir()
        (self.case / 'allowed').write_text('visible')
        (self.base / 'canary').write_text('SECRET_SYNTHETIC')

    def tearDown(self):
        self.tmp.cleanup()

    def run_python(self, code, **kw):
        return run(['/usr/bin/python3', '-c', code], scratch=self.scratch, timeout=kw.pop('timeout', 5), **kw)

    def test_filesystem_and_privileges(self):
        code = r'''import json, os
paths = ['/case/allowed', CANARY, '/proc/1/root' + CANARY, '/proc/1/cwd' + CANARY, '/workspace']
results = {}
for p in paths:
 try:
  with open(p) as f: results[p] = f.read()
 except OSError: results[p] = None
try:
 open('/case/allowed', 'w').write('changed')
 results['write'] = True
except OSError: results['write'] = False
s = open('/proc/self/status').read()
results['home'] = os.environ['HOME']
results['root_writable'] = {}
for p in ['/etc/probe', '/escape']:
 try: open(p, 'w').close(); results['root_writable'][p] = True
 except OSError: results['root_writable'][p] = False
results['caps'] = [x for x in s.splitlines() if x.startswith(('CapEff:', 'CapBnd:', 'NoNewPrivs:'))]
print(json.dumps(results))'''.replace('CANARY', repr(str(self.base / 'canary')))
        result = self.run_python(code, mounts={str(self.case): '/case'})
        self.assertEqual(result['returncode'], 0, result)
        data = json.loads(result['stdout'])
        self.assertEqual(data['/case/allowed'], 'visible')
        for path in [str(self.base / 'canary'), '/proc/1/root' + str(self.base / 'canary'), '/proc/1/cwd' + str(self.base / 'canary'), '/workspace']:
            self.assertIsNone(data[path], path)
        self.assertFalse(data['write'])
        self.assertEqual(data['home'], '/home/builderbob')
        self.assertEqual(data['root_writable'], {'/etc/probe': False, '/escape': False})
        self.assertIn('CapEff:\t0000000000000000', data['caps'])
        self.assertIn('CapBnd:\t0000000000000000', data['caps'])
        self.assertIn('NoNewPrivs:\t1', data['caps'])
        self.assertEqual((self.case / 'allowed').read_text(), 'visible')

    def test_rejects_linked_inputs(self):
        (self.case / 'link').symlink_to(self.base / 'canary')
        with self.assertRaises(ValueError):
            self.run_python('pass', mounts={str(self.case): '/case'})
        (self.case / 'link').unlink()
        os.link(self.base / 'canary', self.case / 'hardlink')
        with self.assertRaises(ValueError):
            self.run_python('pass', mounts={str(self.case): '/case'})

    def test_which_and_zoneinfo_readonly(self):
        script = """import json,subprocess
r=subprocess.run(['/usr/bin/which','python3'],capture_output=True,text=True)
out={'rc':r.returncode,'path':r.stdout.strip(), 'zone':bool(open('/usr/share/zoneinfo/zone.tab').read())}
try: open('/usr/share/zoneinfo/zone.tab','w').write('bad'); out['write']=True
except OSError: out['write']=False
print(json.dumps(out))"""
        result = self.run_python(script)
        self.assertEqual(result['returncode'], 0, result)
        self.assertEqual(json.loads(result['stdout']), {'rc':0,'path':'/usr/bin/python3','zone':True,'write':False})

    def test_network_and_mount_escape(self):
        code = r'''import socket, subprocess, json
s = socket.socket(); s.settimeout(.3)
try: s.connect(('1.1.1.1', 80)); network = True
except OSError: network = False
p = subprocess.run(['/usr/bin/mount', '--bind', '/proc', '/tmp'], capture_output=True)
print(json.dumps({'network':network, 'mount':p.returncode}))'''
        result = self.run_python(code)
        self.assertEqual(result['returncode'], 0, result)
        data = json.loads(result['stdout'])
        self.assertFalse(data['network'])
        self.assertNotEqual(data['mount'], 0)

    def test_case_budget_charges_repeated_commands(self):
        from executor.supervisor import CaseBudget
        budget = CaseBudget(self.base / 'budget.sqlite', elapsed_seconds=20,
                            vm_seconds=15, active_seconds=15, network_bytes=100)
        try:
            for _ in range(2):
                result = self.run_python('pass', timeout=1, budget=budget)
                self.assertEqual(result['returncode'], 0, result)
            self.assertGreater(budget.snapshot()['active_charged_seconds'], 0)
            with self.assertRaises(RuntimeError):
                self.run_python('pass', timeout=15, budget=budget)
        finally:
            budget.close()

    def test_failed_command_revokes_budget_authority(self):
        from executor.supervisor import CaseBudget
        budget = CaseBudget(self.base/'failure.sqlite', elapsed_seconds=30,
                            vm_seconds=20, active_seconds=20, network_bytes=100)
        try:
            with self.assertRaises(ValueError):
                run(['/usr/bin/true'], scratch=self.scratch, timeout=1, budget=budget,
                    mounts={str(self.case): '/usr/invalid'})
            self.assertFalse(budget.consume_network(1))
            self.assertGreaterEqual(budget.snapshot()['vm_charged_seconds'], 6)
        finally:
            budget.close()

    def test_output_limit_stops_flood(self):
        result = self.run_python("import os; b=b'x'*65536\nwhile True: os.write(1,b)")
        self.assertTrue(result['output_limit'], result)
        self.assertLessEqual(len(result['stdout'].encode()), 8 * 1024 * 1024)

    def test_host_descriptor_not_inherited(self):
        with open(self.base / 'canary') as secret:
            os.set_inheritable(secret.fileno(), True)
            code = "import os; print(os.path.exists('/proc/self/fd/%d'))" % secret.fileno()
            result = self.run_python(code)
        self.assertEqual(result['returncode'], 0, result)
        self.assertEqual(result['stdout'].strip(), 'False')

    def test_timeout_kills_session_escaping_descendant(self):
        marker = self.scratch / 'survived'
        code = "import os,time; p=os.fork(); (os.setsid(),time.sleep(2),open('/work/survived','w').write('bad')) if p == 0 else time.sleep(30)"
        result = self.run_python(code, timeout=.5)
        self.assertTrue(result['timed_out'], result)
        time.sleep(2.2)
        self.assertFalse(marker.exists())

    def test_disallow_overlapping_or_reserved_mounts(self):
        with self.assertRaises(ValueError):
            self.run_python('pass', mounts={str(self.case): '/usr/foo'})
        with self.assertRaises(ValueError):
            self.run_python('pass', mounts={str(self.base): '/input'})

if __name__ == '__main__':
    unittest.main()

class SandboxProxyIntegration(unittest.TestCase):
    def test_proxy_http_https_and_denial(self):
        import shutil
        import socket
        import socketserver
        import ssl
        import threading
        from executor.egress import EgressBroker, create_tls_material

        class Upstream(socketserver.BaseRequestHandler):
            def handle(self):
                self.request.recv(4096)
                self.request.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\nhello')

        with tempfile.TemporaryDirectory(dir='/workspace/repos/builderbob') as tmp:
            base = Path(tmp)
            scratch = base / 'scratch'
            scratch.mkdir()
            private = base / 'private'
            bundle = create_tls_material(private, ['example.test'])
            public_ca = base / 'ca.pem'
            shutil.copyfile(bundle, public_ca)
            http = socketserver.TCPServer(('127.0.0.1', 0), Upstream)
            https = socketserver.TCPServer(('127.0.0.1', 0), Upstream)
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(private / 'example.test.pem', private / 'example.test.key')
            https.socket = ctx.wrap_socket(https.socket, server_side=True)
            for server in (http, https):
                threading.Thread(target=server.serve_forever, daemon=True).start()
            trust = ssl.create_default_context(cafile=str(bundle))
            def resolver(host, port):
                server = https if port == 443 else http
                return [(socket.AF_INET, socket.SOCK_STREAM, 0, '', server.server_address)]
            script = '''import json, urllib.request, urllib.error
out = {}
for name in __import__('os').listdir('/proc'):
 if name.isdigit() and int(name) != __import__('os').getpid():
  try: __import__('os').kill(int(name), 9)
  except (ProcessLookupError, PermissionError): pass
for url in ('http://example.test/', 'https://example.test/', 'http://evil.test/'):
 try:
  with urllib.request.urlopen(url, timeout=4) as r: out[url] = [r.status, r.read().decode()]
 except urllib.error.HTTPError as e: out[url] = [e.code, '']
print(json.dumps(out))'''
            try:
                with EgressBroker(str(base/'broker.sock'), ['example.test'], 100000,
                                  tls_dir=private, _test_resolver=resolver,
                                  _test_upstream_context=trust):
                    result = run(['/usr/bin/python3', '-c', script],
                                 mounts={str(public_ca): '/input/ca.pem'}, scratch=scratch,
                                 timeout=10, proxy_socket=base/'broker.sock',
                                 env={'SSL_CERT_FILE': '/input/ca.pem'})
                    self.assertEqual(result['returncode'], 0, result)
                    response = json.loads(result['stdout'])
                    self.assertEqual(response['http://example.test/'], [200, 'hello'])
                    self.assertEqual(response['https://example.test/'], [200, 'hello'])
                    self.assertEqual(response['http://evil.test/'][0], 403)
            finally:
                for server in (http, https):
                    server.shutdown()
                    server.server_close()


@unittest.skipUnless(os.environ.get('PILOT_FUSE_RUNTIME'), 'set PILOT_FUSE_RUNTIME to extracted runtime directory')
class SandboxQuotaIntegration(unittest.TestCase):
    def test_home_and_tmp_on_bounded_scratch(self):
        from executor.quota_fs import QuotaFS
        root = Path(os.environ['PILOT_FUSE_RUNTIME']).resolve()
        with QuotaFS(root.parent, 32 * 1024**2, fuse2fs=root/'usr/bin/fuse2fs',
                     library_dir=root/'lib/x86_64-linux-gnu') as fs:
            code = r"""import errno,json,os
r={'home':os.environ['HOME']}
open('/home/builderbob/private', 'w').write('sandbox-home')
try:
 with open('/tmp/full', 'wb', buffering=0) as f:
  while True: f.write(b'x'*65536)
except OSError as e: r['errno']=e.errno
try: open('/etc/escape','w').close(); r['etc']=True
except OSError: r['etc']=False
try: open('/escape','w').close(); r['root']=True
except OSError: r['root']=False
print(json.dumps(r))"""
            result = run(['/usr/bin/python3', '-c', code], scratch=fs.mount, timeout=10)
            self.assertEqual(result['returncode'], 0, result)
            data = json.loads(result['stdout'])
            self.assertEqual(data, {'home': '/home/builderbob', 'errno': 28, 'etc': False, 'root': False})
            self.assertEqual((fs.mount/'.sandbox-home/private').read_text(), 'sandbox-home')
            self.assertIsNone(fs.process.poll())
