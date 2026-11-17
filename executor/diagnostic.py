"""Separately qualified, evidence-preserving diagnostic repeats for cases 06 and 07."""
import argparse
import hashlib
import json
from pathlib import Path
import stat

from executor import remaining

CASES = ('PILOT-06', 'PILOT-07')
WINDOW = {'active_seconds': 10800, 'runtime_seconds': 14400, 'elapsed_seconds': 21600}


def preservation_manifest(root):
    """Inventory all primary evidence without following links or accepting special files."""
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('primary attempt must be an unlinked directory')
    records = []
    for path in sorted(root.rglob('*')):
        info = path.lstat()
        rel = path.relative_to(root).as_posix()
        if stat.S_ISDIR(info.st_mode):
            records.append({'path': rel, 'type': 'directory'})
        elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
            records.append({'path': rel, 'type': 'file', 'bytes': info.st_size,
                            'sha256': remaining.digest(path)})
        else:
            raise ValueError('linked or special primary evidence: ' + rel)
    return records


def manifest_bytes(records):
    return (json.dumps(records, sort_keys=True, separators=(',', ':')) + '\n').encode()


def run_diagnostic(runtime, attempt, receipt, spec_path):
    runtime, attempt, receipt, spec_path = map(Path, (runtime, attempt, receipt, spec_path))
    runtime = runtime.resolve(strict=True)
    spec = json.loads(spec_path.read_bytes())
    case = spec.get('case_id')
    if case not in CASES:
        raise ValueError('diagnostic case outside authorization')
    expected_id = case + '-diagnostic-20261117'
    if spec.get('diagnostic_id') != expected_id or attempt.name != expected_id:
        raise ValueError('diagnostic identifier mismatch')
    diagnostics = runtime/'diagnostics'
    if diagnostics.is_symlink() or not diagnostics.is_dir() or attempt.parent.resolve(strict=True) != diagnostics.resolve(strict=True):
        raise ValueError('diagnostic attempt must be directly under runtime/diagnostics')
    if attempt.exists() or attempt.is_symlink():
        raise FileExistsError('diagnostic attempt already exists')
    if spec.get('diagnostic_transport') != {'publisher_cookie_policy': 'observed-same-https-host'}:
        raise ValueError('diagnostic transport policy mismatch')
    if spec.get('diagnostic_window') != WINDOW:
        raise ValueError('diagnostic window must declare the authorized limits')
    primary = Path(spec['primary_attempt'])
    if primary.is_symlink() or primary.parent.resolve(strict=True) != (runtime/'attempts').resolve(strict=True):
        raise ValueError('primary attempt must be directly under runtime/attempts')
    primary = primary.resolve(strict=True)
    status = json.loads((primary/'status.json').read_text())
    if status.get('case_id') != case or not (primary/'native-start.json').is_file():
        raise ValueError('matching primary native invocation required')
    original = json.loads((primary/'spec.json').read_text())
    extras = {'diagnostic_id', 'primary_attempt', 'primary_manifest_sha256', 'diagnostic_window', 'diagnostic_transport'}
    if {k: v for k, v in spec.items() if k not in extras} != original:
        raise ValueError('diagnostic must retain the complete primary task and inputs')
    before = preservation_manifest(primary)
    if hashlib.sha256(manifest_bytes(before)).hexdigest() != spec.get('primary_manifest_sha256'):
        raise ValueError('primary preservation manifest mismatch')
    remaining.check_receipt(receipt, 'diagnostic')
    try:
        return remaining._run_case(runtime, attempt, receipt, spec_path, phase='diagnostic')
    finally:
        if attempt.is_dir() and not attempt.is_symlink():
            (attempt/'primary-preservation-before.json').write_bytes(manifest_bytes(before))
            after = preservation_manifest(primary)
            (attempt/'primary-preservation-after.json').write_bytes(manifest_bytes(after))
            if before != after:
                raise RuntimeError('primary evidence changed during diagnostic')


def main():
    parser = argparse.ArgumentParser()
    for name in ('runtime', 'attempt', 'qualification', 'spec'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    result = run_diagnostic(args.runtime, args.attempt, args.qualification, args.spec)
    print(json.dumps({'case_id': result['case_id'], 'status': result['status'], 'attempt': str(args.attempt)}))


if __name__ == '__main__':
    main()
