# Screening round 1: final PI review packet

**Version:** seed-screen-2026-11-17-v1. **Status:** assigned model work complete; PI review and sign-off pending. **PI:** Cole Lyons. This packet covers the fixed 33-lead screening round, its separate four-query gap search and the revised review process. It does not claim that the entire study or a main evaluation is complete.

**Recommendation:** accept this as a bounded exploratory screening record, retain the five unresolved cases, and continue evidence development through the open issues. Keep main-study execution withheld. The current evidence does not supply the required completed workflow comparisons or a finalized ten-system nonpilot, non-team frame.

## What is ready for review

The [tracker (#5)](https://github.com/Open-Source-Research-Initiative/acquiring-public-data-for-us-health-systems-research/issues/5) links four domain batches, the cross-check, gap search and this packet. [Issue #13](https://github.com/Open-Source-Research-Initiative/acquiring-public-data-for-us-health-systems-research/issues/13) is an unassigned follow-up contributor batch for the three new search leads, outside this round's fixed denominator. All issues remain open for contributor evidence and corrections; model completion is not scientific acceptance or a claim that a volunteer contributed.

The [contract](CONTRACT.md), [manifest](manifest.json), [model-work register](model-work.json), [decision ledger](decisions.csv), [reconciliation](reconciliation.json), and [validation](validation.json) identify the completed work. The [packet index](packet-index.json) binds the supporting artifact bytes. Each review must name the actual reviewed commit or packet version; no sign-off is prefilled below.

## Results and denominators

| Final model-adjudicated disposition | Lead count | Interpretation |
|---|---:|---|
| Eligible | 14 | Inspectable implemented in-scope acquisition leads; eligibility is not verified acquisition. |
| Companion | 10 | Supporting portals, documentation, methods or local-file tools. |
| Excluded | 4 | P20/P21 outside U.S. scope; P26/P27 individual survey microdata. |
| Unresolved | 5 | P04, P09, P17, P31, P33; reasons below. |
| Total fixed seed | 33 | Historical leads, not a probability sample or internet census. |

The 14 eligible leads map to 14 provisional implementation groups under the recorded canonical keys. Eight are the existing pilot systems and cannot enter a later primary sample. The remaining six are P05, P12, P13, P14, P24 and P25. Research-team affiliation is unverified; P05's fork lineage and other code/source relationships need further attention. These are six potential nonpilot leads, **not six finalized eligible non-team systems**. Common source families do not make two implementations duplicates; forks and parent repositories do not create additional systems merely by having separate URLs.

First-pass agents classified 16 leads eligible. REVIEW-B proposed holding P17 unresolved. Coordinator consistency review also held P04 unresolved because it presents the same coupled application/data-publication question. Initial classifications and reviewer positions remain preserved. Reviews were not blinded: agents could see historical decisions and exchanged evidence. Do not interpret agreement as independent-human validation or compute an independent inter-rater reliability statistic from it.

## Unresolved evidence and method choices

- **P04 and P17 — system boundary:** both viewers fetch separately published data from associated repositories. Shared ownership and a graphical interface are not exclusion criteria; publisher-authored clients can be eligible. The unresolved question is whether the data publication is an external release consumed by the evaluated client or an internal output of the coupled system being counted. [Boundary adjudication](boundary-adjudication.json) retains both interpretations. Recommendation: keep both unresolved until the same explicit unit rule is applied, rather than including one and excluding the other.
- **P09 — public-source scope:** an implemented provider-index request exists, but public publication/access and U.S. scope are not established. It is not safely classified as documentation-only or eligible from the current evidence.
- **P31 — inaccessible implementation:** fresh repository access returned 404. This does not prove the historical code never existed or that an eligible workflow failed.
- **P33 — placeholder endpoint:** request code is present, but a real source URL and actual acquisition path remain unestablished.

These are recorded terminal screening dispositions for this round, not completed answers to the underlying scientific questions. The PI can accept the record with unresolved cases, request revision, or stop. Routine source checks did not require intermediate PI approvals.

## Separate gap search

The [prospective search plan](gap-search-plan.json) fixed four GitHub repository queries, stars-descending order, one page and five-result cap per query. [Results](gap-search.json) record returned counts of 1, 1, 0 and 1. Three new leads are unscreened: `nfisher20/nppes-scrape`, `jfangmeier/hcris-cost-reports` and `mirador/brfss`. Exact repository-name checks found no seed/pilot match; they do not establish independent lineage or eligibility. The BRFSS lead particularly needs a microdata-versus-aggregate check.

These narrow repository queries are not a comprehensive literature or code search. No query used `in:readme`; selected README resources were fetched afterward. The original plan's wording overstated README search coverage; the result record preserves the correction without changing the executed queries. Zero returned results for one query do not establish absence of relevant software. The new leads do not alter the 33-lead denominator or supply the ten-system progression threshold.

## Relation to the completed pilot

The [original pilot findings](../../pilot-findings/README.md) and [separate diagnostics](../../pilot-findings/diagnostics-06-07.md) remain unchanged. Cookie-policy interference is established for the controlled request probes; the earlier untraced failures remain more limited. Case 06's diagnostic exposed a list/left_join error and produced no data object. Case 07 produced a 3,143-row table, but no independent source-row fidelity or completeness comparison. Case 03 remains the one workflow with bounded partial returned-row comparison; three checked rows are not three workflows.

Changing the human review sequence does not satisfy the missing reference-comparison conditions. The [current protocol](../../../protocol.md) requires the substantive evidence thresholds and explicit PI authorization for progression. A second human reviewer is optional at Cole's request; neither model checks nor PI sign-off should be reported as an independent-human review that did not occur.

## Checks and assistance

All eight assigned GPT-6.1 Terra agents completed their bounded deliverables, including follow-up boundary checks. The coordinator reconciled records and checked the supplied evidence. [Structural validation](validation.json) verifies the unchanged seed hash, exact 33-ID coverage across four batches and two review files, evidence fields, classification consistency and reconciliation. These checks do not verify source truth or eligibility automatically. Source access failures and unavailable affiliation/lineage evidence remain explicit. No candidate workflow, package installation or health-payload collection occurred during screening.

The code, screening and governance changes are prepared in the draft PR. Merge, main-study execution and scientific release are not implied by packet readiness. Contributor corrections may produce a new version; retain this version and its decision history.

## PI decision — not yet recorded

- **Decision:** Accept this bounded record / Revise / Stop
- **Reviewed commit or packet version:**
- **Review date:**
- **Accepted claims and remaining limitations:**
- **Required revisions, including the P04/P17 unit rule if any:**
- **Authorized next scope:**
- **Main-study execution authorization, only if separately explicit and evidence conditions met:**
- **Independent human review actually performed, if any:**
- **PI sign-off:** Cole Lyons
