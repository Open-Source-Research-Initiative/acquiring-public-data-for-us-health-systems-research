# R execution bundles: frozen bytes and proposed commands

17 November 2026. The retained runtime archive and four case source archives are identified by the `r-03.json`, `r-04.json`, `r-06.json`, and `r-07.json` records beside this file. These are **provisional bundles, not qualified primary execution locks**. No package installation, R execution, or acquisition request occurred during their preparation. A separate guarded synthetic staging check extracted 38,316 entries, reported R 4.5.3, and cleaned its scratch; package loading and setup remain untested. Coordinator review and case-specific lock remain necessary before an attempt.

The archive is `externalruntime/r-staging/r-runtime.tar.gz` in the pilot runtime workspace, SHA-256 `96905b47a8268e07688a09ecf7a80f21f60241daeee1ddbf14eb2f5cc82f5e16`. It contains 36,553 regular files and 1,763 relative symlinks, no hardlinks or special entries, and no duplicate, absolute or lexically escaping paths. It comprises files attributed to installed conda packages plus the recursively inventoried required R libraries; it is not a validated minimal closure. A limited scan found no `.netrc`, `.Renviron`, `.Rprofile` or `*.key` file names. The PEM private-key marker occurred in public OpenSSL/libssh2 documentation and a library binary; a marker string alone does not identify a secret. Package ownership and other potential credential formats remain subject to review.

## Proposed guarded staging and environment

1. Verify the exact archive and case-source hashes against the case JSON outside the executor; reject any mismatch. Bring only reviewed source files into the guarded session. Do not reuse a mutable shared runtime directory.
2. Under the same case resource ledger, use the independently validated archive extractor to stage the runtime at `/work/runtime/r`, then alias `/workspace/cache/builderbob/medsci-runtime/20261111/r` to that scratch-backed tree. Extracted runtime, package library, temporary files, logs and outputs all count against the case disk limit. The alias must neither reveal nor bind the actual host cache. Mount the source archives read-only under `/inputs` after their hash and content checks. The staging implementation and alias passed one guarded synthetic R-version check; repeat qualification against the exact session configuration.
3. Use `RHOME=/workspace/cache/builderbob/medsci-runtime/20261111/r`; set `PATH="$RHOME/bin:/usr/bin:/bin"`, `R_LIBS_USER=/work/r-library`, `HOME=/home/builderbob`, `TMPDIR=/work`, and `LANG=C.UTF-8`. Preserve the guarded proxy and trust configuration; do not inject host environment or credentials. Create `/work/r-library` and `/work/output` inside the charged scratch. Check `"$RHOME/bin/Rscript" --version` and, in a separate logged command, load the explicitly needed installed packages; capture failures without changing versions. Inspect the dynamic library and trust behavior under the actual sandbox.
4. All commands below are proposed setup commands, using exact, locally retained source archives with `R CMD INSTALL` into `/work/r-library`, in the stated order. **This differs from the documented `devtools` or `remotes` GitHub installer.** The coordinator selected installation from the exact pinned archive as immutable-source environment configuration under the selection rules. It installs the runtime dependencies needed by the native task and does not claim to reproduce the documented GitHub installer. In particular PILOT-06 documents `dependencies=TRUE`; this configuration omits `Suggests`, including `testthat`, and does not claim that option ran. Neither installation route permits silently substituting a package, patching candidate code, or fetching dependencies from an unreviewed host.

All paths below refer to reviewed archives mounted read-only in `/inputs`, with hashes from the case JSON:

```sh
# 03: install retained prerequisites in order, then the selected case source.
"$RHOME/bin/R" CMD INSTALL -l "$R_LIBS_USER" /inputs/httr2_1.3.0.tar.gz
"$RHOME/bin/R" CMD INSTALL -l "$R_LIBS_USER" /inputs/yyjsonr_0.1.22.tar.gz
"$RHOME/bin/R" CMD INSTALL -l "$R_LIBS_USER" /inputs/tigris_2.3.0.tar.gz
"$RHOME/bin/R" CMD INSTALL -l "$R_LIBS_USER" /inputs/PILOT-03.tar.gz

# 04: install retained prerequisite, then selected case source.
"$RHOME/bin/R" CMD INSTALL -l "$R_LIBS_USER" /inputs/MMWRweek_0.1.3.tar.gz
"$RHOME/bin/R" CMD INSTALL -l "$R_LIBS_USER" /inputs/PILOT-04.tar.gz

# 06 and 07: selected case source, with setup difference recorded above.
"$RHOME/bin/R" CMD INSTALL -l "$R_LIBS_USER" /inputs/PILOT-06.tar.gz
"$RHOME/bin/R" CMD INSTALL -l "$R_LIBS_USER" /inputs/PILOT-07.tar.gz
```

Each case starts from a fresh session and runs only its own commands. Package loading and any build during install are code execution and must occur inside the guarded ledger, not in the preparer's host environment. Missing compiler, native library, version conflict, network prohibition or unsafe installation is a recorded typed setup outcome; do not retry with a different version or patch as primary.

## Proposed native calls and serialization

After its locked setup passes, run only the selected case's call below. `saveRDS` is coordinator-added output capture for the returned object; freeze this wrapper and disclose it before the attempt. The archive names and commands do not themselves authorize a case run.

```r
# 03
result <- CDCPLACES::get_places(geography="county", state=NULL, measure=NULL,
  county=NULL, release="2025", geometry=FALSE, cat=NULL, age_adjust=NULL)
saveRDS(result, "/work/output/result.rds")

# 04
result <- cdcfluview::who_nrevss(region="national", years=NULL)
saveRDS(result, "/work/output/result.rds")

# 06
library(EPHTrackR)
data_st <- get_data(measure=99, strat_level="ST")
saveRDS(data_st, "/work/output/result.rds")

# 07
library(countyhealthR)
county_data <- get_chrr_measure_data(geography="county", measure="premature death", release_year=2024)
saveRDS(county_data, "/work/output/result.rds")
```

Record exact stdout, stderr, exit status, resource use, source URLs and redirects, and preserve the returned artifact before any comparison. These proposed commands do not establish that an endpoint is available or the output is correct.

Static source inspection also shows that case 03 calls `curl::has_internet()` before querying and can return an invisible `NULL` when it reports no connectivity. The guard's proxy-only network may affect that check. Preserve the native behavior and investigate the actual probe route; an RDS containing `NULL` alone does not establish a valid empty publisher response.

A static numeric comparison of 293 declared version constraints against the selected installed and retained package versions found no failed or unknown comparisons. The record is `externalruntime/r-staging/version-constraints.json`; it does not establish native ABI compatibility, successful loading, or installation. The separately retained supplemental installer sources are not part of these case setups.

Static compiler inspection for case 03 found that `yyjsonr` 0.1.22 contains C sources and requests `-lz`; R's `Makeconf` selects the archived `x86_64-conda-linux-gnu-cc`, whose target, assembler, linker, `make`, GCC helpers, R headers, zlib, and conda sysroot headers and startup objects are present in the archive inventory. The sysroot `usr/lib` link resolves within the archived sysroot. This does not establish that compilation or linking works in the sandbox: the compiler's sysroot resolution, dynamic loader, tools and libraries must be verified by the guarded setup. Fortran flags also refer to an old conda build-artifact include path, but no Fortran source was found in `yyjsonr`; its significance for other packages is untested. The sandbox's lack of host `/usr/include` alone is not evidence that these archived conda headers are unavailable.
