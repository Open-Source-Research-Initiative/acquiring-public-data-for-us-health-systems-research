"""Launch one separately qualified diagnostic through the coordinator guard."""
import argparse
import json
from pathlib import Path
import sys

REPO = Path('/workspace/repos/builderbob/open-source-research-initiative/repos/acquiring-public-data-for-us-health-systems-research')
RUNTIME = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
from executor.coordinator_guard import run_guarded


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('case', choices=('06', '07'))
    parser.add_argument('--spec', type=Path, required=True)
    args = parser.parse_args()
    case = 'PILOT-' + args.case
    diagnostics = RUNTIME / 'diagnostics'
    if diagnostics.is_symlink() or not diagnostics.is_dir():
        raise SystemExit('diagnostics directory must already exist and not be a symlink')
    attempt = diagnostics / (case + '-diagnostic-20261117')
    if attempt.exists() or attempt.is_symlink():
        raise SystemExit('diagnostic attempt already exists')
    receipt = REPO / 'evidence/executor/qualification-diagnostics-v1.json'
    spec = args.spec.resolve(strict=True)
    argv = ['/usr/bin/python3', '-m', 'executor.diagnostic', '--runtime', str(RUNTIME),
            '--attempt', str(attempt), '--qualification', str(receipt), '--spec', str(spec)]
    guard = diagnostics / (case + '-diagnostic-guard.json')
    # Reserve the guard record before launch; existing records are never overwritten.
    with guard.open('x') as output:
        output.write(json.dumps({'case': case, 'status': 'launching'}) + '\n')
    result = run_guarded(argv, workspace_parent='/workspace/repos/builderbob/.osri-pilot', timeout=21600)
    # The reserved record remains as evidence if the guard itself raises.
    with guard.open('w') as output:
        json.dump(result, output, indent=2)
        output.write('\n')
    print(json.dumps({'case': case, 'guard': str(guard), 'result': result}, indent=2))


if __name__ == '__main__':
    main()
