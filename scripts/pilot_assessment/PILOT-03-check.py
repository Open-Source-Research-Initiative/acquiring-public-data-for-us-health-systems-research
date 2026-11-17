#!/usr/bin/env python3
"""Compare frozen selected source records to an offline exporter result; no RDS access."""
import argparse, copy, json
from decimal import Decimal
from pathlib import Path
FIELDS = ('data_value','data_value_unit','low_confidence_limit','high_confidence_limit','data_value_footnote_symbol','data_value_footnote')
KEYS = ('year','locationid','measureid','datavaluetypeid')
def value(row, field):
    # Source omitted field and candidate NA are both missing; zero remains distinct.
    v=row.get(field)
    if v is None: return ('missing', None)
    if field in ('data_value','low_confidence_limit','high_confidence_limit'):
        try: return ('number', Decimal(str(v)))
        except Exception: return ('invalid-number', str(v))
    return ('text',str(v))
def check(plan, export):
    results=[]
    batches=export.get('selected_matches',[])
    if len(batches)!=len(plan['selected']): raise ValueError('selection count mismatch')
    for source, matches in zip(plan['selected'],batches):
        # jsonlite may auto-unbox a single match; accept object or array.
        if isinstance(matches,dict): matches=[matches]
        diffs=[]; unavailable=[]
        if len(matches)!=1: results.append({'status':'unmatched_or_multiplicity','count':len(matches)}); continue
        row=matches[0]
        for k in KEYS:
            if str(row.get(k)) != str(source.get(k)): diffs.append(k)
        for f in FIELDS:
            if f not in export['fields_exported']: unavailable.append(f); continue
            if value(row,f)!=value(source,f): diffs.append(f)
        results.append({'status':'different' if diffs else ('partial_agreement' if unavailable else 'match'),'differences':diffs,'unavailable_fields':unavailable})
    return results
def test():
    row=dict(year='2023',locationid='001',measureid='M',datavaluetypeid='T',data_value='0',data_value_unit='%',low_confidence_limit='0',high_confidence_limit='1')
    plan={'selected':[row]}; exp={'fields_exported':list(KEYS+FIELDS),'selected_matches':[[copy.deepcopy(row)]]}
    assert check(plan,exp)[0]['status']=='match'
    for field, v in [('locationid','002'),('data_value','1'),('data_value',None)]:
        e=copy.deepcopy(exp); e['selected_matches'][0][0][field]=v
        assert check(plan,e)[0]['status']=='different',field
    e=copy.deepcopy(exp); e['selected_matches'][0]=[]
    assert check(plan,e)[0]['status']=='unmatched_or_multiplicity'
    e=copy.deepcopy(exp); e['fields_exported'].remove('data_value_footnote')
    assert check(plan,e)[0]['status']=='partial_agreement'
    print('PASS: matching, changed key, changed value, missing versus zero, unmatched, unavailable field')
if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--self-test',action='store_true'); p.add_argument('--plan'); p.add_argument('--export'); a=p.parse_args()
    if a.self_test: test()
    else:
        if not a.plan or not a.export: p.error('--plan and --export required')
        print(json.dumps(check(json.loads(Path(a.plan).read_text()),json.loads(Path(a.export).read_text())),indent=2))
