"""Validate repository records and local file links; no external requests."""
import csv
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]


def main():
    files = [path for path in ROOT.rglob("*.json") if ".git" not in path.parts]
    for path in files:
        json.loads(path.read_text())
    with (ROOT / "sources.csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    ids = [row["record_id"] for row in rows]
    assert len(ids) == len(set(ids)), "Duplicate source observation IDs"
    for row in rows:
        assert all(row.values()), f"Incomplete source record: {row}"
        assert urlsplit(row["url"]).scheme in {"https", "http"}, row["url"]

    candidates = json.loads((ROOT / "research/candidates/candidate-code-inspection-2026-11-17.json").read_text())
    historic = candidates["historical_source"]
    path = ROOT / "research/candidates" / historic["path"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == historic["sha256"], "Historical artifact changed"
    candidate_ids = [item["id"] for item in candidates["candidates"]]
    assert len(candidate_ids) == len(set(candidate_ids)), "Duplicate candidate IDs"
    for item in candidates["candidates"]:
        assert re.fullmatch(r"[0-9a-f]{40}", item["inspected_sha"]), item["id"]
        for key in ("docs_url", "code_url"):
            assert f'/blob/{item["inspected_sha"]}/' in item[key], item[key]

    broken = []
    for path in ROOT.rglob("*.md"):
        if ".git" in path.parts:
            continue
        for target in re.findall(r"\]\(([^\s)]+)(?:\s+[^)]*)?\)", path.read_text()):
            parsed = urlsplit(target.strip("<>"))
            if parsed.scheme or not parsed.path:
                continue
            resolved = path.parent / unquote(parsed.path)
            if not resolved.exists():
                broken.append(f"{path.relative_to(ROOT)}: {target}")
    assert not broken, "Missing local link targets:\n" + "\n".join(broken)
    from prepare_pilot_packets import build
    for path, expected in build().items():
        assert path.exists() and path.read_bytes() == expected, f"Stale pilot artifact: {path}"
    print(f"PASS: {len(files)} JSON files, {len(rows)} source observations, "
          f"{len(candidate_ids)} immutable candidate records, historical hash, local link targets")
    print("Limits: no external URL, source-truth, runtime, isolation or scientific validation.")


if __name__ == "__main__":
    main()
