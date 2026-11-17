# Experimental pilot executor

This Linux-only harness separates candidate commands from source-reference material and supervises a model-directed action loop. It is study infrastructure, not a general-purpose hardened sandbox. Read the [conditions](../protocol/pilot/executor-conditions.md), [current qualification receipt](../evidence/executor/qualification.json), and [case observations](../evidence/pilot/README.md) before use.

The trusted coordinator owns native model authentication, source packets, private reference storage and output custody. Candidate processes run in unprivileged user, mount, PID and network namespaces with dropped capabilities and no native host mounts. An allowlisted HTTP/HTTPS broker supplies the only network path. A bounded ext4 image mounted through user-mode FUSE holds writable files; separate executor/reference directories are never mounted together. A shared durable ledger covers both phases. Model actions are structured proposals interpreted by the coordinator; native tool dispatch is disabled and tested separately.

The implementation requires the already available user-namespace, transient user-systemd-scope and FUSE capabilities. The workspace-local `fuse2fs` and libfuse package identities are recorded in the quota evidence. No persistent service, new identity or privileged package installation is provided by this repository. Quota tests require an explicit `PILOT_FUSE_RUNTIME` directory pointing to those extracted packages. Otherwise they skip; a skipped quota test cannot qualify a case.

Run the synthetic suite from the repository root:

```sh
PILOT_FUSE_RUNTIME=/workspace/path/to/extracted-fuse-runtime python3 -m unittest discover -s tests/executor -v
python3 scripts/check_records.py
python3 scripts/prepare_pilot_packets.py --check
```

`CaseSession` composes input snapshots, separate writable trees, the proxy and ledger. `run_guarded` bounds the complete coordinator and recovers only its recorded resources. Use its exact `PILOT_SESSION_ROOT` contract; blocked recovery preserves evidence. `lock_outputs` rejects unsafe links and bounds retained bytes, file count and path length. Pass remaining totals across output collections rather than resetting allowances.

Qualification is a reviewed, hash-bound record, not an automatic consequence of a test count or caller flag. `executor.pilot` refuses stale or out-of-scope receipts and preserves one primary invocation. The current receipt permits only the recorded post-lock reference capture and synthetic work; it does not authorize another case-01 primary. Runtime locks for cases 02–08 remain incomplete. Do not create a new directory to bypass the case history, reset its ledger, label a diagnostic as primary, or reinterpret this software as scientific approval.

Original case-01 source and its then-current qualification are preserved in the [runtime archive](../evidence/executor/snapshots/PILOT-01-primary-runtime.tar.gz). Current code uses prepaid durable transfer credits after the first pilot exposed per-chunk database overhead. Unused credit remains charged; expired, finished, abandoned and reopened reservations cannot authorize further traffic. Confirmed application bytes and reserved bytes are different measures. Their relationship and the lower-layer exclusions must remain explicit in reports.
