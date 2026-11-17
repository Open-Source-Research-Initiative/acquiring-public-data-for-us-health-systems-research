"""Guarded coordinator for exploratory PILOT-02 through PILOT-08."""
import argparse
from contextlib import contextmanager
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import time

from executor.model_runtime import PINNED_MODEL, cli_decide, run_agent
from executor.pilot import ROOT, check_host_tree, digest, save, utc
from executor.session import CaseSession
from executor.supervisor import CaseBudget, lock_outputs

CASES = [f'PILOT-{n:02}' for n in range(2, 9)]
OUTPUT_LIMIT = 46 * 1024**3
CONTROL_LIMIT = 32 * 1024**2
OUTPUT_DIRS = {'outputs', 'native-logs', 'reference', 'setup-outputs'}


def _usage(attempt):
    control = output = 0
    for folder, dirs, files in os.walk(attempt, followlinks=False):
        for name in dirs + files:
            path = Path(folder)/name
            st = path.lstat()
            if stat.S_ISLNK(st.st_mode):
                raise ValueError('linked retained artifact')
            if stat.S_ISREG(st.st_mode):
                if any(part in OUTPUT_DIRS for part in path.relative_to(attempt).parts[:-1]):
                    output += st.st_size
                else:
                    control += st.st_size
            elif not stat.S_ISDIR(st.st_mode):
                raise ValueError('special retained artifact')
    return control, output


def _control_write(attempt, path, payload, *, exclusive=False):
    path = Path(path)
    control, _ = _usage(attempt)
    prior = path.stat().st_size if path.exists() else 0
    # Reserve space for SQLite and final status writes.
    if control - prior + len(payload) > CONTROL_LIMIT - 1024**2:
        raise RuntimeError('aggregate control-record allocation exhausted')
    with path.open('xb' if exclusive else 'wb') as stream:
        stream.write(payload)
        stream.flush()
        if exclusive:
            os.fsync(stream.fileno())


def _save(attempt, path, value):
    payload = (json.dumps(value, indent=2, ensure_ascii=False) + '\n').encode()
    _control_write(attempt, path, payload)


def _output_remaining(attempt):
    _, output = _usage(attempt)
    if output >= OUTPUT_LIMIT:
        raise RuntimeError('aggregate retained-output allocation exhausted')
    return OUTPUT_LIMIT - output


def check_receipt(path, phase='primary'):
    receipt = json.loads(Path(path).read_text())
    if (receipt.get('status') != 'qualified_for_bounded_feasibility'
            or receipt.get('allowed_cases') != (CASES if phase == 'primary' else ['PILOT-06', 'PILOT-07'])
            or phase not in receipt.get('allowed_phases', [])
            or (phase == 'diagnostic' and receipt.get('allowed_phases') != ['diagnostic'])
            or phase not in ('primary', 'diagnostic')
            or receipt.get('open_blockers')
            or receipt.get('tests', {}).get('failures') != 0
            or receipt.get('tests', {}).get('skipped') != 0):
        raise RuntimeError('remaining-cases qualification incomplete or out of scope')
    files = receipt.get('file_sha256', {})
    required = {str(p.relative_to(ROOT)) for p in (ROOT/'executor').glob('*.py')}
    if not required.issubset(files):
        raise RuntimeError('qualification does not cover all executor code')
    for name, expected in files.items():
        path = ROOT/name
        if not path.resolve(strict=True).is_relative_to(ROOT) or digest(path) != expected:
            raise RuntimeError('qualification is stale: ' + name)
    return receipt


def _check_supplemental_manifests(receipt):
    manifests = receipt.get('supplemental_host_manifests', [])
    if not isinstance(manifests, list) or not manifests:
        raise ValueError('supplemental host manifests required')
    for item in manifests:
        path = Path(item['path'])
        if path.is_symlink():
            raise ValueError('linked supplemental manifest')
        path = path.resolve(strict=True)
        if not path.is_relative_to('/workspace') or not path.is_file():
            raise ValueError('supplemental manifest must be a workspace file')
        if digest(path) != item['sha256']:
            raise RuntimeError('supplemental manifest changed')
        check_host_tree(path)


