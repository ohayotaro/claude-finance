Status: PASS

## Summary

Implemented the approved task through corrections I1-I6:

- Added separate Decimal bounds for venue inputs (40) and derived/persisted values (100).
- Made cap comparisons exact and independent of ambient Decimal precision.
- Applied future-skew tolerance consistently to producer health and consumer validation.
- Made CLI NullVenue refusal publish fail-closed state before exiting.
- Corrected symmetric accounting-cut documentation.
- Preserved authoritative venue/ledger accounting and all fail-closed controls.

No network, trading, credentials, commits, pushes, deployments, or dependency changes occurred.

## Files changed

- [src/risk/aggregator.py](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:740)
- [src/risk/ledger.py](/Users/ohayotaro/claude-finance/src/risk/ledger.py:24)
- [tests/test_risk/test_aggregator.py](/Users/ohayotaro/claude-finance/tests/test_risk/test_aggregator.py:368)
- [tests/test_risk/test_ledger.py](/Users/ohayotaro/claude-finance/tests/test_risk/test_ledger.py:396)
- [config/risk_groups.toml](/Users/ohayotaro/claude-finance/config/risk_groups.toml)
- [.claude/docs/DESIGN.md](/Users/ohayotaro/claude-finance/.claude/docs/DESIGN.md:44)
- [test-evidence.md](/Users/ohayotaro/claude-finance/.claude/tasks/risk-ledger-accounting-001/test-evidence.md)
- [implementation-result.md](/Users/ohayotaro/claude-finance/.claude/tasks/risk-ledger-accounting-001/implementation-result.md)

Pre-existing state, stderr, and review artifacts were preserved. `review.md` was not written.

## Material design decisions

- Valid boundary inputs may produce aggregate values up to the wider derived bound and round-trip through checkpoints.
- Cap thresholds use exact cross-multiplication instead of percentage division.
- Repeating drawdown ratios are explicitly rounded to the repository-standard two decimals in an isolated context.
- Consumer validation reads the published future-skew tolerance rather than rejecting all negative ages.
- NullVenue startup refusal atomically replaces any prior healthy state with non-authoritative, fail-closed state.

## Validation

- Corrections-pass baseline: `325 passed in 7.22s`
- Failing-first regressions: `5 failed in 0.21s`
- Corrected targeted regressions: `5 passed in 0.06s`
- `UV_OFFLINE=1 UV_CACHE_DIR=/private/tmp/risk-ledger-uv-cache uv run --extra dev pytest tests/test_risk/ -v`
  - `161 passed in 0.69s`
- `UV_OFFLINE=1 UV_CACHE_DIR=/private/tmp/risk-ledger-uv-cache uv run --extra dev pytest -m 'not integration and not slow'`
  - `330 passed in 7.22s`
- `UV_OFFLINE=1 UV_CACHE_DIR=/private/tmp/risk-ledger-uv-cache uv run --extra dev ruff check src/ tests/ .claude/hooks/ .claude/scripts/`
  - `All checks passed!`
- `UV_OFFLINE=1 UV_CACHE_DIR=/private/tmp/risk-ledger-uv-cache uv run --extra dev mypy src/ .claude/scripts/`
  - `Success: no issues found in 14 source files`
- `UV_OFFLINE=1 UV_CACHE_DIR=/private/tmp/risk-ledger-uv-cache uv run python -m src.orchestrator.registry audit`
  - `audit: ok (0 strategies, 0 accounts)`
- `git diff --check`
  - Exit code `0`, no output; run last.

## Acceptance-criteria mapping

| AC | Result | Evidence |
|---|---|---|
| AC1 | PASS | `test_closed_round_trip_net_of_costs_and_funding_is_idempotent`, `test_daily_total_from_boundary_ledger_entries_is_queryable` |
| AC2 | PASS | `test_venue_zero_unrealized_overrides_log_telemetry`, `test_venue_omission_prunes_log_unrealized_from_caps` |
| AC3 | PASS | `test_disabled_strategy_residual_position_counts_until_flat`, `test_deprecated_strategy_position_pnl_counts_toward_caps`, `test_retired_strategy_residual_order_counts_until_flat` |
| AC4 | PASS | `test_ledger_restart_replay_does_not_double_count`, `test_previous_utc_day_fill_arriving_today_is_not_today_pnl`, `test_exposure_from_boundary_inputs_round_trips_through_checkpoint` |
| AC5 | PASS | `test_state_schema_v2_publishes_required_metric_metadata`, `test_allowed_future_skew_publishes_healthy_and_validates`, `test_main_null_venue_refusal_publishes_fail_closed_state` |
| AC6 | PASS | `test_example_risk_groups_config_loads`, `test_config_rejects_non_finite_values`, `test_unsafe_risk_group_is_rejected` |
| AC7 | PASS | All required test, lint, type-check, audit, and whitespace checks passed |
| AC8 | PASS | `test_design_records_ledger_aggregator_exception` |

The exhaustive test inventory, failing-first history, and legacy-test replacement reasons are in [test-evidence.md](/Users/ohayotaro/claude-finance/.claude/tasks/risk-ledger-accounting-001/test-evidence.md).

## Residual risks, debt, or blockers

- No real venue adapter yet validates cursor completeness or normalized PnL.
- Exposure still uses entry price; venue mark/current notional remains deferred.
- Writer locking is host-local and cooperative.
- Ledger compaction, currency conversion, and shared-account cash allocation remain deferred.
- A fresh read-only eighth review remains required for PM acceptance.