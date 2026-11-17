# Eight-case feasibility pilot: findings for review

17 November 2026 UTC. Cases 02–08 each received one native invocation after their runtime locks and technical checks. Case 01's original harness-interrupted attempt, subsequent source observation and limitations remain preserved. No selected case was replaced, no candidate source was patched, and no native diagnostic repeat has occurred. The main evaluation remains unapproved.

The strongest research finding is a gap between returned-record agreement and acquisition scope. CDCPLACES returned 1,000 rows; three source-selected rows agreed on the available checked fields, while a later count of the same dataset reported 229,298 rows. The pinned client issues an unpaginated query, and the [publisher's API documentation](https://dev.socrata.com/docs/queries/limit.html) specifies a default limit of 1,000. These observations support a substantial scope limitation. They do not establish the exact source population during the earlier invocation or verify a complete release.

The pilot also exposed measurement interference. The inspecting proxy blocked requests during cases 06 and 07. Later independent requests to the corresponding metadata endpoints succeeded. Those original failures therefore remain controlled-environment barriers with unresolved candidate correctness. The exact rejected request property was not retained; anonymous session cookies are a hypothesis, not an established explanation.

## Case dispositions

| Case | Observed native outcome | What the evidence supports |
|---|---|---|
| [01 HCRIS](../../evidence/pilot/README.md) | Coordinator interrupted the run for a metering bottleneck. | Later archive filenames are inconsistent in case with the script selectors; earlier downloaded bytes were deleted, so exact input identity remains unknown. Timing includes disclosed synthetic-probe overlap. |
| [02 NPPES client](PILOT-02.md) | Exit 0, `NULL`. | Independent bracketing queries returned zero results. The native response was not retained; no verified-empty or row-fidelity claim. |
| [03 CDCPLACES](PILOT-03.md) | Exit 0, 1,000-row object. | Three conditional partial row agreements; footnote preservation unresolved. Later source count 229,298 and the unpaginated query support a scope limitation. |
| [04 cdcfluview](PILOT-04.md) | Exit 1 at initialization URL, HTTP 404. | Independent observations corroborate 404 at that selected endpoint in this window; no acquired result. |
| [05 COVIDcast](PILOT-05.md) | Exit 1 at the composed legacy metadata URL, HTTP 404. | Endpoint/dependency compatibility is unresolved. The separately denied PyPI version check is not the metadata failure. |
| [06 EPHTrackR](PILOT-06.md) | Exit 1 parsing metadata; broker policy blocked a native-host request. | Later anonymous geographic-types request returned JSON successfully. The blocked primary cannot establish publisher unavailability or candidate failure under compatible transport. |
| [07 countyhealthR](PILOT-07.md) | Exit 1 downloading 2025 metadata for the selected 2024 data task; three built-in attempts. | Three proxy policy blocks, one coordinator invocation. A later independent request to the exact metadata-file URL succeeded; no candidate result was available to compare. |
| [08 PricePortal](PILOT-08.md) | Exit 1 at the hospital-list prerequisite, HTTP 404. | NPPES lookup did not run. This is a prerequisite failure, with matching independent 404 observations. |

These are purposively selected cases, not an estimated success rate for healthcare acquisition software. Cases 02 and 08 share NPPES as the intended primary source family; case 08 never reached it. Three compared rows in case 03 are one workflow comparison, not three assessable cases. No full verified acquisition or independent qualified human adjudication is claimed.

## Decisions for Cole's review

1. **Review the scope finding and failure attributions.** The proposed scientific claim is that returned-record agreement can coexist with a substantial retrieval-scope gap, and that evaluator restrictions can create acquisition failures. This pilot supports bounded examples, not population prevalence or a general software ranking.
2. **Review a prospective diagnostic-method amendment before further native attempts.** I recommend explicit, bounded request/response provenance and specific broker rejection reasons, plus qualification against native multi-request behavior, including any publisher-issued anonymous session cookies. The rejected property in cases 06/07 must be established before changing policy. Any diagnostic repeat must remain separate from the original primary and within a declared observation window and resource budget. These changes are proposed, not applied to the recorded attempts.
3. **Retain the main-study gate.** Only case 03 currently supplies a bounded conditional source-to-output comparison, in one family, and human review is pending. The protocol requires at least three actual assessable workflow comparisons across two families and its other review/disposition conditions. Completing eight attempts does not satisfy that gate. Broader scraping and main evaluation should wait for the measurement and reference-design problems to be resolved.

## Evidence and validation

The [runtime qualification used for cases 02–08](../../evidence/executor/qualification-02-08.json) records 84 passing integrated tests. Earlier qualified code and failed setup configurations remain archived. [Setup corrections](../../evidence/executor/remaining-setup-notes.md) addressed missing sealed-runtime resources and an unsupported Composer flag before any native case 02/03 invocation. Shared ledgers retain conservative charges; all guarded primary sessions reported clean teardown. The controls are scoped engineering evidence, not a general security certification or independent human review.

[Public runtime receipts](../../evidence/pilot/README.md) contain artifact hashes and bounded execution metadata. Raw publisher payloads, assessment fixtures, model packets and traces remain in the controlled workspace. The [case 03 exporter and checker](../../scripts/pilot_assessment/) preserve the source-first selection and tested comparison procedure. An initial checker classification error for unavailable columns was retained and corrected without changing the selected rows, values or tolerance.

The contribution remains an independent empirical application of established methods. These results do not revive a first-study claim or justify a meta-analysis of repositories as if they were comparable effect-size studies.
