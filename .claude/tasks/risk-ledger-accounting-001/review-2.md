# Verdict: CHANGES_REQUIRED

## Findings

### Critical — Freshness is measured before venue I/O

[`reconcile_once`](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:977) captures `now_utc` before four venue calls at [line 991](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:991), then validates all observations against that earlier time. The strict future/stale checks are at [line 796](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:796).

This has two unsafe outcomes:

- A normal adapter timestamping its response during the call produces a timestamp later than the captured time and is rejected. A read-only dynamic-client probe reproduced immediate fail-closed with `snapshot.timestamp cannot be in the future`.
- A snapshot just within the health window at cycle start can become stale during slow venue calls but still be accepted. The cycle then clears `fail_closed`, recomputes caps, and can clear residual strategies at [line 1034](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:1034).

Freshness must be evaluated using a post-fetch/completion clock, preferably through an injectable clock callable. This violates correction C2 and leaves AC3, AC5, and AC7 incomplete.

### High — A post-commit ledger failure can bind stale risk state to the advanced ledger

Ledger ingestion commits at [aggregator.py:1008](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:1008). If the subsequent daily-total query raises the generic `LedgerError` produced at [ledger.py:628](/Users/ohayotaro/claude-finance/src/risk/ledger.py:628), reconciliation preserves the old PnL and does not immediately fail closed because generic `LedgerError` is excluded from the forced-failure list at [aggregator.py:1017](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:1017).

`run_forever` then unconditionally saves a checkpoint at [aggregator.py:1961](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:1961), and `save_checkpoint` reads the new ledger binding at [aggregator.py:1454](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:1454). The checkpoint can therefore claim that stale cached PnL/caps correspond to the new generation. Restart no longer detects the mismatch, potentially omitting a newly committed loss from cap decisions.

The C4 regression only simulates a crash without this failed-cycle checkpoint save. Add a regression covering commit → total-read failure → checkpoint attempt → restart. AC4 and AC7 remain incomplete.

### Low — C8 evidence is absent from the implementation result

The implementation result reports aggregate test counts at [implementation-result.md:42](/Users/ohayotaro/claude-finance/.claude/tasks/risk-ledger-accounting-001/implementation-result.md:42) and claims complete evidence at [line 64](/Users/ohayotaro/claude-finance/.claude/tasks/risk-ledger-accounting-001/implementation-result.md:64), but it does not include:

- Every new test name.
- Failing-first results and reasons.
- The modified legacy tests and reason for each change.

The diff replaces three legacy tests, but those replacements are not documented. This directly fails C8 and AC7.

## Acceptance-criteria gaps

| AC | Review status |
|---|---|
| AC1 | Satisfied by code/test inspection; not freshly executed. |
| AC2 | Satisfied by inspection; venue-only unrealized behavior is covered. |
| AC3 | Partial: normal residual logic exists, but stale-at-use observations can clear residual state. |
| AC4 | Not satisfied: checkpoint binding can bless stale state after a post-commit read failure. |
| AC5 | Partial: consumer recomputation is correct, but producer-side observation freshness uses the wrong clock. |
| AC6 | Satisfied by inspection and successful test collection. |
| AC7 | Not satisfied because of the two missing regressions, missing C8 evidence, and unavailable fresh test execution. |
| AC8 | Satisfied; ADR-005 documents the accounting model and ADR-004 exception. |

## Validation gaps

No network access was used.

- Required `uv` commands could not start because this review sandbox forbids cache writes.
- Direct pytest execution also could not create temporary files.
- Read-only collection succeeded: 85 risk tests and 254 fast-suite tests.
- Direct read-only Ruff: passed.
- Direct mypy: passed, 14 source files.
- Direct registry audit: passed.
- `git diff --check`: passed.

The implementation artifact records successful full runs, but they were not independently reproduced here.

## Residual risks

- Financial: exposure remains calculated as `size * entry_price` at [aggregator.py:684](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:684), rather than venue-supplied current notional or mark value. This can understate exposure as prices move and should be tracked separately.
- Operational: no real adapter validates cursor completeness, timestamp behavior, or normalized venue PnL; ledger retention remains unbounded.
- Security: no credential, network, dependency, forbidden-file, or live-trading changes were identified. Path and slug checks are present.
- Regression: full tests were not freshly executable, and the undocumented legacy-test replacements weaken the audit trail.