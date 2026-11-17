"""Create a fresh, separately scoped diagnostic qualification after code freeze.

Run from the project root. Outputs are exclusive: an existing receipt, log, or
snapshot is never replaced. No candidate task is executed by this script.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
from datetime import datetime, timezone

REPO = Path('/workspace/repos/builderbob/open-source-research-initiative/repos/acquiring-public-data-for-us-health-systems-research')
RUNTIME = Path(__file__).resolve().parent
CASES = ('PILOT-06', 'PILOT-07')


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--spec-dir', type=Path, required=True)
    parser.add_argument('--amendment', type=Path, required=True)
    args = parser.parse_args()
    amendment = args.amendment.resolve(strict=True)
    if not amendment.is_relative_to(REPO / 'protocol/pilot') or not amendment.is_file():
        raise SystemExit('amendment must be a project pilot protocol file')
    specs = {case: (args.spec_dir / (case + '.json')).resolve(strict=True) for case in CASES}
    packets = {case: REPO / 'protocol/pilot/execution' / (case + '.json') for case in CASES}
    executor = sorted((REPO / 'executor').glob('*.py'))
    tests = sorted((REPO / 'tests/executor').glob('*.py'))
    files = executor + tests + [amendment]
    if not executor or not tests:
        raise SystemExit('missing executor or test files')
    for case, path in specs.items():
        plan = json.loads(path.read_bytes())
        if plan.get('case_id') != case:
            raise SystemExit('plan case mismatch: ' + case)
        for item in plan['inputs']:
            if sha(item['source']) != item['sha256']:
                raise SystemExit('input drift: ' + case)
        if sha(plan['reference_adapter']) != plan['reference_adapter_sha256']:
            raise SystemExit('adapter drift: ' + case)
        for value in plan.get('guest_aliases', {}).values():
            if value.startswith('/') or '..' in Path(value).parts:
                raise SystemExit('invalid guest alias: ' + case)
    manifest = RUNTIME / 'runtime-zoneinfo-manifest.jsonl'
    tracked = files + list(specs.values()) + list(packets.values()) + [manifest]
    before = {str(p): sha(p) for p in tracked}
    receipt = REPO / 'evidence/executor/qualification-diagnostics-v1.json'
    snapshots = REPO / 'evidence/executor/snapshots'
    code_archive = snapshots / 'diagnostics-v1-executor.tar.gz'
    evidence_archive = snapshots / 'diagnostics-v1-tests-amendment.tar.gz'
    log = RUNTIME / 'diagnostics-v1-tests.log'
    for path in (receipt, code_archive, evidence_archive, log):
        if path.exists() or path.is_symlink():
            raise SystemExit('output already exists: ' + str(path))
    env = os.environ.copy()
    env['PILOT_FUSE_RUNTIME'] = str(RUNTIME / 'fuse-runtime' / 'extracted')
    with log.open('x') as output:
        result = subprocess.run(['/usr/bin/python3', '-m', 'unittest', 'discover', '-s', 'tests/executor', '-v'], cwd=REPO, env=env, stdout=output, stderr=subprocess.STDOUT, check=False)
    text = log.read_text()
    match = re.search(r'Ran (\d+) tests', text)
    if result.returncode or not match or not re.search(r'\nOK\s*$', text) or 'skipped=' in text:
        raise SystemExit('full passing unskipped suite required; failed log retained')
    if (executor != sorted((REPO / 'executor').glob('*.py'))
            or tests != sorted((REPO / 'tests/executor').glob('*.py'))
            or before != {str(p): sha(p) for p in tracked}):
        raise SystemExit('qualification inputs changed during tests; log retained')
    for archive, members in ((code_archive, executor), (evidence_archive, tests + [amendment])):
        with archive.open('xb') as stream:
            with tarfile.open(fileobj=stream, mode='w:gz') as tar:
                for path in members:
                    tar.add(path, arcname=str(path.relative_to(REPO)), recursive=False)
        archive.chmod(0o444)
    if (executor != sorted((REPO / 'executor').glob('*.py'))
            or tests != sorted((REPO / 'tests/executor').glob('*.py'))
            or before != {str(p): sha(p) for p in tracked}):
        raise SystemExit('qualification inputs changed during archival; artifacts retained')
    record = {
        'status': 'qualified_for_bounded_feasibility', 'version': 'diagnostics-v1',
        'created_utc': datetime.now(timezone.utc).isoformat(), 'performer': 'Codex coordinator',
        'allowed_cases': list(CASES), 'allowed_phases': ['diagnostic'], 'allowed_schemes': ['http', 'https'],
        'tests': {'count': int(match.group(1)), 'failures': 0, 'skipped': 0,
                  'command': 'PILOT_FUSE_RUNTIME=<workspace extracted runtime> /usr/bin/python3 -m unittest discover -s tests/executor -v',
                  'log_path': str(log), 'log_sha256': sha(log)},
        'open_blockers': [], 'file_sha256': {str(p.relative_to(REPO)): before[str(p)] for p in files},
        'case_plan_sha256': {case: before[str(path)] for case, path in specs.items()},
        'case_packet_sha256': {case: before[str(path)] for case, path in packets.items()},
        'supplemental_host_manifests': [{'path': str(manifest), 'sha256': before[str(manifest)]}],
        'runtime_snapshot': {'path': str(code_archive.relative_to(REPO)), 'sha256': sha(code_archive)},
        'tests_amendment_snapshot': {'path': str(evidence_archive.relative_to(REPO)), 'sha256': sha(evidence_archive)},
        'limitations': ['Scoped synthetic tests do not establish general sandbox security or human review.',
                        'Diagnostic execution and its outcomes require separate evidence.',
                        'Trusted host mutation and kernel flaws are outside the demonstrated boundary.']}
    with receipt.open('x') as output:
        json.dump(record, output, indent=2)
        output.write('\n')
    receipt.chmod(0o444)
    log.chmod(0o444)
    print(json.dumps({'receipt': str(receipt), 'tests': record['tests']['count']}))


if __name__ == '__main__':
    main()
