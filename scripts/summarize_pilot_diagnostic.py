#!/usr/bin/env python3
"""Summarize a separate diagnostic without changing primary evidence."""
import argparse
import json
from pathlib import Path

from summarize_pilot_attempt import summarize, sha256


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('attempt', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    spec = json.loads((args.attempt / 'spec.json').read_text())
    status = json.loads((args.attempt / 'status.json').read_text())
    if status.get('phase') != 'diagnostic':
        raise ValueError('separately recorded diagnostic required')
    result = summarize(args.attempt)
    result['phase'] = 'exploratory_diagnostic'
    result['diagnostic_id'] = spec['diagnostic_id']
    result['original_primary_manifest_sha256'] = spec['primary_manifest_sha256']
    result['original_primary_replaced'] = False
    result['diagnostic_output_locked_utc'] = result.pop('primary_locked_utc')
    result['mutable_ledger'] = 'Separate diagnostic ledger; original ledger remains unchanged. Resources are timestamped snapshots, not immutable SQLite identity claims.'
    before = args.attempt / 'primary-preservation-before.json'
    after = args.attempt / 'primary-preservation-after.json'
    result['primary_preservation'] = {'before_sha256': sha256(before),
                                      'after_sha256': sha256(after),
                                      'unchanged': before.read_bytes() == after.read_bytes()}
    with args.output.open('x') as output:
        json.dump(result, output, indent=2)
        output.write('\n')
    print(json.dumps({'case': result['case_id'], 'native_invocations': result['native_invocations']}))


if __name__ == '__main__':
    main()