def _relative(value):
    p = PurePosixPath(value)
    if p.is_absolute() or not p.parts or '..' in p.parts:
        raise ValueError('path must be relative to scratch')
    return p


def _inputs(spec):
    result, seen, total = {}, set(), 0
    for item in spec['inputs']:
        source = Path(item['source'])
        if source.is_symlink():
            raise ValueError('linked input root')
        source = source.resolve(strict=True)
        st = source.lstat()
        if not source.is_relative_to('/workspace') or not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
            raise ValueError('input must be a single-link workspace file')
        if digest(source) != item['sha256']:
            raise ValueError('input hash mismatch')
        if item['target'] in seen or str(source) in result:
            raise ValueError('duplicate input target or source')
        seen.add(item['target'])
        result[str(source)] = item['target']
        total += st.st_size
    if total > OUTPUT_LIMIT:
        raise ValueError('input snapshots exceed case disk ceiling')
    return result, total


def _predebit(ledger, count):
    budget = CaseBudget(ledger)
    token = None
    started = time.monotonic()
    try:
        token = budget.reserve(30, active=False)
        if not budget.consume_network(count):
            raise RuntimeError('retained inputs exceed case transfer budget')
        budget.finish(token, time.monotonic() - started)
    except BaseException:
        if token:
            budget.abandon(token)
        raise
    finally:
        budget.close()


@contextmanager
def _ledger_meter(path):
    budget = CaseBudget(path)
    token = None
    started = time.monotonic()
    try:
        maximum = min(1800, budget.remaining(active=False)-5)
        if maximum <= 0:
            raise RuntimeError('case time exhausted during coordinator work')
        token = budget.reserve(maximum, active=False)
        yield
        budget.finish(token, time.monotonic() - started)
    except BaseException:
        if token:
            budget.abandon(token)
        raise
    finally:
        budget.close()


def _shell(command):
    if not isinstance(command, str) or not command.strip() or '\0' in command:
        raise ValueError('invalid shell command')
    return ['bash', '-c', command]


def _native_argv(command):
    _shell(command)
    wrapped = ('cd /work && { ( ' + command + ' ) > /work/output/native.stdout 2> /work/output/native.stderr; '
               'rc=$?; tail -c 3000 /work/output/native.stdout; tail -c 3000 /work/output/native.stderr >&2; exit "$rc"; }')
    return ['bash', '-c', wrapped]


def _ok(result):
    return result.get('returncode') == 0 and not result.get('timed_out') and not result.get('output_limit_exceeded')


def _checked_path(scratch, name):
    if name == '.':
        return Path(scratch)
    path = Path(scratch)
    for part in _relative(name).parts:
        path = path / part
        if path.is_symlink():
            raise ValueError('linked path component')
    return path


def _manifest_roots(scratch, roots):
    records = []
    for root_name in roots:
        root = _checked_path(scratch, root_name)
        if not root.exists() or root.is_symlink() or not root.is_dir():
            raise ValueError('installed root absent or linked: ' + root_name)
        for folder, dirs, files in os.walk(root, followlinks=False):
            for name in sorted(dirs + files):
                path = Path(folder)/name
                rel = path.relative_to(scratch).as_posix()
                st = path.lstat()
                if stat.S_ISLNK(st.st_mode):
                    records.append({'path': rel, 'type': 'symlink', 'target': os.readlink(path)})
                    if name in dirs:
                        dirs.remove(name)
                elif stat.S_ISREG(st.st_mode) and st.st_nlink == 1:
                    records.append({'path':rel, 'type':'file', 'bytes':st.st_size, 'sha256':digest(path)})
                elif stat.S_ISDIR(st.st_mode):
                    continue
                else:
                    raise ValueError('unsupported installed file: ' + rel)
                if len(records) > 250000:
                    raise ValueError('installation manifest limit exceeded')
    return records


def _output_paths(scratch, roots):
    paths = set()
    for name in roots:
        p = _checked_path(scratch, name)
        if not p.exists() and not p.is_symlink():
            continue
        if p.is_symlink():
            raise ValueError('linked output root')
        root_type = p.lstat().st_mode
        if not (stat.S_ISREG(root_type) or stat.S_ISDIR(root_type)):
            raise ValueError('unsupported output root')
        candidates = [p] if stat.S_ISREG(root_type) else p.rglob('*')
        for item in candidates:
            mode = item.lstat().st_mode
            if stat.S_ISREG(mode):
                paths.add(item.relative_to(scratch).as_posix())
            elif not stat.S_ISDIR(mode):
                raise ValueError('linked or special output is not capturable')
    if len(paths) > 10000:
        raise ValueError('output file count exceeded')
    return sorted(paths)


