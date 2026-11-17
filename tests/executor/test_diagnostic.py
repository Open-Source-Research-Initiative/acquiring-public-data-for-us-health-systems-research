import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from executor import diagnostic

BASE = '/workspace/repos/builderbob'


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=BASE)
        self.root = Path(self.tmp.name)
        self.runtime = self.root/'runtime'
        (self.runtime/'attempts'/'primary').mkdir(parents=True)
        (self.runtime/'diagnostics').mkdir()
        self.primary = self.runtime/'attempts'/'primary'
        self.original = {'case_id': 'PILOT-06', 'native_shell_command': 'original'}
        (self.primary/'spec.json').write_text(json.dumps(self.original))
        (self.primary/'status.json').write_text(json.dumps({'case_id': 'PILOT-06'}))
        (self.primary/'native-start.json').write_text('{}')
        self.attempt = self.runtime/'diagnostics'/'PILOT-06-diagnostic-20261117'
        self.spec = {**self.original, 'diagnostic_id': self.attempt.name,
                     'primary_attempt': str(self.primary), 'diagnostic_window': diagnostic.WINDOW,
                     'diagnostic_transport': {'publisher_cookie_policy': 'observed-same-https-host'},
                     'primary_manifest_sha256': hashlib.sha256(diagnostic.manifest_bytes(
                         diagnostic.preservation_manifest(self.primary))).hexdigest()}
        self.plan = self.root/'plan.json'
        self.receipt = self.root/'receipt.json'
        self.plan.write_text(json.dumps(self.spec))
        self.receipt.write_text('{}')

    def tearDown(self):
        self.tmp.cleanup()

    def run_it(self):
        return diagnostic.run_diagnostic(self.runtime, self.attempt, self.receipt, self.plan)

    def test_separate_invocation_and_preservation(self):
        def run(runtime, attempt, receipt, spec, *, phase):
            self.assertEqual(phase, 'diagnostic')
            attempt.mkdir()
            (attempt/'budget.sqlite').write_text('fresh')
            return {'status': 'synthetic'}
        with patch.object(diagnostic.remaining, 'check_receipt') as qualification, \
             patch.object(diagnostic.remaining, '_run_case', side_effect=run):
            self.assertEqual(self.run_it()['status'], 'synthetic')
            qualification.assert_called_once_with(self.receipt, 'diagnostic')
            self.assertEqual((self.attempt/'primary-preservation-before.json').read_bytes(),
                             (self.attempt/'primary-preservation-after.json').read_bytes())
            with self.assertRaises(FileExistsError):
                self.run_it()

    def test_crossover_and_changed_native_rejected(self):
        self.attempt = self.runtime/'attempts'/'PILOT-06-diagnostic-20261117'
        with self.assertRaises(ValueError): self.run_it()
        self.attempt = self.runtime/'diagnostics'/'PILOT-06-diagnostic-20261117'
        self.spec['native_shell_command'] = 'changed'
        self.plan.write_text(json.dumps(self.spec))
        with self.assertRaisesRegex(ValueError, 'complete primary'): self.run_it()

    def test_primary_mutation_detected_and_recorded(self):
        def run(runtime, attempt, receipt, spec, *, phase):
            attempt.mkdir()
            (self.primary/'status.json').write_text('changed')
            return {}
        with patch.object(diagnostic.remaining, 'check_receipt'), \
             patch.object(diagnostic.remaining, '_run_case', side_effect=run):
            with self.assertRaisesRegex(RuntimeError, 'primary evidence changed'): self.run_it()
        self.assertNotEqual((self.attempt/'primary-preservation-before.json').read_bytes(),
                            (self.attempt/'primary-preservation-after.json').read_bytes())

    def test_wrong_qualification_refused(self):
        with patch.object(diagnostic.remaining, 'check_receipt', side_effect=RuntimeError('not qualified')):
            with self.assertRaisesRegex(RuntimeError, 'not qualified'): self.run_it()
        self.assertFalse(self.attempt.exists())

    def test_changed_primary_refused(self):
        (self.primary/'status.json').write_text(json.dumps({'case_id': 'PILOT-06', 'changed': True}))
        with self.assertRaisesRegex(ValueError, 'manifest mismatch'): self.run_it()

    def test_public_phase_dispatch_validates_diagnostic(self):
        self.spec['native_shell_command'] = 'altered'
        self.plan.write_text(json.dumps(self.spec))
        with self.assertRaisesRegex(ValueError, 'complete primary'):
            diagnostic.remaining.run_case(self.runtime, self.attempt, self.receipt, self.plan, phase='diagnostic')
