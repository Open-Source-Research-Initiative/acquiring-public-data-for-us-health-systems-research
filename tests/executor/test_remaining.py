import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from executor.remaining import _native_argv, _output_paths, _prepare_attempt, _predebit
from executor.supervisor import CaseBudget

BASE = '/workspace/repos/builderbob'


class RemainingTests(unittest.TestCase):
    def test_native_group_redirects_entire_command(self):
        argv = _native_argv("printf first; printf second >&2")
        self.assertEqual(argv[:2], ['bash', '-c'])
        self.assertIn('( printf first; printf second >&2 ) > /work/output/native.stdout', argv[2])
        self.assertIn('2> /work/output/native.stderr', argv[2])

    def test_reference_root_and_reject_link_or_fifo(self):
        with tempfile.TemporaryDirectory(dir=BASE) as tmp:
            root = Path(tmp)
            (root/'a').mkdir()
            (root/'a'/'b').write_text('ok')
            self.assertEqual(_output_paths(root, ['.']), ['a/b'])
            (root/'escape').symlink_to('/etc')
            with self.assertRaises(ValueError):
                _output_paths(root, ['escape/passwd'])
            (root/'escape').unlink()
            os.mkfifo(root/'fifo')
            with self.assertRaises(ValueError):
                _output_paths(root, ['.'])

    def test_setup_resume_requires_ledger_and_no_native_marker(self):
        with tempfile.TemporaryDirectory(dir=BASE) as tmp:
            attempt = Path(tmp)/'attempt'
            _prepare_attempt(attempt, False)
            (attempt/'status.json').write_text(json.dumps({'status':'setup_failed'}))
            (attempt/'lock.json').write_text('old')
            with self.assertRaises(ValueError):
                _prepare_attempt(attempt, True)
            (attempt/'budget.sqlite').touch()
            (attempt/'native-start.json').write_text('{}')
            with self.assertRaises(ValueError):
                _prepare_attempt(attempt, True)
            (attempt/'native-start.json').unlink()
            _prepare_attempt(attempt, True)
            self.assertEqual((attempt/'setup-history-1/lock.json').read_text(), 'old')
            self.assertTrue((attempt/'budget.sqlite').exists())

    def test_aggregate_history_counts_control_and_output(self):
        from unittest.mock import patch
        import executor.remaining as runner
        with tempfile.TemporaryDirectory(dir=BASE) as tmp:
            root = Path(tmp)
            history = root/'setup-history-1'
            (history/'setup-outputs').mkdir(parents=True)
            (history/'old.json').write_bytes(b'a'*10)
            (history/'setup-outputs/data').write_bytes(b'b'*70)
            with patch.object(runner, 'OUTPUT_LIMIT', 100):
                self.assertEqual(runner._output_remaining(root), 30)
            with patch.object(runner, 'CONTROL_LIMIT', 1024**2+20):
                with self.assertRaises(RuntimeError):
                    runner._control_write(root, root/'new.json', b'x'*11)

    def test_receipt_binding_rejects_changed_plan_and_corrupt_prior_status(self):
        from unittest.mock import patch
        import hashlib
        import executor.remaining as runner
        with tempfile.TemporaryDirectory(dir=BASE) as tmp:
            root = Path(tmp)
            runtime = root/'runtime'; (runtime/'attempts').mkdir(parents=True)
            guarded = root/'guard'; guarded.mkdir()
            spec = root/'spec.json'; spec.write_text(json.dumps({'case_id':'PILOT-02'}))
            packet = runner.ROOT/'protocol/pilot/execution/PILOT-02.json'
            binding = {'case_plan_sha256': {'PILOT-02':'wrong'},
                       'case_packet_sha256': {'PILOT-02':runner.digest(packet)}}
            with patch.dict(os.environ, {'PILOT_SESSION_ROOT':str(guarded)}), \
                 patch.object(runner, 'check_receipt', return_value=binding):
                with self.assertRaisesRegex(RuntimeError, 'bind'):
                    runner.run_case(runtime, runtime/'attempts/new', root/'receipt', spec)
                binding['case_plan_sha256']['PILOT-02'] = hashlib.sha256(spec.read_bytes()).hexdigest()
                prior = runtime/'attempts/PILOT-02-prior'; prior.mkdir()
                (prior/'status.json').write_text('{bad')
                (prior/'native-start.json').write_text('{}')
                with self.assertRaisesRegex(RuntimeError, 'corrupt'):
                    runner.run_case(runtime, runtime/'attempts/new', root/'receipt', spec)

    def test_supplemental_manifest_detects_changes(self):
        import hashlib
        from executor.remaining import _check_supplemental_manifests
        with tempfile.TemporaryDirectory(dir=BASE) as tmp:
            root = Path(tmp)
            source = root/'zone.tab'
            source.write_bytes(b'synthetic zone data')
            manifest = root/'manifest.jsonl'
            entry = {'path':str(source), 'type':'file', 'mode':format(source.stat().st_mode & 0o7777,'04o'),
                     'sha256':hashlib.sha256(source.read_bytes()).hexdigest()}
            manifest.write_text(json.dumps(entry)+'\n')
            receipt = {'supplemental_host_manifests':[{'path':str(manifest),
                        'sha256':hashlib.sha256(manifest.read_bytes()).hexdigest()}]}
            _check_supplemental_manifests(receipt)
            source.write_bytes(b'changed')
            with self.assertRaises(RuntimeError):
                _check_supplemental_manifests(receipt)
            manifest.write_text('{}\n')
            with self.assertRaises(RuntimeError):
                _check_supplemental_manifests(receipt)

    def test_predebit_is_durable_and_not_live_afterward(self):
        with tempfile.TemporaryDirectory(dir=BASE) as tmp:
            path = Path(tmp)/'budget.sqlite'
            _predebit(path, 1234)
            budget = CaseBudget(path)
            try:
                self.assertEqual(budget.snapshot()['network_bytes'], 1234)
                self.assertFalse(budget.transfer_allowed())
            finally:
                budget.close()

