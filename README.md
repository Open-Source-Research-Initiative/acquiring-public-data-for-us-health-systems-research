# Acquiring Public Data for U.S. Health-Systems Research

An OSRI feasibility study of software that acquires public U.S. health data and the evidence needed to verify its outputs.

**Human lead:** Cole Lyons / [@ajhcs](https://github.com/ajhcs). **State:** feasibility research in progress; main evaluation not approved. **Areas:** Healthcare, Informatics, Engineering. Research-directory ID: pending registration.

We ask whether publicly inspectable acquisition workflows obtain their intended source release or current snapshot, and whether selected source facts are preserved in their outputs. Execution, source verification, reproduction of previous outputs, and suitability for a research question are separate claims.

The initial scope covers non-patient-level public U.S. data, including provider/facility records, finances, prices, utilization, quality and population aggregates. Patient-level records are excluded. Portals, standards and validators are supporting resources rather than interchangeable acquisition systems.

## Current work

The lead authorized repository setup and feasibility research in November 2026. This covers contribution research, candidate/code inspection, protocol development, and preparation and technically qualified attempts for an exploratory eight-system pilot. It does not authorize the main evaluation or establish independent human scientific review.

Screening now proceeds through [open contributor issues](research/screening/README.md). Assigned model work and cross-checks finish before one consolidated packet goes to Cole for final PI review and sign-off. Routine screening decisions do not need intermediate human approval. Model agreement is not human review; runtime and isolation controls remain prerequisites for any separately authorized attempts.

- [Research log](research/README.md): completed work and evidence limits.
- [Research protocol](protocol.md): scope, selection rules, pilot progression and limits.
- [Admission record](governance/admission.md): authorized scope and human-review status.
- [Related-work research](research/related-work/): new empirical-overlap search and limitations.
- [Candidate reconnaissance](research/candidates/): source-linked implementation and revision checks.
- [Source ledger](sources.csv): historical proposal-research sources, with evidence limits.
- [Contributions](contributions.md): human responsibility, agent assistance and checks.
- [Data and sharing policy](data/README.md).

## Current research package

The [contribution assessment](research/contribution/ASSESSMENT.md) recommends an independent empirical evaluation using established methods. All eight selected workflows now have retained native-attempt records, including the interrupted case 01. The [pilot findings for review](research/pilot-findings/README.md) separate source-scope limitations, endpoint failures, proxy interference and unresolved verification. The main-study progression gate remains unmet.

Cases 02–08 used [hash-bound runtime plans](protocol/pilot/runtime/locked/) and a [qualified executor](evidence/executor/qualification-02-08.json) with 84 passing integrated tests. Each received one native invocation. [Case 01's findings and limitations](evidence/pilot/README.md) remain unchanged. Technical checks and agent assessments are not independent human scientific review.

## Next work

Cole authorized a [separate diagnostic amendment](protocol/pilot/diagnostic-06-07-amendment.md) for cases 06–07. The [original findings and review package](research/pilot-findings/README.md) remain preserved as recorded before those diagnostics. The [diagnostic findings for review](research/pilot-findings/diagnostics-06-07.md) report new tracing, qualification and results separately; available source records, returned-record agreement and full acquisition remain distinct claims.

The [first screening round](research/screening/README.md) rechecks 33 historical leads and logs a separate search for missed candidates. Contributors can take a batch or challenge a model draft. The [final PI review policy](governance/final-pi-review.md) makes Cole the sole required human reviewer, with a second reviewer optional at his request. The main evaluation remains unapproved, and the required workflow comparisons remain unmet.

## Standards and reuse

This feasibility project follows [OSRI-0.1.0 at commit 8c39a0a](https://github.com/Open-Source-Research-Initiative/osri/blob/8c39a0a36c0e962060659b1d51f666c367f9464a/governance/contribution-standards.md). The lead remains responsible for scientific decisions. Agent checks are not independent human reviews. USHSO motivated the work; team-authored workflows are excluded from the proposed primary evaluation.

Original text/data documentation uses CC BY 4.0 and original code uses MIT as specified in [LICENSE.md](LICENSE.md); third-party source and data terms remain separate. No patient records or secret credentials belong here. Publication of this feasibility repository is not peer review or acceptance of scientific conclusions.