def _adapter(spec):
    path = Path(spec['reference_adapter'])
    if path.is_symlink():
        raise ValueError('linked reference adapter')
    path = path.resolve(strict=True)
    if not path.is_relative_to('/workspace') or digest(path) != spec['reference_adapter_sha256']:
        raise ValueError('reference adapter mismatch')
    module_spec = importlib.util.spec_from_file_location('private_reference_adapter', path)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    if digest(path) != spec['reference_adapter_sha256']:
        raise RuntimeError('reference adapter changed during load')
    return module


def _prepare_attempt(attempt, resume):
    if not attempt.exists():
        if resume:
            raise ValueError('no setup failure to resume')
        attempt.mkdir(mode=0o700)
        return
    if not resume:
        raise FileExistsError('attempt exists; explicit setup resume required')
    ledger = attempt/'budget.sqlite'
    if ledger.is_symlink() or not ledger.is_file():
        raise ValueError('existing regular case ledger required for resume')
    old = json.loads((attempt/'status.json').read_text())
    if old.get('status') not in ('setup_failed', 'coordinator_error'):
        raise ValueError('prior outcome does not permit setup resume')
    if any((attempt/name).exists() for name in ('native-start.json','command-log.json','primary.json')):
        raise ValueError('native invocation may already have started')
    n = 1
    while (attempt/f'setup-history-{n}').exists():
        n += 1
    history = attempt/f'setup-history-{n}'
    history.mkdir(mode=0o700)
    for item in list(attempt.iterdir()):
        if item.name in {'budget.sqlite','budget.sqlite-wal','budget.sqlite-shm',history.name} or item.name.startswith('setup-history-'):
            continue
        shutil.move(str(item), history/item.name)


