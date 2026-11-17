#!/usr/bin/env python3
"""Publish provenance metadata, never the retained publisher payloads."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def summarize(attempt):
    status = json.loads((attempt / 'status.json').read_text())
    lock = json.loads((attempt / 'lock.json').read_text())
    commands_path = attempt / 'command-log.json'
    commands = json.loads(commands_path.read_text()) if commands_path.exists() else []
    records = []
    for path in sorted(attempt.rglob('*')):
        if path.is_symlink():
            raise ValueError('linked evidence path')
        if path.is_file() and not path.name.startswith('budget.sqlite'):
            records.append({'path': path.relative_to(attempt).as_posix(),
                            'bytes': path.stat().st_size, 'sha256': sha256(path)})
    return {
        'case_id': status['case_id'],
        'recorded_utc': datetime.now(timezone.utc).isoformat(),
        'phase': 'exploratory_feasibility',
        'coordinator_status': status['status'],
        'native_invocations': len(commands),
        'native_results': [{k: entry.get('result', {}).get(k)
                           for k in ('returncode', 'timed_out', 'output_limit_exceeded', 'elapsed_seconds')}
                          for entry in commands],
        'primary_locked_utc': status.get('primary_locked_utc'),
        'setup_histories': len(list(attempt.glob('setup-history-*'))),
        'runtime_postcheck': status.get('runtime_postcheck'),
        'resources': status.get('resources_post_cleanup', status.get('resources')),
        'lock': lock,
        'reference_observations': {
            phase: json.loads((attempt / f'reference-{phase}.json').read_text()).get('status')
            for phase in ('before', 'after') if (attempt / f'reference-{phase}.json').exists()},
        'retained_artifacts': records,
        'mutable_ledger': 'budget.sqlite remains cumulative; use the separately timestamped remaining-accounting.json reconciliation, not an immutable-file claim.',
        'limitations': [
            'Metadata inventory of locally retained evidence; raw payloads and private assessments are not published here.',
            'Process exit, coordinator status and hashes do not establish acquisition, completeness, fidelity or research fitness.',
            'Resource ledger preserves conservative charges; application-byte accounting excludes unknown historical preparation traffic.',
            'Independent human scientific review is pending.'
        ]
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('attempt', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    result = summarize(args.attempt)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'case': result['case_id'], 'native_invocations': result['native_invocations'],
                      'artifact_count': len(result['retained_artifacts'])}))
