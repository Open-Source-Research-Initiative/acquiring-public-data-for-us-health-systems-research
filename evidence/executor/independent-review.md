# Independent synthetic executor boundary review

Historical first review, 17 November 2026. Its CONNECT finding was corrected and the regression test now requires denial. A follow-up review attempt failed hardware-key authentication and produced no follow-up review. Later coordinator/implementation-agent checks are recorded separately in [qualification](qualification.json); none is independent human review.

Original record: 17 November 2026. Reviewer: separate Codex agent. This is an implementation review, not human review or a security certification. No real reference values, credentials, candidate code, data sources, or production systems were used.

**Disposition: not qualified for the proposed agent-assisted pilot.** The allowed HTTPS CONNECT tunnel forwards opaque traffic; a synthetic endpoint received a request naming `forbidden.example` through a tunnel authorized for `allowed.example`. The test uses a test-only DNS resolver and loopback server and demonstrates proxy behavior, not a real external service. On a shared destination this permits virtual-host/domain-fronting routing outside a domain allowlist. A destination-IP restriction is not a domain restriction. Resolve or explicitly redesign and prospectively assess the network policy before relying on it.

The namespace runner explicitly does not implement CPU, memory, disk, or network quotas, and captures unbounded output in host memory. A timeout alone does not fulfill the protocol's resource ceilings. The model runtime and its tool routing have not been demonstrated here; a shell child boundary does not constrain independent host tools, browser, other agents, or model-side access. These are prerequisites, not claims that those routes were successfully exploited.

## Observations

- `python3 -m unittest discover -s tests/executor -p test_boundary_adversarial.py -v`: 2 tests passed. The CONNECT test deliberately asserts the undesired behavior; a passing test confirms the policy bypass. The other test found the selected synthetic host file, host environment value, inherited descriptor and `/proc/1` root/cwd paths inaccessible in one sandbox invocation. It does not cover every proc path or race.
- `python3 -m unittest discover -s tests/executor -v`: 11 tests passed, including the independent tests and implementation authors' tests. The authors' tests exercise selected mount/capability, direct network denial, timeout descendant cleanup, socket forwarding, cap and DNS cases. Passing them does not establish comprehensive containment or resource enforcement.
- Static inspection found DNS answers checked before connecting to the selected numeric address, but no independent rebinding race test was run. No independent hardlink, sibling-UID attack, host writable-mount race, full inherited credential inventory, browser/agent tool-routing, resource exhaustion or full protocol-limit test was completed. Those remain unresolved; absence of a finding is not evidence of safety.

The historical proof was observed in the original test run; `tests/executor/test_boundary_adversarial.py` now retains a denial regression rather than the original exploit assertion. Re-run against the exact final code and update this assessment after changes. Agent review does not replace independent qualified human review.
