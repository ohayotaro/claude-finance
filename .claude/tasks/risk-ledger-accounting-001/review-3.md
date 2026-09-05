# Verdict: CHANGES_REQUIRED

## Findings

1. **High — Post-fetch freshness still has an unsafe default path.**  
   [aggregator.py](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:995) substitutes a fixed, pre-call `now_utc` value when no `clock` is supplied. A snapshot fresh at cycle start but stale after slow venue I/O can therefore pass validation and clear fail-closed/cap/residual state. The regression test avoids this path by supplying an explicit clock. This leaves D1 and AC5 incomplete.

2. **High — Checkpoint binding can certify stale state against a newer ledger generation.**  
   Reconciliation records the generation that produced the state at [aggregator.py](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:1078), but `save_checkpoint` rereads and unconditionally overwrites it with the latest ledger binding at [aggregator.py](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:1500). If another process advances the ledger between reconciliation and checkpoint save, stale metrics and drawdown baselines become apparently bound to the newer generation, bypassing the restart mismatch check at [aggregator.py](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:1866). Saving must compare bindings and refuse on mismatch, or enforce single-writer ownership. This affects C4/D2 and AC4.

3. **High — Completeness and authority flags are validated by truthiness, not exact boolean value.**  
   [aggregator.py](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:841) and [ledger.py](/Users/ohayotaro/claude-finance/src/risk/ledger.py:446) accept values such as `"false"` as authoritative and complete. An adapter normalization error could therefore pass an incomplete empty observation and clear residual strategies and caps at [aggregator.py](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:1091). Require `is True` or explicit boolean type validation and add malformed-flag regressions. This affects C3, AC3, and AC5.

4. **Low — The implementation result still does not satisfy D3/C8.**  
   [implementation-result.md](/Users/ohayotaro/claude-finance/.claude/tasks/risk-ledger-accounting-001/implementation-result.md:50) contains no complete new-test list, failing-first evidence by group, or names/reasons for the three replaced legacy tests. Line 62 claims those details are present when they are not. The artifact is also predominantly Japanese despite the brief requiring English, plain-ASCII artifacts. This leaves AC7 incomplete.

## Acceptance-criteria gaps

| AC | Review result |
|---|---|
| AC1 | No static gap found; known-value and idempotency tests exist. |
| AC2 | No static gap found; venue-zero and omission tests exist. |
| AC3 | Gap: malformed truthy completeness/authority values can clear residual risk. |
| AC4 | Gap: checkpoint save can bind stale state to a concurrently newer ledger. |
| AC5 | Gap: the fixed `now_utc` default can validate freshness against pre-fetch time; malformed authority flags can pass. |
| AC6 | No static gap found; the example configuration loads and validation exists. |
| AC7 | Gap: required implementation evidence is absent, and pytest execution was not independently reproducible here. |
| AC8 | No static gap found; ADR-005 documents the accounting model and ADR-004 exception. |

## Validation gaps

- Offline pytest execution was blocked by the read-only sandbox: uv could not initialize its cache, and pytest could not create a temporary directory.
- Collection succeeded: **89 risk tests** and **258 fast-suite tests**.
- Direct offline checks passed:
  - Ruff: all checks passed.
  - Mypy: no issues in 14 source files.
  - Registry audit: `audit: ok (0 strategies, 0 accounts)`.
  - `git diff --check`: exit 0.
- No network access was enabled.

## Residual risks

- Venue cursor completeness, normalized realized PnL, and timestamp behavior remain unverified without a real adapter.
- Exposure still uses entry-price notional rather than mark/current notional, as recorded for follow-up.
- Concurrent aggregator writers are not prevented.
- Ledger retention remains unbounded; multi-currency conversion remains unsupported.
- No new credential or network-client exposure was found, but dynamically loaded venue adapters remain trusted local code under the `src.risk` namespace.