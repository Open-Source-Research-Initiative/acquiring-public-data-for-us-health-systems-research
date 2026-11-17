"""Case-01 pilot coordinator. Requires a current qualified receipt and outer guard.

This coordinator never gives the model reference inputs or assessment results.
Other selected cases remain prepared, not silently substituted or executed.
"""
import argparse
import hashlib
import importlib.util
import json
import os
import shutil
from pathlib import Path
import stat
import tarfile
from datetime import datetime, timezone

from executor.model_runtime import cli_decide, run_agent, PINNED_MODEL
from executor.session import CaseSession
from executor.supervisor import lock_outputs

ROOT = Path(__file__).resolve().parents[1]

def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def utc():
    return datetime.now(timezone.utc).isoformat()

def save(path, value):
    encoded = (json.dumps(value, indent=2, ensure_ascii=False) + '\n').encode()
    if len(encoded) > 32*1024**2:
        raise RuntimeError('control record exceeds 32 MiB')
    Path(path).write_bytes(encoded)

def check_receipt(path, phase="primary"):
    receipt = json.loads(Path(path).read_text())
    if receipt.get('status') != 'qualified_for_bounded_feasibility':
        raise RuntimeError('executor qualification has not passed')
    if phase not in receipt.get('allowed_phases', []):
        raise RuntimeError('phase not qualified')
    if receipt.get('allowed_cases') != ['PILOT-01'] or receipt.get('allowed_schemes') != ['http', 'https']:
        raise RuntimeError('case or transport scope not qualified')
    if receipt.get('open_blockers') or receipt.get('tests', {}).get('failures') != 0 or receipt.get('tests', {}).get('skipped') != 0:
        raise RuntimeError('qualification has open blockers or incomplete checks')
    files = receipt.get('file_sha256', {})
    required = {str(p.relative_to(ROOT)) for p in (ROOT/'executor').glob('*.py')}
    if not required.issubset(files):
        raise RuntimeError('qualification does not cover current runtime')
    for relative, expected in files.items():
        p = ROOT/relative
        if p.resolve().is_relative_to(ROOT) is False or digest(p) != expected:
            raise RuntimeError('qualification is stale: ' + relative)
    return receipt

def list_outputs(root):
    paths=[]
    for p in root.rglob('*'):
        if p.is_symlink():
            raise RuntimeError('linked output is not capturable')
        if p.is_file():
            relative=p.relative_to(root).as_posix()
            if len(paths)>=10000 or len(relative.encode())>1024:
                raise RuntimeError('output inventory exceeds fixed bound')
            paths.append(relative)
    return sorted(paths)

def check_host_tree(path):
    total=0
    for line in Path(path).read_text().splitlines():
        entry = json.loads(line)
        p = Path(entry['path'])
        st = p.lstat()
        if f'{stat.S_IMODE(st.st_mode):04o}' != entry['mode']:
            raise RuntimeError('host runtime mode changed: ' + str(p))
        if entry['type'] == 'symlink':
            if not p.is_symlink() or os.readlink(p) != entry['target']:
                raise RuntimeError('host runtime symlink changed')
        elif entry['type'] == 'file':
            total += st.st_size
            if total > 3*1024**3:
                raise RuntimeError('frozen runtime exceeds disk allocation')
            if not stat.S_ISREG(st.st_mode) or digest(p) != entry['sha256']:
                raise RuntimeError('host runtime content changed: ' + str(p))
        elif entry['type'] == 'directory':
            if not stat.S_ISDIR(st.st_mode):
                raise RuntimeError('host runtime directory changed')
        else:
            raise RuntimeError('unsupported runtime entry')

def prepare_source(runtime, preparation):
    """Copy exactly two inspected regular source members; never execute archive code."""
    preparation.mkdir(exist_ok=True)
    with tarfile.open(runtime/'sources/PILOT-01.tar.gz') as archive:
        members = {m.name: m for m in archive.getmembers()}
        for name in ('README.md', 'download_source.sh'):
            matches = [m for k, m in members.items() if k.count('/') == 1 and k.endswith('/'+name)]
            if len(matches) != 1 or not matches[0].isfile() or matches[0].size > 1024**2:
                raise RuntimeError('unexpected selected source member')
            expected = archive.extractfile(matches[0]).read()
            target = preparation/name
            if target.exists():
                if target.is_symlink() or target.read_bytes() != expected:
                    raise RuntimeError('prepared source changed')
            else:
                target.write_bytes(expected)
    return preparation

