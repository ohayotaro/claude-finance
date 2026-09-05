Status: PASS

## Summary

Implemented the approved task and all correction groups C1-C8, D1-D3, E1-E4, and F1-F6.

Key outcomes:

- Portable POSIX/Windows single-writer locking.
- One-time immutable materialization of all venue collections.
- Checkpoint mismatches now publish fail-closed, non-authoritative state.
- Venue financial inputs have documented `Decimal` magnitude/exponent bounds.
- Post-commit accounting is staged and exception-contained.
- Disabled, deprecated, and retired residual risk has independent coverage.
- Implementation evidence is English, ASCII-only, and maps every AC to named tests.

No network, credentials, trading, dependency changes, Git mutation, or forbidden-file changes occurred.

## Files changed

- [aggregator.py](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:1052)
- [ledger.py](/Users/ohayotaro/claude-finance/src/risk/ledger.py:24)
- [test_aggregator.py](/Users/ohayotaro/claude-finance/tests/test_risk/test_aggregator.py:2634)
- [test_ledger.py](/Users/ohayotaro/claude-finance/tests/test_risk/test_ledger.py:325)
- [risk_groups.toml](/Users/ohayotaro/claude-finance/config/risk_groups.toml:1)
- [DESIGN.md](/Users/ohayotaro/claude-finance/.claude/docs/DESIGN.md:44)
- [test-evidence.md](/Users/ohayotaro/claude-finance/.claude/tasks/risk-ledger-accounting-001/test-evidence.md:108)
- [implementation-result.md](/Users/ohayotaro/claude-finance/.claude/tasks/risk-ledger-accounting-001/implementation-result.md:1)

The pre-existing dirty `state.json` and `review.md` were not modified.

## Material design decisions

- Venue collections are converted to tuples before validation and reused afterward.
- `Decimal` inputs are limited to an absolute adjusted exponent and stored exponent of 40.
- Post-commit calculations operate on staged state; partial results never replace the authoritative cache.
- Checkpoint refusal returns `False`, invalidates metric provenance, and forces unhealthy publication.
- Locking uses `fcntl.flock` on POSIX and `msvcrt.locking` on Windows.
- Cached amounts and HWM are retained on failure, but their enforcement provenance is invalidated.

## Validation

Pre-change corrections baseline:

```text
UV_OFFLINE=1 UV_CACHE_DIR=/private/tmp/risk-ledger-uv-cache uv run --extra dev pytest -m "not integration and not slow"
```

Result: `285 passed in 7.03s`.

Failing-first F1-F5 regression run: `21 failed, 2 passed in 0.56s`.  
Corrected targeted run: `23 passed in 0.11s`.

Final required validation:

- `UV_OFFLINE=1 UV_CACHE_DIR=/private/tmp/risk-ledger-uv-cache uv run --extra dev pytest tests/test_risk/ -v`
  - `140 passed in 0.65s`
- `UV_OFFLINE=1 UV_CACHE_DIR=/private/tmp/risk-ledger-uv-cache uv run --extra dev pytest -m "not integration and not slow"`
  - `309 passed in 7.29s`
- `UV_OFFLINE=1 UV_CACHE_DIR=/private/tmp/risk-ledger-uv-cache uv run --extra dev ruff check src/ tests/ .claude/hooks/ .claude/scripts/`
  - `All checks passed!`
- `UV_OFFLINE=1 UV_CACHE_DIR=/private/tmp/risk-ledger-uv-cache uv run --extra dev mypy src/ .claude/scripts/`
  - `Success: no issues found in 14 source files`
- `UV_OFFLINE=1 UV_CACHE_DIR=/private/tmp/risk-ledger-uv-cache uv run python -m src.orchestrator.registry audit`
  - `audit: ok (0 strategies, 0 accounts)`
- `git diff --check`
  - Exit code 0

Fast-suite progression: `215` before the original task, `285` before this corrections pass, `309` after.

## Acceptance-criteria mapping

| AC | Result | Named evidence |
|---|---|---|
| AC1 | PASS | `test_closed_round_trip_net_of_costs_and_funding_is_idempotent`, `test_generator_ledger_batch_is_materialized_once` |
| AC2 | PASS | `test_venue_zero_unrealized_overrides_log_telemetry`, `test_venue_omission_prunes_log_unrealized_from_caps`, `test_generator_position_observation_is_materialized_once` |
| AC3 | PASS | `test_disabled_strategy_residual_position_counts_until_flat`, `test_deprecated_strategy_position_pnl_counts_toward_caps`, `test_retired_strategy_residual_order_counts_until_flat` |
| AC4 | PASS | Rotation/truncation, restart replay, late-fill, UTC-boundary, checkpoint-binding, cached-restart, and single-writer tests listed in `test-evidence.md` |
| AC5 | PASS | `test_state_schema_v2_publishes_required_metric_metadata`, consumer freshness tests, `test_checkpoint_binding_mismatch_publishes_unhealthy_state` |
| AC6 | PASS | `test_example_risk_groups_config_loads`, non-finite/config/slug/currency validation tests |
| AC7 | PASS | All required commands pass; portable-lock, generator, Decimal, post-commit, and strict-boolean regressions pass |
| AC8 | PASS | `test_design_records_ledger_aggregator_exception` verifies ADR-005 and the ADR-004 exception |

## Residual risks, debt, or blockers

- No real venue adapter exists, so venue-specific cursor and normalized-PnL semantics remain unverified.
- Exposure still uses `size * entry_price`; mark/current notional remains a follow-up.
- The writer lock is host-local and requires cooperating writers.
- Ledger compaction and multi-currency conversion remain out of scope.
- A fresh read-only fifth review remains required before PM acceptance; there is no implementation blocker.