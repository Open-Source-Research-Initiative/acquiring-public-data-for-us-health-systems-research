# R cases: runtime preparation, not a lock

17 November 2026. This is static preparation for PILOT-03, 04, 06 and 07. No candidate code, package build, installation or health-data request was executed. GPT-6 inspected the pinned candidate `DESCRIPTION` files, existing runtime package descriptions and public CRAN source metadata; independent review remains pending. Package compatibility, safe execution and protocol gates remain open.

## Existing runtime

The existing workspace environment `/workspace/cache/builderbob/medsci-runtime/20261111/r` contains an Rscript executable; a separate local check reported R 4.5.3. This is a shared MedSci runtime, not an immutable pilot environment. Its approximately 2.8 GiB tree contains 1,766 symlinks. Its `bin/R` records the absolute `R_HOME_DIR=/workspace/cache/builderbob/medsci-runtime/20261111/r/lib/R`; relocating the files without preserving that path is therefore unqualified. The initial PATH and limited-depth workspace search did not locate this environment; the subsequent direct inspection supersedes that search. No change was made to it.

Recursive inspection of installed `DESCRIPTION` `Depends`, `Imports` and `LinkingTo` fields, starting with the current source-index closures, found:

| Case | Installed metadata gaps | Limit |
| --- | --- | --- |
| 03 | `httr2`, `tigris`, `yyjsonr` | Their own dependency versions and compiled `yyjsonr` must be qualified. |
| 04 | `MMWRweek` | Runtime and native dependency load remain untested. |
| 06 | None found by this metadata traversal | Candidate package itself is not installed or tested. |
| 07 | None found by this metadata traversal | Candidate package itself is not installed or tested. |

This is a package-name inventory, not a solver: version constraints, optional and system requirements, architecture, ABI, package startup code, compiled shared-library dependencies and actual loading have not been checked. Current-index transitive closure and installed versions are recorded in `planning/health-data-pilot-runtime/externalruntime/r-staging/cran-source-metadata.json` under the OSRI workspace. Do not treat the prospective current CRAN versions as an installed lock. `Suggests` packages are excluded from this dependency walk even though a documented `dependencies=TRUE` installation could include them; resolve this difference prospectively rather than silently changing the procedure.

## Frozen-source preparation

The current CRAN index yielded 52 non-base dependency names across the four cases. The metadata file records version, source URL, SHA-256, size and declared dependency fields for each fetched tarball, plus the index hash; the tarballs were streamed for hashing and checked against the index MD5. Four missing-package archives have been retained in `externalruntime/r-staging/sources`, without executing their contents:

| Package | Version | SHA-256 |
| --- | --- | --- |
| httr2 | 1.3.0 | `031990311482479da4bb910369606c73bb2b2456b8b8c1ab877ad8fbb0703c75` |
| tigris | 2.3.0 | `721527dd4a6de1263eeb53c2d57d09b8296d33aed5a636ee8cd7ad2c3e009db8` |
| yyjsonr | 0.1.22 | `ca2c68e0c1589e536bb76aac8235a75d90bde82e32e3367a321a12731fa48b8e` |
| MMWRweek | 0.1.3 | `1aa8b687dc3340c3f277689eb0ca529e0064a4a3a66868137f2f8ab209d133d0` |

The other source tarballs were not retained and may disappear or change location; hashes alone do not provide an installable dependency closure. Preserve exact bytes for every selected source and record license, provenance, runtime/toolchain, and compatible versions before freezing. Compare installed package versions against all version constraints and inspect native shared-library closure. Packages compiled against a different library set are not qualified merely because their `DESCRIPTION` files exist. The system PATH has gcc, g++ and make; this inspection did not find gfortran, cmake or pkg-config on PATH, so a source-build strategy cannot be assumed available.

## Proposed mount design

Create a separate, reviewed, immutable snapshot under workspace; do not mutate the shared environment. The existing sandbox input auditor rejects symlinks and files with multiple hard links, so a plain recursive copy or direct mount of this tree will fail. A future preparation step may materialize a snapshot with independently copied regular files and dereferenced links only after checking each resolved link stays within the approved source tree, detects cycles and rejects dangling or escaping targets. Re-audit every copied entry and hash the snapshot; assess size and licensing. Native code and libraries must be included from an inspected allowlist, with compatible loader and libraries. Materialization may change link semantics, so run separate synthetic R and package-load checks against the exact snapshot and retain failures; never infer correctness from a file manifest alone.

For a first compatibility test, place that snapshot at an arbitrary host workspace path and mount it read-only inside the sandbox at the **original absolute prefix** recorded in `bin/R`; host storage is relocatable, but the in-sandbox prefix is fixed. Check Rscript's compiled path, dynamic loader/RPATH, certificate and locale paths, and any references to the original host environment. A genuinely different in-sandbox prefix requires an independently qualified relocation method, not an unrecorded script or binary patch. Configure a private, scratch-backed writable library for narrowly permitted package installation, and do not expose the image, host cache or reference materials. A read-only base package library and a separately fixed case library must be mounted without bypassing the quota or the sandbox auditor. Ensure the documented installation method and pin, proxy trust, dependencies and output capture are frozen before any case attempt.

These are preparation options, not evidence that the snapshot exists or that package build, candidate execution, egress or isolation is ready. Preserve the already selected cases if a dependency is unavailable and record a typed blocked outcome under the protocol.
