"""Experimental structured-action model adapter; not qualified for pilot use.

Only the supplied broker callback executes commands. Native tools must be
independently tested and disabled; JSON schema validation alone is not a
security boundary. Never give this adapter assessment material.
"""
import json
import os
import selectors
import signal
import time
from pathlib import Path
import subprocess
import tempfile

SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'properties': {
        'action': {'type': 'string', 'enum': ['run', 'finish']},
        'command': {'type': 'array', 'items': {'type': 'string'}},
        'summary': {'type': 'string'},
    }, 'required': ['action', 'command', 'summary'],
}
MAX_PROMPT = 131072
MAX_RESULT = 16000
MAX_ARG = 4096
MAX_ARGS = 64
MAX_PROCESS_OUTPUT = 1000000
PINNED_MODEL = "gpt-6.1-terra"


def validate_action(value):
    if not isinstance(value, dict) or set(value) != {'action', 'command', 'summary'}:
        raise ValueError('invalid action fields')
    action, command, summary = value['action'], value['command'], value['summary']
    if action not in ('run', 'finish') or not isinstance(summary, str) or len(summary) > MAX_RESULT:
        raise ValueError('invalid action or summary')
    if not isinstance(command, list) or len(command) > MAX_ARGS or any(
        not isinstance(x, str) or not x or len(x) > MAX_ARG or '\0' in x for x in command
    ):
        raise ValueError('invalid command')
    if (action == 'run' and (not command or summary)) or (action == 'finish' and command):
        raise ValueError('command inconsistent with action')
    # Defense in depth, not containment: the broker MUST isolate even shell code.
    for arg in command:
        if arg.startswith('/') or any(part == '..' for part in arg.split('/')):
            raise ValueError('absolute and parent paths are not accepted')
    return value


