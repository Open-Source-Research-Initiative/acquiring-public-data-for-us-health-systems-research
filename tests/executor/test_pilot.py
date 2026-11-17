"""Regression checks for the launch gate; no real pilot execution."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from executor import pilot

class PilotGateTests(unittest.TestCase):
    def test_unqualified_or_stale_runtime_never_launches(self):
        with tempfile.TemporaryDirectory(dir=pilot.ROOT) as temp:
            root=Path(temp); (root/'executor').mkdir()
            source=root/'executor/runtime.py'; source.write_text('version one')
            receipt=root/'qualification.json'
            data={'status':'not_qualified','allowed_phases':['primary'],'allowed_cases':['PILOT-01'],'allowed_schemes':['http','https'],'tests':{'failures':0,'skipped':0},
                  'open_blockers':[], 'file_sha256':{'executor/runtime.py':pilot.digest(source)}}
            with patch.object(pilot,'ROOT',root):
                receipt.write_text(json.dumps(data))
                with self.assertRaises(RuntimeError): pilot.check_receipt(receipt)
                data['status']='qualified_for_bounded_feasibility'
                receipt.write_text(json.dumps(data)); pilot.check_receipt(receipt)
                source.write_text('version two')
                with self.assertRaises(RuntimeError): pilot.check_receipt(receipt)

    def test_runtime_content_and_link_change_rejected(self):
        with tempfile.TemporaryDirectory(dir=pilot.ROOT) as temp:
            root=Path(temp); source=root/'binary'; source.write_text('original'); source.chmod(0o600)
            manifest=root/'manifest.jsonl'
            manifest.write_text(json.dumps({'path':str(source),'type':'file','mode':'0600','sha256':pilot.digest(source)})+'\n')
            pilot.check_host_tree(manifest)
            source.write_text('mutated')
            with self.assertRaises(RuntimeError): pilot.check_host_tree(manifest)
            source.unlink(); source.symlink_to(manifest)
            with self.assertRaises(RuntimeError): pilot.check_host_tree(manifest)

if __name__=='__main__': unittest.main()
