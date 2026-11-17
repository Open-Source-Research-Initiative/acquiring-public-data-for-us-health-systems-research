# Pilot selection and execution rules

17 November 2026. The coordinator applies these rules under the human lead's delegation of routine feasibility decisions. They do not establish a completed packet lock or technical qualification. The historical candidate record is unchanged. Corrections to draft workflow/example inventories are retained in the case records; none followed an execution outcome.

## Systems and source families

Use eight purposively chosen, provisionally eligible systems to exercise different acquisition mechanisms and documentation conditions. Record previous code inspection. Do not call the pilot a random software sample, a representative survey, or a power calculation. The main evaluation, if separately approved, must exclude these pilot systems.

Count source families by upstream data program, not repository, programming language, endpoint or hosting platform. CDC PLACES, FluView and Environmental Public Health Tracking are different programs; Zenodo is hosting for County Health Rankings. NPPES is one shared family for PILOT-02 and PILOT-08. The latter also depends on CMS Hospital General Information. Do not inflate the count by treating dependencies as additional cases.

## Software and documentation

The proposal adopts a **GitHub-source-first observation frame** for this pilot. Within the selected component, use the latest stable semantic-version tag by the observation cutoff; use component-specific tags in a monorepo, not an unrelated package release. If no ordered stable tags exist, use the latest publisher-designated non-prerelease release; otherwise the observed default-branch commit. Record ambiguity for non-semantic or undocumented tags before lock. Preserve exact commit, tag and observation date. A package's internal version string does not override the recorded source identity.

Use revision-matched documentation. Registry releases such as CRAN are alternate distributions, not silent substitutes for the source revision. A material contradiction in release ordering or identity requires correction before lock. Pagination, API rate limits and unavailable dates remain explicit evidence limits; an observed tag is not proof of its complete historical release chronology.

**Coordinator implementation rule:** allow immutable checkout and install references as environment configuration. They must identify the selected source, change no source logic, and retain the package lock or installed dependency manifest. A package-manager installation must resolve to the selected source commit or stop with a mismatch. Dependencies are not yet frozen; resolve and record them in isolated setup before health-data acquisition. Record setup failure as a disposition, not permission to upgrade the selected system.

## Workflows and tasks

Include implemented external retrieval of substantive non-patient health observations, provider/facility information or health-system financial information. Exclude metadata-only helpers, generic standalone demographics, URL-discovery-only routines and offline parsers from the primary workflow draw. Collapse functions or scripts that share the same acquisition mechanism and source and differ only by geography, measure or other filtering. Distinct upstream acquisition steps may remain distinct even when one depends on another. A selected workflow includes its documented necessary prerequisites; an empty disposable cache must not silently substitute historical team data.

Sort stable workflow identifiers before selection. For this exploratory pilot, set the seed text to `OSRI-health-data-pilot-v1|PILOT-XX`; take the first 16 hexadecimal characters of its SHA-256 as an integer and take the remainder modulo the workflow count. This is a reproducible pseudorandom selection convention, not a probability-sampling claim. An inventory correction requires recalculation before lock and a preserved superseded record.

Use a complete documented default invocation when one exists, including its native scope. Otherwise use a uniquely designated basic/quickstart example. If several equally ranked examples exist, enumerate them, sort stable identifiers and use the same convention with the additional suffix `|example`. Advanced demonstrations do not outrank a designated basic example. Document the inspected example corpus and ranking rationale. Retain an inconvenient, large or possibly empty native task. Do not choose an easier release, geographic slice or known-positive identifier using reference or runtime results.

## Fixed attempt conditions

Use the original proposed per-case limits: three active executor hours, six elapsed hours, four VM-hours, at most four vCPUs, 16 GiB RAM, 100 GiB disk and 20 GiB transferred data. Software setup, primary execution and independent reference capture consume the same case meters; distinguish their contributions in reporting.

Preserve the first outcome. Permit either one justified transient retry or one later diagnostic repeat, not both; the repeat stays within the same caps. No code patches, alternate provider, hidden troubleshooting, maintainer contact or protected data. A compatible workspace-backed path inside the isolated environment may satisfy a documented absolute path without a source patch; it does not authorize host writes to `/data0` or new system mounts/services.

Task-specific outputs must be retained in an original native format, with a documented lossless serialization only where needed to inspect an in-memory return value. Output capture must not change request parameters or feed back assessment results. Lock commands, environment, outputs and logs before assessment disclosure. A capture failure is a recording limitation, not automatically a software failure.

## Lock still required

Before an attempt: confirm eligibility and software identity; apply and document the global configuration/task rules; freeze dependencies and permitted documentation; select the executor model/tools; qualify the executor boundary and resource controls; prepare an independent source reference or document its absence; set source observation windows and lock both packets with hashes. The coordinator may resolve routine documented details, but cannot invent a completed reference, reviewer, runtime qualification or human decision.
