#!/usr/bin/env python3
"""Check structural completeness of the fixed screening packet, not scientific truth."""
import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
ROUND = ROOT / 'research/screening/2026-11-17'
EXPECTED_HASH = '6172db0ca1787f40a8e9666dbe52b895576874320f1c0e4217b9262a5a3824f0'
CLASSES = {'eligible', 'companion', 'excluded', 'unresolved'}
errors = []


def fail(where, message):
    errors.append(f'{where}: {message}')


def read(path, required=True):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError as exc:
        if required:
            fail(str(path.relative_to(ROOT)), f'cannot read JSON: {exc}')
        return None
    except (OSError, ValueError) as exc:
        fail(str(path.relative_to(ROOT)), f'cannot read JSON: {exc}')
        return None


def string(obj, key, where, nullable=False):
    value = obj.get(key)
    if key not in obj or (not (nullable and value is None) and (not isinstance(value, str) or not value.strip())):
        fail(where, f'{key} must be a nonempty string' + (' or null' if nullable else ''))


def notes(obj, key, where):
    value = obj.get(key)
    if isinstance(value, str) and value.strip():
        return
    if isinstance(value, list) and all(isinstance(x, str) and x.strip() for x in value):
        return
    fail(where, f"{key} must be a nonempty string or a list of nonempty strings")


def timestamp(obj, key, where):
    string(obj, key, where)
    try:
        dt = datetime.fromisoformat(obj.get(key, '').replace('Z', '+00:00'))
        if dt.utcoffset() is None:
            raise ValueError('timezone required')
    except (ValueError, TypeError, AttributeError):
        fail(where, f'{key} must be an ISO 8601 timestamp with timezone')


def url(obj, key, where):
    string(obj, key, where)
    value = obj.get(key)
    if not isinstance(value, str) or urlparse(value).scheme not in ('http', 'https') or not urlparse(value).netloc:
        fail(where, f'{key} must be an HTTP(S) URL')


def evidence(record, where):
    entries = record.get('evidence')
    if not isinstance(entries, list) or not entries:
        fail(where, 'evidence must be a nonempty list')
        return
    for i, item in enumerate(entries):
        loc = f'{where}.evidence[{i}]'
        if not isinstance(item, dict):
            fail(loc, 'must be an object')
            continue
        url(item, 'url', loc)
        timestamp(item, 'accessed_utc', loc)
        string(item, 'observation', loc)
        string(item, 'access_status', loc)
        for field in ('revision', 'path', 'sha256'):
            string(item, field, loc, nullable=True)
        digest = item.get('sha256')
        if isinstance(digest, str) and not re.fullmatch(r'[a-fA-F0-9]{64}', digest):
            fail(loc, 'sha256 must be a 64-character hexadecimal digest or null')


def records(doc, where):
    if not isinstance(doc, dict) or not isinstance(doc.get('records'), list):
        fail(where, 'must be an object with a records list')
        return []
    result = []
    for i, rec in enumerate(doc['records']):
        if not isinstance(rec, dict):
            fail(f'{where}.records[{i}]', 'must be an object')
        else:
            result.append(rec)
    return result