if __name__ == '__main__':
    unittest.main()

class RemainingCoordinatorTests(unittest.TestCase):
    def test_synthetic_primary_locks_once_and_reference_stays_private(self):
        from unittest.mock import patch
        import executor.remaining as runner
        class Budget:
            def remaining(self, active=True): return 200
            def snapshot(self): return {'vm_charged_seconds': 1}
        class Broker:
            events = []
            dropped_event_count = 0
        class FakeSession:
            def __init__(self, **kw):
                self.root = Path(kw['workspace_parent'])
                self.executor_scratch = self.root/'fake-executor'
                self.reference_scratch = self.root/'fake-reference'
                self.budget, self.broker = Budget(), Broker()
                self.input_manifest = {'case':[]}
            def __enter__(self):
                self.executor_scratch.mkdir(); self.reference_scratch.mkdir()
                return self
            def __exit__(self, *args): pass
            def external_reservation(self, timeout, active=True):
                from contextlib import nullcontext
                return nullcontext()
            def execute(self, argv, *, timeout, env=None, network=True, reference=False):
                if argv[0] == '/usr/bin/mkdir':
                    (self.executor_scratch/argv[-1].removeprefix('/work/')).mkdir(parents=True, exist_ok=True)
                elif argv[0] == 'bash':
                    (self.executor_scratch/'output/native.stdout').write_text('native')
                    (self.executor_scratch/'output/native.stderr').write_text('')
                return {'returncode':0, 'timed_out':False, 'stdout':'native', 'stderr':''}
        class Adapter:
            def capture(self, case, session):
                (session.reference_scratch/'ref').write_text('secret')
                return {'status':'unclassified'}
        def agent(prompt, *, decide, broker, max_turns, command_timeout):
            self.assertNotIn('secret', prompt)
            argv = runner._native_argv('printf native')
            broker(argv, command_timeout)
            with self.assertRaises(RuntimeError):
                broker(argv, command_timeout)
            return {'status':'finished'}
        with tempfile.TemporaryDirectory(dir=BASE) as temp:
            root = Path(temp)
            runtime = root/'runtime'; (runtime/'attempts').mkdir(parents=True)
            guarded = root/'guard'; guarded.mkdir()
            (runtime/'runtime-host-manifest.jsonl').write_text('')
            spec = root/'spec.json'
            spec.write_text(json.dumps({'case_id':'PILOT-02','inputs':[], 'hosts':['example.test'],
                'native_shell_command':'printf native','reference_adapter_sha256':'placeholder',
                'installation_roots':[],'setup_shell_commands':[],'directories':[]}))
            attempt = runtime/'attempts'/'PILOT-02-synthetic'
            original_digest = runner.digest
            frozen = json.loads((runner.ROOT/'protocol/pilot/runtime/PILOT-01.json').read_text())
            expected = frozen['environment']['host_manifest']['sha256']
            def fake_digest(path):
                return expected if Path(path).name == 'runtime-host-manifest.jsonl' else original_digest(path)
            receipt = root/'receipt.json'; receipt.write_text('{}')
            binding = {'case_plan_sha256':{'PILOT-02':original_digest(spec)},
                       'case_packet_sha256':{'PILOT-02':original_digest(runner.ROOT/'protocol/pilot/execution/PILOT-02.json')}}
            with patch.dict(os.environ, {'PILOT_SESSION_ROOT':str(guarded)}), \
                 patch.object(runner, 'check_receipt', return_value=binding), patch.object(runner, 'check_host_tree'), \
                 patch.object(runner, '_check_supplemental_manifests'), \
                 patch.object(runner, 'digest', side_effect=fake_digest), \
                 patch.object(runner, '_adapter', return_value=Adapter()), \
                 patch.object(runner, '_predebit'), patch.object(runner, 'CaseSession', FakeSession), \
                 patch.object(runner, 'run_agent', side_effect=agent):
                result = runner.run_case(runtime, attempt, receipt, spec)
            self.assertEqual(result['status'], 'primary_finished_pending_assessment', result)
            self.assertTrue((attempt/'native-start.json').exists())
            self.assertEqual((attempt/'native-logs/output/native.stdout').read_text(), 'native')
            self.assertEqual((attempt/'reference/ref').read_text(), 'secret')
            self.assertNotIn('secret', (attempt/'model-packet.txt').read_text())
