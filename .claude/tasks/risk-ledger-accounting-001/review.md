# Verdict: CHANGES_REQUIRED

The ledger core is well structured, but several fail-closed and recovery defects remain in the aggregator.

## Findings

### Critical

1. **Consumers cannot detect that an otherwise valid state file became stale.**  
   `age_seconds` is calculated only when the file is published, then [the validator trusts that frozen number](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:1122). Although it parses `as_of_ts`, it never compares that timestamp with the consumer’s current time. A read-only probe confirmed that metadata with `as_of_ts = 2020-01-01` and `age_seconds = 0` is accepted with `max_age_s=120` in 2026. If the aggregator crashes or hangs after publishing, both `healthy=true` and the metric ages can remain apparently fresh indefinitely. This violates AC5 and the fail-closed health contract.

### High

2. **A stale venue cycle is treated as successful and clears existing safety gates.**  
   Observation validation [rejects future timestamps but imposes no maximum age](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:692). Reconciliation then [resets `fail_closed`](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:891) and recomputes cap flags from the stale data. A probe using 2020 snapshot/ledger timestamps at a 2026 reconciliation cleared `fail_closed`, `soft_cap`, and `hard_cap`, while merely publishing `healthy=false`. The approved plan explicitly requires stale data not to clear an existing cap. This affects AC5 and fail-closed behavior.

3. **Position and order metrics are assigned provenance they do not possess.**  
   `VenuePosition` and `VenueOrder` [carry no observation timestamp, completeness indicator, or authority flag](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:109), yet exposure, unrealized PnL, and both counts are [labeled with the independent account snapshot timestamp](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:1054). A fresh account snapshot combined with a stale or partial empty position response can therefore clear residual strategies and exposure while being labeled fresh and authoritative. This undermines AC2, AC3, and AC5.

4. **Ledger and checkpoint persistence are not crash-consistent for drawdown state.**  
   The ledger cursor commits during [reconciliation](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:868), while HWM and start-of-day state are updated later and checkpointed only after [state publication](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:1535). The checkpoint contains no ledger cursor or generation binding. A crash after observing a new equity peak but before checkpoint save leaves the ledger ahead and the checkpoint with an older HWM; after restart, a lower equity can permanently understate drawdown. The checkpoint also omits last-known snapshot/exposure/PnL and provenance, so a failed first reconciliation after restart cannot retain the required cached venue state. This leaves AC4 recovery incomplete and affects AC5 drawdown correctness.

5. **Non-finite configuration values are accepted.**  
   Configuration is converted to floats and [validated only with ordering/range comparisons](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:362). TOML `inf` is accepted for both loss thresholds and `health_window_s`; a probe confirmed this. Infinite loss thresholds disable the caps, while infinite health duration causes `timedelta(seconds=inf)` to fail during publication. This violates the approved configuration-hardening design associated with AC6.

6. **Malformed non-UTF-8 log data can crash the aggregator.**  
   [Only `json.JSONDecodeError` is caught](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:559); `json.loads()` on invalid UTF-8 bytes raises `UnicodeDecodeError`. The surrounding reconciliation code catches only `OSError` for log reads, so the exception escapes `reconcile_once` and `run_forever`. A read-only probe reproduced the exception. This violates the binding rule that one malformed strategy log must never take down aggregate enforcement.

### Medium

7. **`risk_group` is not safe for use as a filesystem component.**  
   The loader validates account and currency but [does not validate the risk-group identifier](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:325). It is then directly joined into the [ledger path](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:663) and state/checkpoint paths. A quoted absolute or traversal-containing TOML key selected through `--risk-group` can escape `data/aggregator`. The new authoritative database should use a validated slug or a common-path check.

### Low

8. **The implementation result does not contain the evidence it claims.**  
   It says all 22 new test names and failing-first evidence are recorded [at line 49](/Users/ohayotaro/claude-finance/.claude/tasks/risk-ledger-accounting-001/implementation-result.md:49), but neither appears in the artifact. Its AC mapping also names no tests, and it does not identify the modified legacy tests with explicit reasons. This is an AC7 evidence gap.

## Acceptance-criteria gaps

| AC | Review result |
|---|---|
| AC1 | Implemented and covered by known-value Decimal ledger tests. Full execution was not independently rerun. |
| AC2 | The explicit zero/omission tests exist and the aggregation logic uses venue positions, but production authority is weakened by missing position-snapshot completeness and timestamps. |
| AC3 | Disabled/deprecated residual behavior is covered with positions/orders; subject to the same incomplete-snapshot problem. |
| AC4 | Rotation, truncation, replay, and UTC-day tests exist. Crash consistency between ledger and checkpoint, failed reconciliation immediately after restart, and end-to-end venue replay after restart are untested and unsafe. |
| AC5 | **Not met:** frozen ages can be accepted indefinitely, and position/order ages are borrowed from another observation. |
| AC6 | The example loads, but unsafe non-finite values and unsafe risk-group path components remain accepted. |
| AC7 | Lint, typing, and audit were reproduced; full test execution was blocked in this read-only review environment. The implementation artifact also omits required named evidence and legacy-test reasons. |
| AC8 | Met. [ADR-005](/Users/ohayotaro/claude-finance/.claude/docs/DESIGN.md:44) records the model and explicit ADR-004 exception. |

## Validation gaps

- Full pytest execution could not be independently performed because the enforced read-only filesystem provides no writable UV cache or temporary directory. No network access was attempted.
- Collection succeeded: **239 tests collected**.
- Seven non-writing risk tests passed.
- Direct existing-environment checks passed:
  - Ruff: `All checks passed!`
  - Mypy: `Success: no issues found in 14 source files`
  - Registry audit: `audit: ok (0 strategies, 0 accounts)`
  - `git diff --check`: passed.
- Missing regressions include:
  - State-file staleness after publication time advances.
  - Stale snapshots preserving existing caps/fail-closed state.
  - Independent position/order timestamps and incomplete responses.
  - Crash between ledger commit and checkpoint save.
  - Restart followed by venue failure.
  - Invalid UTF-8 log lines.
  - `inf`/`nan` configuration values.
  - Unsafe `risk_group` path components.

## Residual risks

- **Financial:** Venue-normalized gross PnL remains unvalidated against a real adapter; checkpoint races can understate HWM drawdown; multi-currency conversion remains unsupported.
- **Operational:** Corrupt log bytes can terminate enforcement; SQLite retention is unbounded; stale published state is not safely consumable after a crash.
- **Security:** No credentials, network client, or new dependency was introduced, but unsanitized risk-group paths can escape the intended data directory.
- **Regression:** The expanded venue protocol will require all future adapters to implement ledger history and a stronger coherent snapshot contract. State-schema consumers must recompute freshness from authoritative timestamps rather than trust stored ages.