def _bounded_process(argv, *, input_text, env, cwd, timeout, max_output=MAX_PROCESS_OUTPUT):
    """Run under a PID namespace and cap combined pipe bytes while streaming.

    The target is namespace PID 1. Its death destroys the namespace and kills
    descendants, including descendants that created a new session. The outer
    unshare process kills it if the launcher is killed. This is cleanup, not a
    filesystem or network sandbox. Fail closed if namespaces are unavailable.
    """
    args = ['/usr/bin/unshare', '--map-current-user', '--pid', '--fork',
            '--kill-child=KILL', '--', *argv]
    proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env=env, cwd=cwd,
                            start_new_session=True, close_fds=True)
    selector = selectors.DefaultSelector()
    content = {'stdout': bytearray(), 'stderr': bytearray()}
    pending = memoryview(input_text.encode('utf-8'))
    deadline = time.monotonic() + timeout
    try:
        os.set_blocking(proc.stdin.fileno(), False)
        selector.register(proc.stdin, selectors.EVENT_WRITE, 'stdin')
        for name in content:
            stream = getattr(proc, name)
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, name)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError('model process timed out')
            for key, _ in selector.select(min(remaining, 0.2)):
                if key.data == 'stdin':
                    if pending:
                        try:
                            count = os.write(key.fd, pending[:65536])
                            pending = pending[count:]
                        except BrokenPipeError:
                            pending = pending[:0]
                    if not pending:
                        selector.unregister(key.fileobj)
                        key.fileobj.close()
                    continue
                chunk = os.read(key.fd, 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    key.fileobj.close()
                    continue
                if sum(map(len, content.values())) + len(chunk) > max_output:
                    raise RuntimeError('model process output limit exceeded')
                content[key.data].extend(chunk)
        try:
            returncode = proc.wait(timeout=max(0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError('model process timed out') from exc
        return subprocess.CompletedProcess(argv, returncode,
            content['stdout'].decode('utf-8', 'replace'),
            content['stderr'].decode('utf-8', 'replace'))
    finally:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()
        selector.close()
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            if not stream.closed:
                stream.close()


def _cli_decide(prompt, *, scratch, timeout=120, model=PINNED_MODEL):
    """Obtain one decision via native CLI authentication, with no native tools.

    The startup code-mode error is expected. A later error or non-message item
    aborts the decision. Model output and diagnostics never contain credentials
    by design, but still require the caller's ordinary transcript controls.
    """
    scratch = Path(scratch).resolve(strict=True)
    if not scratch.is_dir() or Path('/workspace') not in scratch.parents:
        raise ValueError('scratch must be below /workspace')
    if not isinstance(prompt, str) or len(prompt.encode()) > MAX_PROMPT:
        raise ValueError('invalid prompt')
    if not 0 < timeout <= 600:
        raise ValueError('invalid model timeout')
    if model != PINNED_MODEL:
        raise ValueError('model must match the pinned experimental model')
    codex = '/home/builderbob/.local/bin/codex'
    env = {'HOME': os.environ['HOME'], 'PATH': '/home/builderbob/.local/bin:/usr/bin:/bin',
           'LANG': 'C.UTF-8', 'TMPDIR': str(scratch)}
    if 'CODEX_HOME' in os.environ:
        env['CODEX_HOME'] = os.environ['CODEX_HOME']
    disabled = ['shell_tool', 'unified_exec', 'apps', 'plugins', 'view_image',
                'multi_agent', 'multi_agent_v2', 'skill_search', 'remote_plugin',
                'code_mode_host', 'goals', 'sleep_tool', 'image_generation',
                'browser_use', 'computer_use', 'memories']
    with tempfile.TemporaryDirectory(prefix='model-', dir=scratch) as temp:
        schema = Path(temp) / 'schema.json'
        schema.write_text(json.dumps(SCHEMA), encoding='utf-8')
        args = [codex, 'exec', '--ignore-user-config', '--ignore-rules', '--ephemeral',
                '--skip-git-repo-check', '--sandbox', 'read-only', '--json',
                '--output-schema', str(schema), '--enable', 'skip_host_skill_discovery',
                '-c', 'web_search="disabled"',
                '-C', temp]
        for flag in disabled:
            args += ['--disable', flag]
        args += ['--model', model]
        args += ['-']
        result = _bounded_process(args, input_text=prompt, env=env, cwd=temp, timeout=timeout)
        if 'code-mode host is disabled' in result.stderr:
            raise RuntimeError('native tool invocation rejected')
        if result.returncode != 0:
            raise RuntimeError('model process failed or exceeded output bound')
        messages = []
        started = False
        for line in result.stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError('invalid model event') from exc
            kind = event.get('type')
            if kind == 'turn.started':
                started = True
            if kind == 'item.completed':
                item = event.get('item', {})
                if item.get('type') == 'error' and not started and item.get('message', '').startswith(('Code Mode is unavailable because code-mode host is disabled.', 'Under-development features enabled: skip_host_skill_discovery.')):
                    continue
                if item.get('type') != 'agent_message':
                    raise RuntimeError('unexpected native tool or error event')
                messages.append(item.get('text', ''))
            elif kind not in ('thread.started', 'turn.started', 'turn.completed'):
                raise RuntimeError('unexpected model event')
        if not messages:
            raise RuntimeError('no model response')
        try:
            return validate_action(json.loads(messages[-1]))
        except (json.JSONDecodeError, ValueError) as exc:
            raise RuntimeError('invalid structured model response') from exc


def cli_decide(prompt, *, scratch, timeout=120, model=PINNED_MODEL, budget=None):
    """Make one decision, optionally charging the shared coordinator ledger.

    The reserved timeout is at most the remaining active case budget. Both
    active and VM time are conservatively charged for the entire hosted model
    call, including process cleanup. A crash leaves the reservation charged.
    """
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not 0 < timeout <= 600:
        raise ValueError('invalid model timeout')
    if budget is None:
        return _cli_decide(prompt, scratch=scratch, timeout=timeout, model=model)
    # Leave a margin because elapsed time advances between snapshot and reserve.
    allowed = min(timeout, budget.remaining(active=True) - 0.1)
    if allowed <= 0:
        raise RuntimeError('case time budget exhausted')
    token = budget.reserve(allowed, active=True)
    started = time.clock_gettime(time.CLOCK_BOOTTIME)
    try:
        return _cli_decide(prompt, scratch=scratch, timeout=allowed, model=model)
    finally:
        budget.finish(token, time.clock_gettime(time.CLOCK_BOOTTIME) - started)


def run_agent(packet, *, decide, broker, max_turns=8, command_timeout=30):
    """Execute a bounded action loop using injected model and sandbox broker.

    Each `decide(prompt)` must start an ephemeral isolated model turn; `broker`
    accepts only (argv, timeout) and returns a JSON-serializable result. The
    caller must enforce a total time budget, lock all inputs and outputs, and
    establish the sandbox and native-tool boundary before using real cases.
    """
    if not isinstance(packet, str) or len(packet.encode()) > MAX_PROMPT // 2:
        raise ValueError('invalid packet')
    if not isinstance(max_turns, int) or not 1 <= max_turns <= 100:
        raise ValueError('invalid turn limit')
    if not isinstance(command_timeout, (int, float)) or not 0 < command_timeout <= 21600:
        raise ValueError('invalid command timeout')
    history = []
    for _ in range(max_turns):
        prompt = ('Use the locked task and action history below. Return one JSON action. '
                  'For run, supply an argv command and empty summary; for finish, '
                  'supply an empty command and a summary. Commands run only in the '
                  'constrained broker. Do not invoke native tools.\n'
                  + json.dumps({'task': packet, 'history': history}, ensure_ascii=True))
        if len(prompt.encode()) > MAX_PROMPT:
            raise RuntimeError('model context limit exceeded')
        action = validate_action(decide(prompt))
        if action['action'] == 'finish':
            return {'status': 'finished', 'summary': action['summary'], 'history': history}
        outcome = broker(action['command'], command_timeout)
        encoded = json.dumps(outcome, ensure_ascii=True)
        if len(encoded.encode()) > MAX_RESULT:
            raise RuntimeError('broker result exceeds context bound')
        history.append({'action': action, 'result': outcome})
    return {'status': 'turn_limit', 'summary': '', 'history': history}