def _run_case(runtime, attempt, receipt_path, spec_path, resume_setup=False, *, phase='primary'):
    runtime, attempt, receipt_path, spec_path = map(Path, (runtime, attempt, receipt_path, spec_path))
    receipt = check_receipt(receipt_path) if phase == 'primary' else check_receipt(receipt_path, phase)
    guarded = Path(os.environ['PILOT_SESSION_ROOT']).resolve(strict=True)
    if not guarded.is_relative_to('/workspace'):
        raise RuntimeError('outer guarded workspace required')
    runtime = runtime.resolve(strict=True)
    if not runtime.is_relative_to('/workspace') or not attempt.resolve().is_relative_to(runtime/('attempts' if phase == 'primary' else 'diagnostics')):
        raise ValueError('attempt must be beneath workspace runtime/attempts')
    spec_bytes = spec_path.read_bytes()
    spec = json.loads(spec_bytes)
    case = spec['case_id']
    if case not in CASES:
        raise ValueError('case outside remaining pilot')
    packet_path = ROOT/'protocol/pilot/execution'/f'{case}.json'
    if (receipt.get('case_plan_sha256', {}).get(case) != hashlib.sha256(spec_bytes).hexdigest()
            or receipt.get('case_packet_sha256', {}).get(case) != digest(packet_path)):
        raise RuntimeError('qualification does not bind this plan and packet')
    for prior in (runtime/('attempts' if phase == 'primary' else 'diagnostics')).iterdir():
        if prior == attempt or not prior.is_dir() or prior.is_symlink():
            continue
        prior_status = prior/'status.json'
        has_marker = any((prior/name).exists() for name in ('native-start.json','primary.json','command-log.json'))
        if (not prior_status.is_file() or prior_status.is_symlink()) and has_marker:
            marker = prior/'native-start.json'
            try:
                marker_case = json.loads(marker.read_text())['case_id']
            except (OSError, ValueError, KeyError, TypeError):
                raise RuntimeError('unresolved prior native marker')
            if marker_case == case:
                raise RuntimeError('a native invocation already exists for this case')
        if not prior_status.is_file() or prior_status.is_symlink():
            continue
        try:
            previous_case = json.loads(prior_status.read_text()).get('case_id')
        except (ValueError, OSError):
            if has_marker and prior.name.startswith(case):
                raise RuntimeError('corrupt prior case status with native marker')
            continue
        if previous_case == case and any((prior/name).exists() for name in ('native-start.json','primary.json','command-log.json')):
            raise RuntimeError('a native invocation already exists for this case')
    _prepare_attempt(attempt, resume_setup)
    _output_remaining(attempt)
    status = {'case_id':case, 'status':'started', 'started_utc':utc(), 'setup_resume':resume_setup, 'phase':phase}
    _save(attempt, attempt/'status.json', status)
    calls = []
    try:
        frozen = json.loads((ROOT/'protocol/pilot/runtime/PILOT-01.json').read_text())
        host_manifest = runtime/'runtime-host-manifest.jsonl'
        with _ledger_meter(attempt/'budget.sqlite'):
            if digest(host_manifest) != frozen['environment']['host_manifest']['sha256']:
                raise RuntimeError('host runtime manifest changed')
            check_host_tree(host_manifest)
            _check_supplemental_manifests(receipt)
            mounts, input_bytes = _inputs(spec)
        known = spec.get('known_input_payload_predebit', 0)
        if not isinstance(known, int) or isinstance(known, bool) or known < 0:
            raise ValueError('invalid known input payload debit')
        debit = max(input_bytes, known)
        adapter = _adapter(spec)
        packet = json.loads(packet_path.read_text())
        native_argv = _native_argv(spec['native_shell_command'])
        prompt = json.dumps(packet) + ('\nExecute exactly this locked command once through the broker: '
                 + json.dumps(native_argv) + '. Do not change arguments, retry, invoke native tools, '
                 'request assessment data, or perform any other command. Then finish using the broker result.')
        lock = {'case_id':case, 'locked_utc':utc(), 'spec_sha256':hashlib.sha256(spec_bytes).hexdigest(),
                'packet_sha256':digest(packet_path), 'qualification_sha256':digest(receipt_path),
                'reference_adapter_sha256':spec['reference_adapter_sha256'], 'model':PINNED_MODEL, 'phase':phase,
                'native_argv':native_argv, 'retry':'none', 'setup_resume':resume_setup,
                'input_debit':'full input sizes debited on each setup including any explicit resume',
                'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest()}
        _control_write(attempt, attempt/'spec.json', spec_bytes)
        _control_write(attempt, attempt/'qualification.json', receipt_path.read_bytes())
        if digest(attempt/'qualification.json') != lock['qualification_sha256']:
            raise RuntimeError('qualification changed during snapshot')
        check_receipt(attempt/'qualification.json') if phase == 'primary' else check_receipt(attempt/'qualification.json', phase)
        _save(attempt, attempt/'lock.json', lock)
        _control_write(attempt, attempt/'model-packet.txt', prompt.encode())
        predebit = {'input_bytes':input_bytes, 'known_input_bytes':known, 'charged_bytes':debit, 'status':'pending'}
        _save(attempt, attempt/'predebit.json', predebit)
        _predebit(attempt/'budget.sqlite', debit)
        predebit['status'] = 'debited'
        _save(attempt, attempt/'predebit.json', predebit)
        with CaseSession(workspace_parent=guarded, state_parent=guarded,
                         ledger_path=attempt/'budget.sqlite',
                         fuse2fs=runtime/'fuse-runtime/extracted/usr/bin/fuse2fs',
                         library_dir=runtime/'fuse-runtime/extracted/lib/x86_64-linux-gnu',
                         allowed_hosts=spec['hosts'], allowed_schemes=('http','https'),
                         case_inputs=mounts, guest_aliases=spec.get('guest_aliases', {}),
                         disk_bytes=OUTPUT_LIMIT, broker_timeout=10800,
                         allow_publisher_cookies=(phase == 'diagnostic')) as session:
            try:
                _save(attempt, attempt/'input-manifest.json', session.input_manifest['case'])
                observed = {x['target']: x['sha256'] for x in session.input_manifest['case']}
                if observed != {x['target']: x['sha256'] for x in spec['inputs']}:
                    raise RuntimeError('input snapshot differs from frozen plan')
                for i, staging in enumerate(spec.get('staging', [])):
                    remaining = session.budget.remaining(active=False)
                    value = session.stage_runtime(staging['input'], destination=staging['destination'],
                                                  timeout=min(1800, remaining-5))
                    _save(attempt, attempt/f'staging-{i:02}.json', value)
                for directory in ['output', *spec.get('directories', [])]:
                    result = session.execute(['/usr/bin/mkdir','-p','/work/'+str(_relative(directory))],
                                             timeout=30, network=False, env=spec.get('env'))
                    if not _ok(result):
                        raise RuntimeError('directory setup failed: ' + str(directory))
                setup = []
                for command in spec.get('setup_shell_commands', []):
                    remaining = session.budget.remaining(active=True)
                    result = session.execute(_shell(command), timeout=min(1800, remaining-5),
                                             env=spec.get('env'), network=False)
                    setup.append({'command':command, 'result':result})
                    _save(attempt, attempt/'setup-log.json', setup)
                    if not _ok(result):
                        raise RuntimeError('offline setup failed')
                meter = min(1800, session.budget.remaining(active=False)-5)
                if meter <= 0:
                    raise RuntimeError('no time for installation manifest')
                with session.external_reservation(meter, active=False):
                    _save(attempt, attempt/'installed-manifest.json', _manifest_roots(session.executor_scratch,
                         spec.get('installation_roots', [])))
                def reference(label):
                    try:
                        value = adapter.capture(case, session)
                    except Exception as error:
                        value = {'status':'capture_failed', 'error':type(error).__name__+': '+str(error)}
                    _save(attempt, attempt/f'reference-{label}.json', value)
                reference('before')
                def decide(text):
                    maximum = min(125, session.budget.remaining(active=True))
                    if maximum <= 5:
                        raise RuntimeError('model time exhausted')
                    with session.external_reservation(maximum, active=True):
                        return cli_decide(text, scratch=guarded, timeout=maximum-5)
                def broker(argv, timeout):
                    if calls or argv != native_argv or (attempt/'native-start.json').exists():
                        raise RuntimeError('only one exact locked native invocation is allowed')
                    entry = {'case_id':case, 'argv':argv, 'status':'started', 'started_utc':utc()}
                    _control_write(attempt, attempt/'native-start.json', json.dumps(entry).encode(), exclusive=True)
                    dirfd = os.open(attempt, os.O_RDONLY | os.O_DIRECTORY)
                    try:
                        os.fsync(dirfd)
                    finally:
                        os.close(dirfd)
                    calls.append(entry)
                    _save(attempt, attempt/'command-log.json', calls)
                    remaining = session.budget.remaining(active=True)
                    if remaining <= 5:
                        raise RuntimeError('native time exhausted')
                    entry['result'] = session.execute(argv, timeout=min(timeout, remaining-5), env=spec.get('env'))
                    entry['status'] = 'finished'
                    _save(attempt, attempt/'command-log.json', calls)
                    return entry['result']
                try:
                    status['agent'] = run_agent(prompt, decide=decide, broker=broker,
                                                max_turns=4, command_timeout=10800)
                    status['status'] = ('primary_finished_pending_assessment' if phase == 'primary' else 'diagnostic_finished_pending_assessment') if calls else 'no_native_invocation'
                except Exception as error:
                    status['status'] = 'executor_or_recording_error'
                    status['error'] = type(error).__name__ + ': ' + str(error)
                # Lock native logs first so later output inventory failures retain them.
                meter = min(1800, session.budget.remaining(active=False)-5)
                if meter <= 0:
                    raise RuntimeError('no time for native log capture')
                with session.external_reservation(meter, active=False):
                    log_paths = _output_paths(session.executor_scratch, ['output/native.stdout', 'output/native.stderr'])
                    log_records = lock_outputs(session.executor_scratch, attempt/'native-logs', log_paths,
                                               max_bytes=_output_remaining(attempt), max_path_bytes=1024)
                status['native_logs'] = log_records
                _save(attempt, attempt/'status.json', status)
                meter = min(1800, session.budget.remaining(active=False)-5)
                if meter <= 0:
                    raise RuntimeError('no time for output capture')
                with session.external_reservation(meter, active=False):
                    paths = [p for p in _output_paths(session.executor_scratch,
                             ['output', *spec.get('additional_output_roots', [])]) if p not in log_paths]
                    status['outputs'] = lock_outputs(session.executor_scratch, attempt/'outputs', paths,
                                                     max_bytes=_output_remaining(attempt), max_path_bytes=1024)
                status['primary_locked_utc'] = utc()
                _save(attempt, attempt/'primary.json', status)
                reference('after')
                meter = min(1800, session.budget.remaining(active=False)-5)
                if meter <= 0:
                    raise RuntimeError('no time for reference capture')
                with session.external_reservation(meter, active=False):
                    reference_paths = _output_paths(session.reference_scratch, ['.'])
                    status['reference_files'] = lock_outputs(session.reference_scratch, attempt/'reference',
                        reference_paths, max_bytes=_output_remaining(attempt), max_files=10000-len(paths), max_path_bytes=1024)
            except Exception:
                if not calls:
                    status['status'] = 'setup_failed'
                    try:
                        meter = min(1800, session.budget.remaining(active=False)-5)
                        if meter <= 0:
                            raise RuntimeError('no time for setup output capture')
                        with session.external_reservation(meter, active=False):
                            paths = _output_paths(session.executor_scratch, ['output', *spec.get('additional_output_roots', [])])
                            status['setup_outputs'] = lock_outputs(session.executor_scratch, attempt/'setup-outputs', paths,
                                                                   max_bytes=_output_remaining(attempt), max_path_bytes=1024)
                    except Exception as capture_error:
                        status['setup_capture_error'] = type(capture_error).__name__ + ': ' + str(capture_error)
                raise
            finally:
                status['broker_events'] = session.broker.events
                status['broker_dropped_events'] = session.broker.dropped_event_count
                status['resources'] = session.budget.snapshot()
                _save(attempt, attempt/'status.json', status)
        ledger = CaseBudget(attempt/'budget.sqlite')
        try:
            status['resources_post_cleanup'] = ledger.snapshot()
        finally:
            ledger.close()
        status['finished_utc'] = utc()
    except Exception as error:
        if status.get('status') != 'setup_failed':
            status['status'] = 'coordinator_error'
        status['error'] = type(error).__name__+': '+str(error)
        status['finished_utc'] = utc()
    try:
        with _ledger_meter(attempt/'budget.sqlite'):
            manifest = runtime/'runtime-host-manifest.jsonl'
            frozen = json.loads((ROOT/'protocol/pilot/runtime/PILOT-01.json').read_text())
            if digest(manifest) != frozen['environment']['host_manifest']['sha256']:
                raise RuntimeError('host runtime manifest changed')
            check_host_tree(manifest)
            _check_supplemental_manifests(receipt)
        status['runtime_postcheck'] = 'matched_frozen_manifest'
    except Exception as error:
        status['runtime_postcheck'] = 'unresolved_or_changed: ' + str(error)
    if (attempt/'budget.sqlite').is_file():
        ledger = CaseBudget(attempt/'budget.sqlite')
        try:
            status['resources_post_cleanup'] = ledger.snapshot()
        finally:
            ledger.close()
    _save(attempt, attempt/'status.json', status)
    return status


def run_case(runtime, attempt, receipt_path, spec_path, resume_setup=False, *, phase='primary'):
    if phase == 'diagnostic':
        if resume_setup:
            raise ValueError('diagnostic setup resume is not authorized')
        from executor.diagnostic import run_diagnostic
        return run_diagnostic(runtime, attempt, receipt_path, spec_path)
    if phase != 'primary':
        raise ValueError('unknown phase')
    return _run_case(runtime, attempt, receipt_path, spec_path, resume_setup)


def main():
    parser = argparse.ArgumentParser()
    for name in ('runtime', 'attempt', 'qualification', 'spec'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--resume-setup', action='store_true')
    args = parser.parse_args()
    result = run_case(args.runtime, args.attempt, args.qualification, args.spec, args.resume_setup)
    print(json.dumps({'case_id':result['case_id'], 'status':result['status'], 'attempt':str(args.attempt)}))

if __name__ == '__main__':
    main()