def coverage(actual, expected, where):
    valid = [item for item in actual if isinstance(item, str)]
    if len(valid) != len(actual):
        fail(where, 'every ID must be a string')
    counts = Counter(valid)
    for item in sorted(expected - counts.keys()):
        fail(where, f'missing ID {item}')
    for item in sorted(counts.keys() - expected, key=str):
        fail(where, f'unexpected ID {item!r}')
    for item, count in counts.items():
        if count != 1:
            fail(where, f'ID {item!r} occurs {count} times')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-incomplete', action='store_true', help='do not report absent batch/review files as errors; present files still checked')
    parser.add_argument('--output', type=Path, help='write validation JSON at this path')
    args = parser.parse_args()
    manifest = read(ROUND / 'manifest.json')
    if not isinstance(manifest, dict):
        manifest = {}
    seed_path = ROOT / 'research/candidates/historical-candidate-adjudication-2026-11-16.json'
    try:
        digest = hashlib.sha256(seed_path.read_bytes()).hexdigest()
    except OSError as exc:
        fail('seed', str(exc))
        digest = None
    if digest != EXPECTED_HASH or manifest.get('seed_sha256') != EXPECTED_HASH:
        fail('seed', 'historical seed or manifest hash differs from frozen hash')
    if manifest.get('seed_path') != str(seed_path.relative_to(ROOT)) or manifest.get('seed_count') != 33:
        fail('manifest', 'seed path or count differs from fixed contract')
    seed = read(seed_path)
    seed_entries = seed.get('entries', []) if isinstance(seed, dict) else []
    ids = [x.get('id') for x in seed_entries if isinstance(x, dict)]
    expected_ids = {f'P{i:02}' for i in range(1, 34)}
    coverage(ids, expected_ids, 'seed')
    seed_by_id = {x['id']: x for x in seed_entries if isinstance(x, dict) and isinstance(x.get('id'), str)}
    batches = manifest.get('batches', [])
    if not isinstance(batches, list):
        fail('manifest', 'batches must be a list')
        batches = []
    batch_map = {b.get('batch_id'): b for b in batches if isinstance(b, dict)}
    coverage([b.get('batch_id') for b in batches if isinstance(b, dict)], {f'SCREEN-0{i}' for i in range(1, 5)}, 'manifest batches')
    assigned = []
    for b in batches:
        if isinstance(b, dict) and isinstance(b.get('candidate_ids'), list):
            assigned.extend(b['candidate_ids'])
        else:
            fail('manifest', 'each batch needs candidate_ids')
    coverage(assigned, expected_ids, 'manifest assignments')
    initials = {}
    reviewed = {}
    present_batches = 0
    for number in range(1, 5):
        batch_id = f'SCREEN-0{number}'
        path = ROUND / 'batches' / f'{batch_id}.json'
        doc = read(path, not args.allow_incomplete)
        if doc is None:
            continue
        present_batches += 1
        where = str(path.relative_to(ROOT))
        recs = records(doc, where)
        if not isinstance(doc, dict):
            continue
        batch = batch_map.get(batch_id, {})
        if doc.get('batch_id') != batch_id or doc.get('issue_url') != batch.get('issue_url'):
            fail(where, 'batch_id or issue_url does not match manifest')
        url(doc, 'issue_url', where)
        string(doc, 'performed_by', where)
        notes(doc, 'limitations', where)
        for field in ('started_utc', 'finished_utc'):
            timestamp(doc, field, where)
        coverage([r.get('id') for r in recs], set(batch.get('candidate_ids', [])), where)
        for rec in recs:
            rid = rec.get('id')
            loc = f'{where}:{rid}'
            for field in ('id', 'title', 'canonical_system', 'reason', 'acquisition_entrypoint', 'us_scope', 'data_level', 'pilot_case', 'lineage_notes'):
                string(rec, field, loc, nullable=field in ('acquisition_entrypoint', 'us_scope', 'data_level', 'pilot_case', 'lineage_notes'))
            notes(rec, 'uncertainties', loc)
            url(rec, 'seed_url', loc)
            seed_rec = seed_by_id.get(rid, {}) if isinstance(rid, str) else {}
            if rec.get('title') != seed_rec.get('title') or rec.get('seed_url') != seed_rec.get('url'):
                fail(loc, 'title or seed_url differs from frozen seed')
            if not isinstance(rec.get('classification'), str) or rec['classification'] not in CLASSES:
                fail(loc, 'invalid classification')
            if 'team_authored' not in rec or not (rec['team_authored'] is None or type(rec['team_authored']) is bool):
                fail(loc, 'team_authored must be true, false, or null')
            evidence(rec, loc)
            if isinstance(rid, str):
                initials[rid] = rec.get('classification')
    present_reviews = 0
    for name, nums in (('REVIEW-A', (1, 2)), ('REVIEW-B', (3, 4))):
        path = ROUND / 'reviews' / f'{name}.json'
        doc = read(path, not args.allow_incomplete)
        if doc is None:
            continue
        present_reviews += 1
        where = str(path.relative_to(ROOT))
        recs = records(doc, where)
        if not isinstance(doc, dict):
            continue
        if doc.get('review_id') != name or doc.get('issue_url') != 'https://github.com/Open-Source-Research-Initiative/acquiring-public-data-for-us-health-systems-research/issues/10':
            fail(where, 'review_id or issue_url does not match assignment')
        for field in ('performed_by',):
            string(doc, field, where)
        for field in ('started_utc', 'finished_utc'):
            timestamp(doc, field, where)
        expected = {rid for n in nums for rid in batch_map.get(f'SCREEN-0{n}', {}).get('candidate_ids', [])}
        coverage([r.get('id') for r in recs], expected, where)
        for rec in recs:
            rid = rec.get('id')
            loc = f'{where}:{rid}'
            for field in ('id', 'reason'):
                string(rec, field, loc)
            notes(rec, 'uncertainties', loc)
            for field in ('initial_classification', 'review_classification'):
                if not isinstance(rec.get(field), str) or rec[field] not in CLASSES:
                    fail(loc, f'invalid {field}')
            if isinstance(rid, str) and rid in initials and rec.get('initial_classification') != initials[rid]:
                fail(loc, 'initial_classification differs from batch')
            if type(rec.get('agreement')) is not bool or rec['agreement'] != (rec.get('initial_classification') == rec.get('review_classification')):
                fail(loc, 'agreement must be boolean and match classifications')
            evidence(rec, loc)
            if isinstance(rid, str):
                reviewed[rid] = rec.get('review_classification')
    reconciliation = read(ROUND / 'reconciliation.json', required=False)
    if reconciliation is not None:
        recs = records(reconciliation, 'reconciliation')
        coverage([r.get('id') for r in recs], expected_ids, 'reconciliation')
        for rec in recs:
            loc = f"reconciliation:{rec.get('id')}"
            if isinstance(rec.get('id'), str) and rec['id'] in initials and rec.get('initial_classification') != initials[rec['id']]:
                fail(loc, 'initial_classification differs from batch')
            if isinstance(rec.get('id'), str) and rec['id'] in reviewed and rec.get('review_classification') != reviewed[rec['id']]:
                fail(loc, 'review_classification differs from review')
            for field in ('initial_classification', 'review_classification', 'final_classification'):
                if not isinstance(rec.get(field), str) or rec[field] not in CLASSES:
                    fail(loc, f'invalid {field}')
            for field in ('rationale', 'canonical_system', 'pilot_case', 'candidate_frame_status'):
                string(rec, field, loc, nullable=field == 'pilot_case')
    complete = present_batches == 4 and present_reviews == 2
    result = {'checked_utc': datetime.now(timezone.utc).isoformat(), 'status': 'pass' if not errors and complete else ('incomplete' if not errors else 'fail'), 'seed_sha256': digest, 'seed_count': len(ids), 'batch_files_present': present_batches, 'review_files_present': present_reviews, 'reconciliation_checked': reconciliation is not None, 'errors': errors, 'scope': 'Structural checks only; no eligibility, evidence truth, source access, or human approval established.'}
    rendered = json.dumps(result, indent=2) + '\n'
    if args.output:
        args.output.write_text(rendered)
    print(rendered, end='')
    return 0 if result['status'] == 'pass' or (args.allow_incomplete and result['status'] == 'incomplete') else 1


if __name__ == '__main__':
    raise SystemExit(main())
