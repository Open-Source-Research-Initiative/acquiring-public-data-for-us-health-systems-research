import json, os, sys
from pathlib import Path
repo=Path('/workspace/repos/builderbob/open-source-research-initiative/repos/acquiring-public-data-for-us-health-systems-research')
sys.path.insert(0,str(repo))
from executor.coordinator_guard import run_guarded
from executor.remaining import check_receipt,_check_supplemental_manifests,_predebit
from executor.session import CaseSession
from executor.supervisor import CaseBudget
from executor.pilot import save,digest,check_host_tree
r=Path(__file__).resolve().parent.parent
out=r/'diagnostic-probes'
script=out/'probe.R'
archive=r/'externalruntime/r-staging/r-runtime.tar.gz'
ledger=out/'probe-budget.sqlite'
prefix='/workspace/cache/builderbob/medsci-runtime/20261111/r'
if '--inside' not in sys.argv:
 if ledger.exists(): raise RuntimeError('fresh probe ledger required')
 res=run_guarded(['/usr/bin/python3',str(Path(__file__).resolve()),'--inside'],workspace_parent='/workspace/repos/builderbob/.osri-pilot',timeout=900)
 save(out/'guard-result.json',res); print(json.dumps(res))
else:
 receipt=check_receipt(repo/'evidence/executor/qualification-diagnostics-v1.json', 'diagnostic')
 expected='96905b47a8268e07688a09ecf7a80f21f60241daeee1ddbf14eb2f5cc82f5e16'
 if digest(archive)!=expected: raise RuntimeError('runtime archive drift')
 inputs={str(archive):'/inputs/runtime.tar.gz',str(script):'/inputs/probe.R'}
 save(out/'lock.json',{'phase':'technical request stack only','inputs':{p:digest(Path(p)) for p in inputs},'guard_seconds':900,'disk_bytes':46*1024**3,'network_bytes':20*1024**3,'response_limit_bytes':8*1024**2,'sequence':'default deny then publisher cookie opt in; each session runs 06 then 07','no_candidate_install_or_invocation':True})
 guarded=Path(os.environ['PILOT_SESSION_ROOT'])
 for policy in (False,True):
  label='default-deny' if not policy else 'publisher-cookie-opt-in'
  _predebit(ledger,sum(Path(p).stat().st_size for p in inputs))
  with CaseSession(workspace_parent=guarded,state_parent=guarded,ledger_path=ledger,fuse2fs=r/'fuse-runtime/extracted/usr/bin/fuse2fs',library_dir=r/'fuse-runtime/extracted/lib/x86_64-linux-gnu',case_inputs=inputs,guest_aliases={prefix:'runtime/r'},allowed_hosts=['ephtracking.cdc.gov','zenodo.org'],disk_bytes=46*1024**3,network_bytes=20*1024**3,allowed_schemes=('https',),allow_publisher_cookies=policy) as session:
   with session.external_reservation(120,active=False):
    check_host_tree(r/'runtime-host-manifest.jsonl'); _check_supplemental_manifests(receipt)
   save(out/(label+'-inputs.json'),session.input_manifest['case'])
   save(out/(label+'-stage.json'),session.stage_runtime('/inputs/runtime.tar.gz',destination='runtime',timeout=300))
   for case in ('06','07'):
    result=session.execute([prefix+'/bin/Rscript','--vanilla','/inputs/probe.R',case],timeout=110,env={'PATH':prefix+'/bin:/usr/bin:/bin'})
    save(out/(label+'-'+case+'.json'),result)
   save(out/(label+'-events.json'),session.broker.events)
   with session.external_reservation(120,active=False):
    check_host_tree(r/'runtime-host-manifest.jsonl'); _check_supplemental_manifests(receipt)
  b=CaseBudget(ledger,network_bytes=20*1024**3); save(out/(label+'-accounting.json'),b.snapshot());b.close()
