"""Export draft task-only packets and verify selection arithmetic. Never runs tasks."""
import argparse
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "protocol/pilot"
FAMILIES = ["CMS HCRIS", "CMS NPPES", "CDC PLACES", "CDC FluView",
            "CMU Delphi COVIDcast", "CDC Environmental Public Health Tracking",
            "County Health Rankings & Roadmaps", "CMS NPPES"]


def encoded(value):
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def draw(case_id, identifiers, selected, suffix=""):
    assert identifiers == sorted(set(identifiers)), (case_id, identifiers)
    assert identifiers, case_id
    seed = "OSRI-health-data-pilot-v1|" + case_id + suffix
    hashed = digest(seed.encode())
    index = int(hashed[:16], 16) % len(identifiers)
    assert identifiers[index] == selected, (case_id, suffix, selected, identifiers[index])
    return {"seed_text": seed, "sha256": hashed, "sorted_ids": identifiers,
            "index": index, "selected": selected}


def build():
    artifacts, entries = {}, []
    for n in range(1, 9):
        case_id = f"PILOT-{n:02}"
        path = PILOT / "cases" / (case_id + ".json")
        raw = path.read_bytes()
        d = json.loads(raw)
        assert d["case_id"] == case_id
        example = None
        if n <= 2:
            revision = d["revision"]["commit"]
            repo = d["repository"]
            w = d["workflow_selection"]
            selection = draw(case_id, w["sorted_workflow_ids"], w["selected_workflow"])
            task = {k: v for k, v in d["selected_task"].items()
                    if k in {"scope", "command", "commands", "parameters", "output",
                             "source_checkout_commands", "command_working_directory"}}
            install, docs = d["runtime"], d["documentation"]
            if n == 2:
                e = d["selected_task"]["example_selection"]
                example = draw(case_id, e["sorted_identifiers"], e["selected_identifier"], "|example")
        elif n <= 4:
            revision = d["software_selection"]["ref"]
            repo = d["software_selection"]["revision_url"].split("/tree/")[0]
            w = d["workflow_selection"]
            selection = draw(case_id, w["sorted_qualifying_workflows"], w["selected"])
            task = {k: v for k, v in d["task"].items()
                    if k in {"entrypoint", "parameters", "scope"}}
            install = d["installation"]
            docs = [d["task"]["example_source"], d["installation"]["source"]]
        elif n <= 6:
            revision, repo = d["software_revision"]["commit"], d["repository"]
            selection = draw(case_id, sorted(x["id"] for x in d["workflow_inventory"]), d["selected_workflow"])
            task = {k: v for k, v in d["task"].items() if k != "basis"}
            install, docs = d["runtime"], d["documentation"]
            if n == 5:
                e = d["example_selection"]
                example = draw(case_id, e["sorted_equal_rank_ids"], e["selected_id"], "|example")
        else:
            revision, repo = d["revision"]["commit"], d["canonical_repository"]
            w = d["workflow_enumeration"]
            selection = draw(case_id, w["sorted"], w["selected"])
            task = {k: v for k, v in d["task"].items()
                    if k in {"description", "command", "source_release"}}
            install = {"requirements": d["runtime_and_dependencies"],
                       "conditional_pinned_install": d["conditional_pinned_install"]}
            docs = [d["task"]["documentation"]] + d["implementation_evidence"]
            if n == 7:
                identifiers = w["documented_examples_sorted"]
                # The selected example appears verbatim after the R assignment.
                matches = [value for value in identifiers if value in d["task"]["command"]]
                assert len(matches) == 1, matches
                example = draw(case_id, identifiers, matches[0], "|example")
        assert re.fullmatch(r"[0-9a-f]{40}", revision), case_id
        packet = {
            "schema_version": "draft-1", "case_id": case_id,
            "status": "draft_pending_qualification_and_lock", "system": d["system"],
            "repository": repo, "source_commit": revision,
            "workflow": selection["selected"], "task": task,
            "setup": install, "permitted_public_documentation": docs,
            "rules": "../selection-rules.md; coordinator-managed implementation; technical qualification and lock remain pending",
            "output_capture": "Preserve native files or returned objects, commands and logs; no reference feedback before output lock.",
            "runtime_freeze": "Not performed: model, tools, environment and dependency manifest must be locked before execution."
        }
        content = encoded(packet)
        packet_path = f"execution/{case_id}.json"
        artifacts[PILOT / packet_path] = content
        entries.append({"case_id": case_id, "system": d["system"],
                        "primary_source_family": FAMILIES[n-1],
                        "source_commit": revision, "workflow_selection": selection,
                        "example_selection": example, "record": f"cases/{case_id}.json",
                        "record_sha256": digest(raw), "execution_packet": packet_path,
                        "execution_packet_sha256": digest(content),
                        "assessment_design": "assessment-design.md",
                        "actual_reference_status": "not_prepared",
                        "attempt_status": "not_started"})
    artifacts[PILOT / "manifest.json"] = encoded({
        "schema_version": "draft-1", "status": "proposed_not_locked",
        "case_count": 8, "primary_source_family_count": len(set(FAMILIES)),
        "sampling": "Purposive systems; reproducible pseudorandom workflow/example choices. Not a probability sample.",
        "cases": entries})
    return artifacts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Check arithmetic and generated files without writing")
    args = parser.parse_args()
    artifacts = build()
    for path, content in artifacts.items():
        if args.check:
            assert path.exists() and path.read_bytes() == content, f"Stale or missing: {path}"
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
    print(f"PASS: 8 case selections, 3 tied-example selections, 7 primary source families, {len(artifacts)} draft artifacts")
    print("No workflow executed. Export selection is not an access-control or scientific validation test.")


if __name__ == "__main__":
    main()
