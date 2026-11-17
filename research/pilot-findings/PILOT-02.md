# PILOT-02: NPPES API client, exploratory assessment

**Disposition:** Native command finished with exit code 0 and printed `NULL`; verified acquisition and same-input fidelity are **unresolved**, with no verified empty result. No output artifact or candidate response body was retained. This is an exploratory agent assessment awaiting independent qualified human review; major scientific claims require coordinator and lead review. It does not establish a defect, an incorrect result, or research fitness.

The selected documented example invokes `searchByNumber(1234567890)` in `adesigns/nppes-api` v1.0.6, commit `2b6a830d608885dd3a814952fbf18575431b5cf5` ([case record](../../protocol/pilot/cases/PILOT-02.json)). The frozen source code supplies limit 1 and API version 2.1 and returns null when the mapped result count is false; errors with a non-200 HTTP status throw an exception. That code path is consistent with an empty response, but the output alone does not establish the response received, its HTTP status, or the cause of `NULL`. The broker records a connection to the allowed host among other events, but the retained events do not identify the candidate's exact query, response or input bytes. They cannot establish same-input comparability.

## Reference and comparison

Independently captured observations requested `https://npiregistry.cms.hhs.gov/api/?number=1234567890&limit=1&version=2.1` on 17 November 2026, at 02:35:15.325–15.838 UTC and 02:35:26.226–26.564 UTC. Each recorded HTTP 200 and JSON with integer result count zero and an empty results array. The primary command began at 02:35:21.373 and its output was locked at 02:35:26.022 UTC, before the second observation. Both retained bodies have the same SHA-256, but this equality cannot rule out an intervening source change or prove that the candidate acquired those bytes. The observed endpoint is a current snapshot without a retained immutable revision. A digest identifies retained bytes; it does not prove publisher truth or completeness.

Before inspecting the native output or command log, the assessor fixed the source identity, query, available strata and comparison rule in the private plan identified below. The reference contains no source rows: general, boundary, missing-value and duplicate strata each yielded zero selectable units. Zero units were selected or compared; unmatched and unknown row counts are not applicable because no row comparison was possible. Query-result comparison remains unknown because the candidate's response is not retained. No separately authored checker or mutation controls were run; no actual assessable workflow-output comparison is claimed. No comparable author output was supplied, so reproduction is not assessable.

## Setup and native execution

Two setup attempts failed before the primary native command: the first Composer invocation aborted with a buffer-overflow diagnostic; the second rejected the unsupported `--no-audit` option. The corrected offline setup subsequently installed the locked dependencies and completed. These are study setup events, not native candidate outcomes; they are retained as setup history rather than counted as candidate executions. The locked primary command ran once, exit 0, stdout `NULL`, empty stderr, with no retry recorded. No raw provider payload is included in this report.

The controlled HTTPS baseline governs the study network environment; it does not establish that the candidate itself verifies TLS peers safely. Static inspection of the pinned client shows an integer cast compared strictly with boolean `true` for `CURLOPT_SSL_VERIFYPEER`, a concern distinct from the observed acquisition result. This was not independently tested here.

## Evidence and custody

Private runtime evidence is retained under `planning/health-data-pilot-runtime/attempts/PILOT-02-primary-20261117` in the OSRI workspace; it is not a public payload. SHA-256 values below identify exact retained files:

| Evidence | SHA-256 |
|---|---|
| Reference-first private assessment plan | `0fc5a3fd1ce9d93a627a8ecdfb3ad02b4b70a76dae996f9f53b7cf8fd057efae` |
| `reference-before.json` | `2c429b8521510caf26a9ef24d4c84f40c742e323c045c084cd9094d1c2d5f884` |
| `reference-after.json` | `9801343efaaf0a498d052d5aa1ae19abf4e82d04d1f94dc81f91b27e99cf0324` |
| Each reference body | `d1d2693d18cee969861c1a7dc0b4023108b4a7567745f4a875ed0f8b0d8973ee` |
| Before / after headers | `09d6d25538b945faa7393b821fc1c8466e795e259ac86a33bdbea6d821d7fc38` / `496da042e80481035ec2b48eb7ce389b97cc01468440780d2f4a8562297a55ac` |
| `primary.json` | `56eb2259c6b3b45ca671e395800c2a8b4fc4fe22c479a3c029d434a90a431fbe` |
| `command-log.json` | `885cf9ce998fbdfba2969fdb9615377632a5fec2a2962736e11e8ea613341fe9` |
| Native stdout / stderr | `21726c10dcf9e11a1bc65ffab39bb4df9a068d87d16f1946d8f54d44860395a5` / `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| Setup logs, first / second / corrected | `3b6cc5fb7796cf370d69ba6ffd0e3607924851def09dc2087d61813e6a169ccf` / `39fed58ce321768dbabde73f91d66f863b8c073e97fac8810a1c8218123b10e6` / `d433711cd4c5cf2285609dea6ce28007287fc76995463166ed8108dbb1bffd26` |
| Frozen source archive | `0c51e7dc79f3e801a8cfeacdcf27193b1e0fcf88744f858cf3af77d263c91520` |

Codex assessed the preserved records and inspected the frozen source without requests or candidate execution in this assessment. The reference-first plan was recorded before output inspection; filesystem timestamps alone do not prove access separation. Human review of evidence, custody, and classification remains pending.
