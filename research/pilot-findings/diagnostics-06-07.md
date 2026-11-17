# Separate diagnostics for cases 06–07

17 November 2026 UTC. Cole authorized improved tracing, correction of established proxy barriers and separately recorded diagnostic repeats. The [original eight-case findings](README.md) remain unchanged. The [prospective amendment](../../protocol/pilot/diagnostic-06-07-amendment.md), [locked plans](../../protocol/pilot/runtime/diagnostic/) and [qualification](../../evidence/executor/qualification-diagnostics-v1.json) define the new observation windows and controls. These are exploratory diagnostics, not replacement primary attempts or approval of the main study.

## Established transport mechanism

The [paired native R request-stack probes](../../evidence/executor/diagnostic-request-probes.json) reproduced a specific policy failure. In each sequence, the first request returned HTTP 200; the next request was rejected with `denied_header_cookie` under the default policy. With the narrowly scoped publisher-cookie option, all four requests returned HTTP 200. The second responses were 366 bytes for CDC geographic types and 6,139 bytes for the Zenodo factor file. The probe did not install either candidate package or invoke either complete workflow.

This establishes the mechanism in the controlled probes. The original broker did not record the rejected property, so the earlier failures remain consistent with this mechanism without being retrospectively proven cookie failures. Their original outcomes and limitations are preserved.

The cookie option remains disabled by default. Diagnostics permit only exact cookie pairs previously delivered by the same HTTPS host in that broker session. Authorization headers, arbitrary cookies and other host destinations remain denied. The broker's bounded store relies on the native client for expiry/path selection and retains previously issued values until teardown. No login or host credential is supplied; the cookie contents themselves are not independently classified as anonymous.

## Diagnostic outcomes

- [Case 06 EPHTrackR](PILOT-06-diagnostic.md): one invocation, exit 1, no saved data object. Ten native metadata responses returned HTTP 200 with no host-attributed policy denial. Execution then failed because `left_join` received a list. The independent API-help reference returned 404 before and after; no row-level comparison is available. No native data POST was observed.
- [Case 07 countyhealthR](PILOT-07-diagnostic.md): one invocation, exit 0, a 94,945-byte saved R object, and no host-attributed policy denial. The [confined offline assessment](../../evidence/pilot/PILOT-07-diagnostic-assessment.json) read a 3,143-row, seven-column table with character FIPS fields and numeric value, count and confidence-interval fields. Independent source-row fidelity and completeness remain unassessed.

## Major claims for Cole's review

1. **Evaluator policy can itself create an acquisition barrier.** The paired probes directly support this claim for the two tested request sequences. They do not estimate its prevalence or prove the exact cause of every original failure.
2. **Removing one barrier does not establish a working acquisition workflow.** Case 06 progressed beyond the proxy denial and exposed a separate R type-handling failure in this pinned configuration. This is a conditional observation, not a claim about all package versions or publisher states.
3. **Execution, returned output and source fidelity remain separate.** Metadata access and response hashes do not verify data rows, units, completeness or research suitability. The larger source-first comparison plans remain preparatory. No diagnostic is credited as a replacement primary or used to pass the main-study progression gate.

## Evidence limits and checks

The frozen executor passed 92 integrated tests with no failures or skips. Separate agents reviewed the changes; neither those reviews nor the tests constitute independent human scientific review or a security certification. The inspecting proxy validates publisher certificates, so these results cannot establish the candidates' own TLS verification behavior.

Traces identify request targets by hash and record bounded reasons, timing and correlated response status. Response hashes/counts cover fully forwarded raw HTTP chunks, including HTTP headers; they are not decoded payload digests. `upstream_eof` does not establish complete HTTP framing, and partial-send exceptions mark counts as lower bounds. Hostless incomplete-header events are not counted as publisher policy denials. Raw publisher payloads, model traces and private plans remain outside the repository.

The [preservation receipt](../../evidence/pilot/diagnostic-primary-preservation.json) checks all original attempt trees and inventoried original public findings. [Diagnostic accounting](../../evidence/pilot/diagnostic-accounting.json) separately records the new ledgers, post-lock assessment and guard teardown. No original ledger was reset.
