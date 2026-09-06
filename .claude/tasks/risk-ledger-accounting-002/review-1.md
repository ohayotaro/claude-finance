**Verdict: CHANGES_REQUIRED**

1. **Medium - Checkpoint validation depends on ambient Decimal precision (AC1).** At [persistence.py:588](/Users/ohayotaro/claude-finance/src/risk/persistence.py:588), `abs(state.group_net_exposure)` runs outside the isolated arithmetic context. An in-memory reproduction with equal net/gross exposure of `1.2345678901234567890123456789` rejects the checkpoint at default precision 28 but restores it at 256. Conversely, rounding can admit a corrupted checkpoint whose net exceeds gross. Use `copy_abs()` or the exact context and add regression coverage for both cases.

2. **Medium - Required test inventory and refactor evidence are missing (AC5).** [implementation-result.md:12](/Users/ohayotaro/claude-finance/.claude/tasks/risk-ledger-accounting-002/implementation-result.md:12) links to itself for an old/new mapping that is absent. It also omits the required identification of pure-move hunks. The assertion-count claim at line 73 cannot demonstrate that assertion meaning was preserved. Supply the complete before/after inventory, moved-test mapping, and comparison against the task-001 baseline.

3. **Low - Implementation artifact violates its evidence contract (AC7).** The [AC table](/Users/ohayotaro/claude-finance/.claude/tasks/risk-ledger-accounting-002/implementation-result.md:79) contains prose instead of exact test function names, and every row contains a non-ASCII em dash. This contradicts the artifact's compliance claims. Replace it with an English ASCII artifact containing the required exact-name mapping.

| Criterion | Review conclusion |
|---|---|
| AC1 | Incomplete: semantic checks exist, but consistent restoration has the Decimal defect above. |
| AC2 | Named startup-refusal branches publish through the shared helper; regression execution remains unverified. |
| AC3 | Byte-offset implementation and named regression are present; execution remains unverified. |
| AC4 | Verified: facade is 553 lines; extracted modules are below 900; boundary and compatibility tests pass. |
| AC5 | Incomplete: required inventory/move evidence is absent; full-suite preservation is unverified. |
| AC6 | Required `uv` validation is blocked in this review; fallback checks passed as detailed below. |
| AC7 | Module map exists and its test passes; artifact requirements fail. |

Validation was entirely offline. All four required `uv` commands exited 2 because the read-only sandbox denied access to the uv cache. Using installed tools without caches, ruff passed, mypy passed for 19 files, and registry audit passed. Pytest collected **346 fast cases / 177 risk cases**; **12 selected tests passed**. Collection does not establish full-suite success.

`git diff --check` ran last and exited 0 with no whitespace diagnostics; macOS emitted sandbox-related cache errors. The single-whole-file-write requirement cannot be verified from the permitted artifacts.

Residual financial and operational risk includes accepting inconsistent exposure or refusing a valid restart because of Decimal rounding. Regression confidence remains limited by the missing baseline evidence and unexecuted full suite. No additional security finding was established; real venue integration remains unvalidated and out of scope.

Repository files and Git state were left unchanged.