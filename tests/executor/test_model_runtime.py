import unittest
from unittest.mock import patch
from types import SimpleNamespace
import tempfile
import os
import sys
import time
from executor.model_runtime import run_agent, validate_action, cli_decide, _bounded_process

class ModelRuntimeTests(unittest.TestCase):
    def test_agent_uses_broker_result_next_turn(self):
        prompts = []
        decisions = iter([{'action':'run', 'command':['cat', 'input.txt'], 'summary':''},
                          {'action':'finish', 'command':[], 'summary':'observed synthetic'}])
        def decide(prompt):
            prompts.append(prompt)
            return next(decisions)
        calls = []
        def broker(argv, timeout):
            calls.append((argv, timeout))
            return {'stdout':'synthetic', 'returncode':0}
        result = run_agent('read input.txt', decide=decide, broker=broker)
        self.assertEqual(result['status'], 'finished')
        self.assertEqual(calls, [(['cat', 'input.txt'], 30)])
        self.assertIn('synthetic', prompts[1])

    def test_rejects_invalid_actions_before_broker(self):
        bad = [
            {'action':'run','command':['cat','/etc/passwd'],'summary':''},
            {'action':'run','command':['cat','../private'],'summary':''},
            {'action':'run','command':['cat'],'summary':'premature'},
            {'action':'finish','command':['cat'],'summary':''},
            {'action':'run','command':[],'summary':''},
            {'action':'run','command':['x'],'summary':'','extra':1},
        ]
        for action in bad:
            with self.subTest(action=action), self.assertRaises(ValueError):
                validate_action(action)

    def test_native_tool_attempt_rejected_even_with_valid_final_json(self):
        events = [
            {"type":"thread.started"}, {"type":"turn.started"},
            {"type":"item.completed", "item":{"type":"agent_message", "text":
                '{"action":"finish","command":[],"summary":"done"}'}},
            {"type":"turn.completed"},
        ]
        import json
        response = SimpleNamespace(returncode=0, stdout="\n".join(map(json.dumps, events)),
                                   stderr="error=code-mode host is disabled")
        with tempfile.TemporaryDirectory(dir='/workspace/build/builderbob') as scratch:
            with patch('executor.model_runtime._bounded_process', return_value=response):
                with self.assertRaisesRegex(RuntimeError, 'native tool invocation'):
                    cli_decide('synthetic', scratch=scratch)

    def test_stream_limit_and_timeout(self):
        with tempfile.TemporaryDirectory(dir='/workspace/build/builderbob') as scratch:
            env = {'PATH':'/usr/bin:/bin', 'HOME':os.environ['HOME']}
            with self.assertRaisesRegex(RuntimeError, 'output limit'):
                _bounded_process([sys.executable, '-c', 'print("x" * 100000)'],
                                 input_text='', env=env, cwd=scratch, timeout=5, max_output=1024)
            with self.assertRaisesRegex(RuntimeError, 'timed out'):
                _bounded_process([sys.executable, '-c', 'import time; time.sleep(10)'],
                                 input_text='', env=env, cwd=scratch, timeout=.2)

    def test_namespace_cleans_detached_descendant_after_leader_exits(self):
        with tempfile.TemporaryDirectory(dir='/workspace/build/builderbob') as scratch:
            marker = os.path.join(scratch, 'marker')
            code = ('import os,time; p=os.fork(); '
                    '(os.setsid(),time.sleep(.4),open('+repr(marker)+',"w").write("bad")) '
                    'if p==0 else os._exit(0)')
            result = _bounded_process([sys.executable, '-c', code], input_text='',
                                      env={'PATH':'/usr/bin:/bin','HOME':os.environ['HOME']},
                                      cwd=scratch, timeout=5)
            self.assertEqual(result.returncode, 0)
            time.sleep(.6)
            self.assertFalse(os.path.exists(marker))

    def test_model_call_reserves_and_reconciles_shared_budget_on_failure(self):
        class Budget:
            def __init__(self): self.events = []
            def remaining(self, *, active):
                self.events.append(('remaining', active)); return 5
            def reserve(self, seconds, *, active):
                self.events.append(('reserve', seconds, active)); return 'token'
            def finish(self, token, elapsed): self.events.append(('finish', token, elapsed))
        budget = Budget()
        with patch('executor.model_runtime._cli_decide', side_effect=RuntimeError('synthetic')) as call:
            with self.assertRaisesRegex(RuntimeError, 'synthetic'):
                cli_decide('synthetic', scratch='/workspace', timeout=20, budget=budget)
        self.assertAlmostEqual(call.call_args.kwargs['timeout'], 4.9)
        self.assertEqual(budget.events[1], ('reserve', 4.9, True))
        self.assertEqual(budget.events[2][0:2], ('finish', 'token'))

    def test_bounded_results_and_turns(self):
        action = {'action':'run','command':['true'],'summary':''}
        with self.assertRaises(RuntimeError):
            run_agent('task', decide=lambda _: action,
                      broker=lambda *_: {'stdout':'x'*20000}, max_turns=1)
        result = run_agent('task', decide=lambda _: action,
                           broker=lambda *_: {'returncode':0}, max_turns=1)
        self.assertEqual(result['status'], 'turn_limit')

if __name__ == '__main__':
    unittest.main()