def run_case(runtime, attempt, receipt_path, resume_setup=False):
    receipt = check_receipt(receipt_path)
    guarded = Path(os.environ['PILOT_SESSION_ROOT']).resolve(strict=True)
    if not guarded.is_relative_to('/workspace'):
        raise RuntimeError('guarded workspace required')
    if not attempt.is_relative_to(runtime/'attempts'):
        raise RuntimeError('attempt must be under runtime/attempts')
    if attempt.exists():
        old = json.loads((attempt/'status.json').read_text())
        if not resume_setup or old.get('status') != 'coordinator_error' or (attempt/'command-log.json').exists() or (attempt/'input-manifest.json').exists():
            raise RuntimeError('attempt already exists; no automatic retry')
        for name in ('lock.json','status.json','model-packet.txt'):
            destination=attempt/('setup-01-'+name)
            if destination.exists():
                raise RuntimeError('setup continuation already used')
            shutil.copyfile(attempt/name,destination)
    else:
        if resume_setup:
            raise RuntimeError('no setup failure to resume')
        attempt.mkdir(mode=0o700)
    runtime_spec = json.loads((ROOT/'protocol/pilot/runtime/PILOT-01.json').read_text())
    archive = runtime/'sources/PILOT-01.tar.gz'
    if digest(archive) != runtime_spec['source']['sha256']:
        raise RuntimeError('source archive changed')
    host_manifest = runtime/'runtime-host-manifest.jsonl'
    if digest(host_manifest) != runtime_spec['environment']['host_manifest']['sha256']:
        raise RuntimeError('host runtime manifest changed')
    check_host_tree(host_manifest)
    source = prepare_source(runtime, attempt/'source')
    packet_path = ROOT/'protocol/pilot/execution/PILOT-01.json'
    packet = json.loads(packet_path.read_text())
    unzip = runtime/'tools/root/usr/bin/unzip'
    if digest(unzip) != runtime_spec['binaries']['unzip']['sha256']:
        raise RuntimeError('unzip changed')
    single_unzip=source/'unzip'
    if single_unzip.exists():
        raise RuntimeError('runtime staging collision')
    shutil.copyfile(unzip,single_unzip)
    single_unzip.chmod(0o755)
    if digest(single_unzip) != digest(unzip) or single_unzip.stat().st_nlink != 1:
        raise RuntimeError('runtime binary snapshot failed')
    unzip=single_unzip
    prompt = json.dumps(packet) + '''\nFrozen runtime supplement: model gpt-6.1-terra;
read-only native script /inputs/download_source.sh and README /inputs/README.md;
source archive already verified, no checkout or installation needed. PATH includes
/tools/unzip. Empty /work is the working directory; native defaults and script bytes
are unchanged. Execute the selected script exactly once, using bash with shell -c
to change directory to /work and capture stdout to /work/native.stdout and stderr
to /work/native.stderr. Report its exit status and at most 3000 characters from the
end of each log. No patches, alternate sources, retries, diagnostic acquisition,
or additional requests. Do not invoke native model tools; return the structured
run action, then finish using the broker result. Reference/checker feedback is
unavailable. A process exit does not establish acquisition or completeness.'''
    lock = {'case_id': 'PILOT-01', 'locked_utc': utc(), 'model': PINNED_MODEL,
            'packet_sha256': digest(packet_path), 'prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest(),
            'runtime_spec_sha256': digest(ROOT/'protocol/pilot/runtime/PILOT-01.json'),
            'qualification_sha256': digest(receipt_path), 'host_manifest_sha256': digest(host_manifest),
            'source_files': {p.name: digest(p) for p in source.iterdir()},
            'private_reference_adapter_sha256': digest(runtime/'assessment-private/capture_plan.py'),
            'source_commit': packet['source_commit'], 'max_model_turns': 4,
            'command_timeout_seconds': 1800, 'request_timeout_seconds': 1800,
            'reference_status_at_lock': 'absent; independent capture plan prepared; no verified acquisition can yet be claimed',
            'observation_window': 'single six-hour case ledger session',
            'reference_feedback': 'never supplied to model', 'retry': 'none planned', 'setup_continuation': resume_setup,
            'setup_note': 'Original pre-command hardlink rejection retained with its full ledger reservation; byte-identical runtime copy, no candidate change or additional primary invocation.' if resume_setup else None}
    save(attempt/'lock.json', lock)
    (attempt/'model-packet.txt').write_text(prompt)
    result = {'case_id': 'PILOT-01', 'status': 'started', 'started_utc': utc()}
    save(attempt/'status.json', result)
    mounts = {str(source/'README.md'): '/inputs/README.md',
              str(source/'download_source.sh'): '/inputs/download_source.sh',
              str(unzip): '/tools/unzip'}
    try:
        with CaseSession(workspace_parent=guarded, state_parent=guarded,
                         ledger_path=attempt/'budget.sqlite',
                         fuse2fs=runtime/'fuse-runtime/extracted/usr/bin/fuse2fs',
                         library_dir=runtime/'fuse-runtime/extracted/lib/x86_64-linux-gnu',
                         allowed_hosts=['downloads.cms.gov'], allowed_schemes=('http','https'), case_inputs=mounts,
                         broker_timeout=1800, disk_bytes=48*1024**3) as session:
            save(attempt/'input-manifest.json', session.input_manifest['case'])
            # Each decision uses a fresh authenticated model with native routes disabled.
            def decide(text):
                maximum = min(125, session.budget.remaining(active=True))
                if maximum <= 5:
                    raise RuntimeError("model time exhausted")
                with session.external_reservation(maximum, active=True):
                    return cli_decide(text, scratch=guarded, timeout=maximum-5)
            calls = []
            def broker(argv, timeout):
                if calls:
                    raise RuntimeError('one primary invocation allowed; no silent retry')
                value = session.execute(argv, timeout=min(timeout, session.budget.remaining(active=True)-5),
                                        env={'PATH':'/tools:/usr/bin:/bin'})
                calls.append({'argv': argv, 'result': value})
                save(attempt/'command-log.json', calls)
                return value
            try:
                result['agent'] = run_agent(prompt, decide=decide, broker=broker,
                                            max_turns=4, command_timeout=1800)
                result['status'] = 'primary_finished_pending_assessment'
            except Exception as error:
                result['status'] = 'executor_or_recording_error'
                result['error'] = type(error).__name__ + ': ' + str(error)
            # No executor process survives each command's supervisor return.
            paths = list_outputs(session.executor_scratch)
            result['outputs'] = lock_outputs(session.executor_scratch, attempt/'outputs', paths, max_bytes=48*1024**3, max_path_bytes=1024)
            result['primary_locked_utc'] = utc()
            save(attempt/'primary.json', result)
            # Assessor code receives no candidate outputs and the model never resumes.
            module_path = runtime/'assessment-private/capture_plan.py'
            if digest(module_path) != lock['private_reference_adapter_sha256']:
                raise RuntimeError('reference plan changed after lock')
            spec = importlib.util.spec_from_file_location('private_capture', module_path)
            assessor = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(assessor)
            def reference_run(argv, **options):
                return session.execute(argv, timeout=min(options['timeout'], session.budget.remaining(active=False)-5),
                                       reference=True, env=options.get('env'))
            try:
                observations = assessor.capture('PILOT-01', run=reference_run,
                    budget=session.budget, broker=session.broker, scratch=session.reference_scratch,
                    proxy_socket=session.broker.socket_path,
                    ca_bundle_mount=(str(session.public_bundle), '/trust/ca.pem'),
                    timeout_per_request=1800, qualification_attested=True, terms_attested=True)
                save(attempt/'reference-observations.json', observations)
                reference_paths = list_outputs(session.reference_scratch)
                remaining_bytes = 48*1024**3-sum(item['bytes'] for item in result['outputs'])
                result['reference_files'] = lock_outputs(session.reference_scratch, attempt/'reference', reference_paths, max_bytes=remaining_bytes, max_files=10000-len(result['outputs']), max_path_bytes=1024)
                result['reference_status'] = 'captured_observations_pending_source_assessment'
            except Exception as error:
                result['reference_status'] = 'capture_or_recording_error'
                result['reference_error'] = type(error).__name__ + ': ' + str(error)
            result['broker_events'] = session.broker.events
            result['resources'] = session.budget.snapshot()
        result['finished_utc'] = utc()
    except Exception as error:
        result.update(status='coordinator_error', error=type(error).__name__ + ': ' + str(error), finished_utc=utc())
    try:
        check_host_tree(host_manifest)
        result['runtime_postcheck'] = 'matched_frozen_manifest'
    except Exception as error:
        result['runtime_postcheck'] = 'unresolved_or_changed: ' + str(error)
    save(attempt/'status.json', result)
    print(json.dumps({'case_id':'PILOT-01','status':result['status'],'receipt':str(attempt/'status.json')}))
    return result

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--attempt', type=Path, required=True)
    parser.add_argument('--qualification', type=Path, required=True)
    parser.add_argument('--resume-setup', action='store_true')
    args=parser.parse_args()
    run_case(args.runtime.resolve(strict=True), args.attempt.resolve(), args.qualification.resolve(strict=True), args.resume_setup)

if __name__ == '__main__': main()
