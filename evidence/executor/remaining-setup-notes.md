# Remaining-case runtime qualification and setup corrections

17 November 2026 UTC. These records describe coordinator preparation, not independent human review or candidate acquisition results.

The first remaining-case runtime passed 82 integrated tests and bound all seven case plans and execution packets. Its implementation and qualification are preserved in `snapshots/remaining-runtime-20261117-v1.tar.gz` and `qualification-02-08-v1.json`.

Case 02 stopped in offline Composer installation: PHP aborted before Composer emitted output. Four separately recorded, network-disabled setup diagnostics used the same case ledger. Even `php -n -v` failed; the final trace showed unsuccessful attempts to open `/usr/share/zoneinfo/` and `zone.tab` immediately before the abort. This isolates the failure to the sealed runtime before any NPPES client invocation; it does not by itself prove a defect in PHP or Composer.

Case 03 stopped in offline R setup. Loading the standard `utils` package failed when it called the compiled `Sys.which` implementation. That implementation names `/usr/bin/which`, whose host symlink leads through `/etc/alternatives/which`; the intermediate link was absent in the sealed root. No CDCPLACES task had run.

The second runtime adds only a read-only bind of the existing timezone directory and the missing `which` link, pointing to an executable already present in the read-only runtime. A separate hash manifest inventories the timezone directory; pre/post checks preserve the original case 01 runtime manifest. The revised runtime passed 84 integrated tests, including read-only resource access. Its snapshot and qualification are retained as version 2. Actual package setup and native acquisition remain separate outcomes.

Setup continuation preserves earlier locks, logs, outputs and the original SQLite ledger. It cannot continue after a native-start marker. Repeated input staging is conservatively debited again, and no resource charge is refunded. Case 01 was not re-executed or reclassified.

The 32 MiB control-file allowance is checked before coordinator writes, with reserved headroom for ledger/final records; it is not a separate filesystem quota. The 46 GiB retained-output allowance counts earlier setup histories, and the workload runs on its own 46 GiB quota image. Coordinator launches are serialized. These controls do not establish a general security certification.

Case 02 continuation confirmed that PHP and Composer could start after timezone data became available. Composer then rejected the coordinator-supplied `install --no-audit` flag. Removing that unsupported setup flag left the selected package revisions and native query unchanged. The previous script bytes remain retained locally. Qualification version 3 binds the corrected setup input and reuses the unchanged version 2 executor and its 84-test result; it does not claim a new test run. Offline installation then succeeded. Its warning about an unavailable Packagist filter feed is retained; package archives came from the locked local inputs.
