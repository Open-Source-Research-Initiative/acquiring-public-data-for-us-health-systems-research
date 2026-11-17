# Eight-case pilot prepared for feasibility work

17 November 2026. **Eight proposed cases and draft execution packets are prepared; no case has run.** Actual reference fixtures, dependency environments and executor qualification are not complete. The [delegation record](../../governance/protocol-decisions.md) assigns routine implementation to the coordinator and reserves major scientific review for Cole.

The systems were purposively selected from earlier reconnaissance to exercise different source programs, languages and documentation conditions. They are not a representative sample. Within systems, recorded workflow/example inventories and fixed hashes determine the proposed tasks. [Selection rules](selection-rules.md) explain the choices; the [manifest](manifest.json) records exact source commits, seeds, packet hashes and status.

| Case | Selected system and revision | Proposed native task | Main preparation issue |
|---|---|---|---|
| [01](cases/PILOT-01.json) | Sacarny HCRIS, `5a3d57c0` | Download script defaults, 1996–2024 and overlapping hospital forms. | Full scope may exceed caps; downloaded ZIPs are deleted by the script. |
| [02](cases/PILOT-02.json) | adesigns NPPES API, `v1.0.6`, `2b6a830d` | Documented single-number lookup `1234567890`. | Potentially empty/invalid example; static TLS peer-verification concern needs safety preflight. |
| [03](cases/PILOT-03.json) | CDCPLACES, `d35fe95a` | `get_places()` defaults: 2025 county release, all states and measures. | Source snapshot identity, full scope and dependencies remain to qualify. |
| [04](cases/PILOT-04.json) | cdcfluview, `v0.9.4`, `cc1791b7` | WHO/NREVSS national data, all available seasons. | Older endpoint and contemporaneous source comparability are untested. |
| [05](cases/PILOT-05.json) | COVIDcast Python, `v0.1.3`, `9f16cfc0` | State-level `fb-survey/smoothed_cli`, from 2020-05-01 through the metadata-derived latest date. | Legacy service and rolling revisions; historical observation dates do not identify a frozen release. |
| [06](cases/PILOT-06.json) | EPHTrackR, tag `v1.0.1`, `6893d31c` | Measure 99, state stratification, default available geography/time. | Tag and internal package version differ; measure metadata and access need qualification. |
| [07](cases/PILOT-07.json) | countyhealthR, `v0.1.5`, `48b940be` | Documented county-level premature-death measure, release 2024. | Filtered output can require downloading full source tables. |
| [08](cases/PILOT-08.json) | PricePortal, `8bae12af` | Build the CMS hospital list, then default NPPES organization lookup. | Required absolute path, mutable sources, fuzzy linkage and request-error ambiguity. This is not a price-file task. |

There are **seven primary source families**, not eight independent source samples: cases 02 and 08 share NPPES. Case 08 also needs the CMS hospital-list source. Eight distinct systems do not remove shared-source dependence.

The earlier countyhealthR and PricePortal inventories, and the earlier COVIDcast and countyhealthR example choices, remain in their case records as superseded proposals. Corrections were made before any outputs existed. No selected system was replaced because it appeared inconvenient.

## Prepared artifacts

- [Execution packets](execution/README.md): generated task-only drafts, with pinned source identity and permitted documentation.
- [Assessment design](assessment-design.md): independent source evidence, comparison grain, bounded sampling and interpretation for all eight cases; no actual expected values.
- [Preparation memos](preparation/): source evidence, limitations and superseded choices. These are assessor/coordinator material, not executor context.
- [Isolation plan](isolation-plan.md) and [probe evidence](../../evidence/isolation-probe.json): a child namespace can hide a test path, but the current agent retains host tools. **Executor qualification failed.**
- [Contribution assessment](../../research/contribution/ASSESSMENT.md): proceed as an empirical application of established methods; no first-study claim.

Rebuild the drafts with `python3 scripts/prepare_pilot_packets.py` from the repository root. `--check` validates selection arithmetic and freshness without rewriting. It never installs packages or executes the proposed commands. The generated files do not themselves enforce isolation.

## Before execution

Qualify a constrained executor and resource meters; resolve installation and transport concerns without source patches; freeze dependencies, documentation and actual tasks; prepare references privately and separately; then lock inputs and packet hashes. Missing reference evidence is retained as a limitation, not manufactured. Independent human review is required for the claimed independent adjudication and later main-study progression, not for continuing this preparation.

No pilot readiness or progression gate has passed. Existing criteria still require eight eligible selected cases, actual comparisons in at least three cases across two source families, the other reference/disposition thresholds, technical limits and independent human review.
