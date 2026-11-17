import hashlib
import os
from pathlib import Path
import sys
import subprocess
import threading
import tempfile
import time
import unittest

from executor.supervisor import CaseBudget, execute, lock_outputs

BASE = Path(__file__).resolve().parents[2]

class SupervisorTests(unittest.TestCase):
    def test_scope_controls_and_oom(self):
        code = '''import os
p='/sys/fs/cgroup'+open('/proc/self/cgroup').read().split('::')[1].strip()
for x in ('memory.max','memory.swap.max','pids.max','cpu.max'):
 print(x,open(p+'/'+x).read().strip(),flush=True)
a=bytearray(128*1024*1024)
'''
        r = execute([sys.executable, '-c', code], timeout=10, memory_bytes=32*1024**2, cpu_quota=100, tasks_max=16)
        self.assertIn('memory.max 33554432', r['stdout'], r)
        self.assertIn('memory.swap.max 0', r['stdout'], r)
        self.assertIn('pids.max 16', r['stdout'], r)
        self.assertIn('cpu.max 100000 100000', r['stdout'], r)
        self.assertEqual(r['returncode'], -9, r)

    def test_affinity_inherited_and_widening_denied(self):
        cpus = sorted(os.sched_getaffinity(0))
        self.assertGreaterEqual(len(cpus), 2)
        selected, other = cpus[0], cpus[1]
        code = """import json,os,subprocess,sys
before=sorted(os.sched_getaffinity(0))
try: os.sched_setaffinity(0, {OTHER}); status='unexpected success'
except OSError as e: status=e.errno
child=subprocess.check_output([sys.executable,'-c',"import os; print(sorted(os.sched_getaffinity(0)))"]).decode().strip()
print(json.dumps({'before':before,'widen_errno':status,'child':child}))
""".replace('OTHER', str(other))
        r = execute([sys.executable, '-c', code], timeout=5, allowed_cpus=[selected], memory_bytes=64*1024**2)
        self.assertEqual(r['returncode'], 0, r)
        import json
        info = json.loads(r['stdout'])
        self.assertEqual(info['before'], [selected])
        self.assertEqual(info['widen_errno'], 1)
        self.assertEqual(info['child'], str([selected]))

    def test_fork_cap(self):
        code = '''import os,time
children=[]
try:
 while True:
  p=os.fork()
  if not p: time.sleep(10); os._exit(0)
  children.append(p)
except OSError as e:
 print('FORK_BLOCKED', e.errno, len(children), flush=True)
finally:
 for p in children: os.kill(p,9)
 for p in children: os.waitpid(p,0)
'''
        r = execute([sys.executable, '-c', code], timeout=8, memory_bytes=64*1024**2, tasks_max=8)
        self.assertIn('FORK_BLOCKED 11', r['stdout'], r)

    def test_timeout_kills_setsid_descendant(self):
        with tempfile.TemporaryDirectory(dir=BASE) as temp:
            marker = str(Path(temp)/'escaped')
            code = "import os,time; p=os.fork(); (os.setsid(),time.sleep(1),open(%r,'w').write('bad')) if p == 0 else time.sleep(20)" % marker
            r = execute([sys.executable, '-c', code], timeout=.3, memory_bytes=64*1024**2)
            self.assertTrue(r['timed_out'], r)
            time.sleep(1.2)
            self.assertFalse(Path(marker).exists())

    def test_successful_parent_cannot_leave_detached_child(self):
        with tempfile.TemporaryDirectory(dir=BASE) as temp:
            marker = str(Path(temp)/'escaped')
            code = "import os,time; p=os.fork(); (os.setsid(),os.close(1),os.close(2),time.sleep(1),open(%r,'w').write('bad')) if p == 0 else None" % marker
            r = execute([sys.executable, '-c', code], timeout=4, memory_bytes=64*1024**2)
            self.assertEqual(r['returncode'], 0, r)
            time.sleep(1.2)
            self.assertFalse(Path(marker).exists())

    def test_timeout_when_output_descriptors_closed(self):
        r = execute([sys.executable, '-c', 'import os,time; os.close(1); os.close(2); time.sleep(10)'], timeout=.3, memory_bytes=64*1024**2)
        self.assertTrue(r['timed_out'], r)
        self.assertLess(r['elapsed_seconds'], 2)

    def test_output_ceiling(self):
        r = execute([sys.executable, '-c', "import os; os.write(1,b'x'*1000000)"], timeout=5, output_bytes=4096, memory_bytes=64*1024**2)
        self.assertTrue(r['output_limit_exceeded'], r)
        self.assertLessEqual(len(r['stdout'].encode()) + len(r['stderr'].encode()), 4096)

    def test_scope_runtime_survives_coordinator_kill(self):
        with tempfile.TemporaryDirectory(dir=BASE) as temp:
            ready, marker = str(Path(temp)/'ready'), str(Path(temp)/'escaped')
            payload = "import time; open(%r,'w').write('ready'); time.sleep(2); open(%r,'w').write('bad')" % (ready, marker)
            wrapper = "from executor.supervisor import execute; import sys; execute([sys.executable,'-c',%r],timeout=.7,memory_bytes=67108864)" % payload
            proc = subprocess.Popen([sys.executable, '-c', wrapper], cwd=BASE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                deadline = time.monotonic() + 2
                while not Path(ready).exists() and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertTrue(Path(ready).exists())
                proc.kill(); proc.wait()
                time.sleep(2.2)
                self.assertFalse(Path(marker).exists())
            finally:
                if proc.poll() is None:
                    proc.kill(); proc.wait()

    def test_budget_concurrent_debits_and_overrun(self):
        with tempfile.TemporaryDirectory(dir=BASE) as temp:
            path = Path(temp)/'case.sqlite'
            b = CaseBudget(path, elapsed_seconds=30, vm_seconds=10, active_seconds=10, network_bytes=50)
            token = b.reserve(2, active=True)
            accepted = []
            def consume(): accepted.append(b.consume_network(1))
            threads = [threading.Thread(target=consume) for _ in range(100)]
            for thread in threads: thread.start()
            for thread in threads: thread.join()
            self.assertEqual(sum(accepted), 50)
            self.assertEqual(b.snapshot()['network_bytes'], 50)
            b.finish(token, 3)
            state = b.snapshot()
            self.assertEqual(state['vm_charged_seconds'], 3)
            self.assertEqual(state['active_charged_seconds'], 3)
            self.assertEqual(state['vm_remaining_seconds'], 7)
            self.assertLessEqual(b.remaining(active=True), 7)
            b.close()

    def test_case_budget_persists_across_commands(self):
        with tempfile.TemporaryDirectory(dir=BASE) as temp:
            path = Path(temp)/'case.sqlite'
            b = CaseBudget(path, elapsed_seconds=20, vm_seconds=10, active_seconds=6, network_bytes=10)
            first = b.reserve(5, active=True)
            b.finish(first, 3)
            second = b.reserve(3, active=True)
            self.assertTrue(b.consume_network(7))
            self.assertFalse(b.consume_network(4))
            b.close()
            b = CaseBudget(path, elapsed_seconds=20, vm_seconds=10, active_seconds=6, network_bytes=10)
            self.assertEqual(b.snapshot()['vm_charged_seconds'], 6)
            self.assertEqual(b.snapshot()['active_charged_seconds'], 6)
            self.assertEqual(b.snapshot()['network_bytes'], 7)
            with self.assertRaises(RuntimeError): b.reserve(1, active=True)
            self.assertFalse(b.transfer_allowed())
            with self.assertRaises(ValueError): b.finish(second, 1)
            third = b.reserve(1, active=False)
            self.assertTrue(b.consume_network(3))
            self.assertFalse(b.consume_network(1))
            b.finish(third, .5)
            self.assertFalse(b.consume_network(0))
            b.close()

    def test_live_reservation_revoked_on_finish_abandon_and_expiry(self):
        with tempfile.TemporaryDirectory(dir=BASE) as temp:
            b=CaseBudget(Path(temp)/'budget', elapsed_seconds=20, vm_seconds=10, active_seconds=10, network_bytes=100)
            self.assertFalse(b.transfer_allowed())
            token=b.reserve(1, active=True)
            self.assertTrue(b.transfer_allowed())
            b.finish(token, .1)
            self.assertFalse(b.transfer_allowed())
            token=b.reserve(1, active=False)
            self.assertTrue(b.transfer_allowed())
            self.assertTrue(b.abandon(token))
            self.assertFalse(b.abandon(token))
            self.assertFalse(b.transfer_allowed())
            charged=b.snapshot()['vm_charged_seconds']
            self.assertGreaterEqual(charged, 1)
            token=b.reserve(.1, active=False)
            time.sleep(.15)
            self.assertFalse(b.transfer_allowed())
            self.assertFalse(b.consume_network(1))
            b.abandon(token)
            b.close()
            self.assertFalse(b.transfer_allowed())

    def test_output_cap_counts_logical_sparse_bytes_across_files(self):
        with tempfile.TemporaryDirectory(dir=BASE) as temp:
            base=Path(temp); src=base/'source'; src.mkdir()
            (src/'one').write_bytes(b'abc')
            with (src/'sparse').open('wb') as stream: stream.truncate(8 * 1024**3)
            with self.assertRaises(ValueError): lock_outputs(src, base/'locked', ['one','sparse'], max_bytes=10)
            self.assertEqual((base/'locked'/'one').read_bytes(), b'abc')
            self.assertFalse((base/'locked'/'sparse').exists())
            (src/'two').write_bytes(b'defg')
            with self.assertRaises(ValueError): lock_outputs(src, base/'second', ['one','two'], max_bytes=6)

    def test_output_caps_files_and_path_length(self):
        with tempfile.TemporaryDirectory(dir=BASE) as temp:
            base=Path(temp); src=base/'source'; src.mkdir()
            (src/'one').write_bytes(b'1'); (src/'two').write_bytes(b'2')
            with self.assertRaises(ValueError): lock_outputs(src, base/'locked', ['one','two'], max_files=1)
            with self.assertRaises(ValueError): lock_outputs(src, base/'second', ['one'], max_path_bytes=2)

    def test_output_capture_rejects_links(self):
        with tempfile.TemporaryDirectory(dir=BASE) as temp:
            base=Path(temp); src=base/'source'; src.mkdir()
            (src/'ok').write_bytes(b'abc')
            records=lock_outputs(src, base/'locked', ['ok'])
            self.assertEqual(records[0]['sha256'], hashlib.sha256(b'abc').hexdigest())
            self.assertEqual((base/'locked'/'ok').stat().st_mode & 0o777, 0o400)
            (src/'link').symlink_to('ok')
            with self.assertRaises(OSError): lock_outputs(src, base/'bad', ['link'])
            os.link(src/'ok', src/'hard')
            with self.assertRaises(ValueError): lock_outputs(src, base/'bad2', ['ok'])

if __name__ == '__main__': unittest.main()
