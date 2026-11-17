"""Manual synthetic live-model integration; no candidate code or health data."""
import json, os
from pathlib import Path
from executor.session import CaseSession
from executor.model_runtime import cli_decide, run_agent

runtime=Path(os.environ['PILOT_RUNTIME'])
root=Path(os.environ['PILOT_SESSION_ROOT'])
with CaseSession(workspace_parent=root,state_parent=root,ledger_path=root/'budget.sqlite',
                 fuse2fs=runtime/'fuse-runtime/extracted/usr/bin/fuse2fs',
                 library_dir=runtime/'fuse-runtime/extracted/lib/x86_64-linux-gnu',
                 allowed_hosts=['example.com'],disk_bytes=32*1024**2) as session:
    def decide(prompt):
        with session.external_reservation(125,active=True):
            return cli_decide(prompt,scratch=root,timeout=120)
    def broker(argv,timeout):
        return session.execute(argv,timeout=timeout)
    result=run_agent('Synthetic test only: run printf synthetic-guarded-pong once, then finish with exactly that observed text. No native tools or other actions.',
                     decide=decide,broker=broker,max_turns=3,command_timeout=10)
    assert result['status']=='finished', result
    assert len(result['history'])==1 and result['history'][0]['result']['stdout']=='synthetic-guarded-pong', result
    assert result['history'][0]['result']['returncode']==0, result
    print(json.dumps({'status':'pass','history':result['history'],'summary':result['summary'],'resources':session.budget.snapshot()}))
