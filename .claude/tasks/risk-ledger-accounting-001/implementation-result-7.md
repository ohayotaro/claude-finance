Status: PASS

## Summary

Implemented the approved task through corrections H1-H3:

- Added symmetric position/ledger accounting-cut enforcement.
- Realized PnL now uses `min(position_cut, ledger_cut)`.
- Effective-cut provenance is published correctly.
- Added isolated 256-digit Decimal arithmetic with fail-closed traps.
- Preserved authoritative venue accounting, ledger idempotency, checkpoint binding, and inactive-strategy risk visibility.

No network, trading, credentials, commits, pushes, deployments, dependencies, or destructive Git operations were used.

## Files changed

- [aggregator.py](/Users/ohayotaro/claude-finance/src/risk/aggregator.py)
- [ledger.py](/Users/ohayotaro/claude-finance/src/risk/ledger.py)
- [test_aggregator.py](/Users/ohayotaro/claude-finance/tests/test_risk/test_aggregator.py)
- [test_ledger.py](/Users/ohayotaro/claude-finance/tests/test_risk/test_ledger.py)
- [risk_groups.toml](/Users/ohayotaro/claude-finance/config/risk_groups.toml)
- [DESIGN.md](/Users/ohayotaro/claude-finance/.claude/docs/DESIGN.md)
- [test-evidence.md](/Users/ohayotaro/claude-finance/.claude/tasks/risk-ledger-accounting-001/test-evidence.md)
- [implementation-result.md](/Users/ohayotaro/claude-finance/.claude/tasks/risk-ledger-accounting-001/implementation-result.md)

Pre-existing `state.json`, stderr, and review artifacts were preserved. This implementation phase did not write `review.md`.

## Material design decisions

- Accounting-cut skew is enforced in both directions before ledger commit.
- Enforcement uses `min(positions_observation.as_of, ledger_batch.as_of)`.
- Unrealized PnL provenance uses that effective cut; exposure retains its independent venue-position timestamp.
- Ledger accumulation, exposure arithmetic, unrealized summation, and composite PnL addition use a fixed 256-digit context trapping `Inexact`, `Rounded`, `Overflow`, and `InvalidOperation`.
- The venue-normalized, single-account, single-quote-currency model remains unchanged.

## Validation

- Addendum 6 failing-first regressions:
  - Before: `4 failed in 0.18s`
  - After: `4 passed in 0.05s`
- `UV_OFFLINE=1 UV_CACHE_DIR=/private/tmp/risk-ledger-uv-cache uv run --extra dev pytest tests/test_risk/ -v`
  - `156 passed in 0.62s`
- `UV_OFFLINE=1 UV_CACHE_DIR=/private/tmp/risk-ledger-uv-cache uv run --extra dev pytest -m 'not integration and not slow'`
  - Original recorded task baseline: `215 passed`
  - Before Addendum 6: `321 passed in 6.79s`
  - After: `325 passed in 6.82s`
- `UV_OFFLINE=1 UV_CACHE_DIR=/private/tmp/risk-ledger-uv-cache uv run --extra dev ruff check src/ tests/ .claude/hooks/ .claude/scripts/`
  - `All checks passed!`
- `UV_OFFLINE=1 UV_CACHE_DIR=/private/tmp/risk-ledger-uv-cache uv run --extra dev mypy src/ .claude/scripts/`
  - `Success: no issues found in 14 source files`
- `UV_OFFLINE=1 UV_CACHE_DIR=/private/tmp/risk-ledger-uv-cache uv run python -m src.orchestrator.registry audit`
  - `audit: ok (0 strategies, 0 accounts)`
- `git diff --check`
  - Exit code `0`, no output; run last.

## Acceptance criteria

| AC | Result | Principal evidence |
|---|---|---|
| AC1 | PASS | `test_closed_round_trip_net_of_costs_and_funding_is_idempotent`, `test_ledger_accumulation_is_exact_for_supported_domain` |
| AC2 | PASS | `test_venue_zero_unrealized_overrides_log_telemetry`, `test_enforcement_cut_is_min_of_position_and_ledger_cuts` |
| AC3 | PASS | `test_disabled_strategy_residual_position_counts_until_flat`, `test_deprecated_strategy_position_pnl_counts_toward_caps`, `test_retired_strategy_residual_order_counts_until_flat` |
| AC4 | PASS | Rotation, truncation, restart, late-fill, checkpoint, and metadata tests listed in `test-evidence.md` |
| AC5 | PASS | `test_state_schema_v2_publishes_required_metric_metadata`, `test_metric_consumer_recomputes_age_from_as_of_ts`, `test_enforcement_cut_is_min_of_position_and_ledger_cuts` |
| AC6 | PASS | `test_example_risk_groups_config_loads`, configuration safety regressions |
| AC7 | PASS | All required test, lint, type-check, audit, and whitespace commands passed |
| AC8 | PASS | `test_design_records_ledger_aggregator_exception`; ADR-005 updated |

The exhaustive AC-to-test map and legacy-test replacement reasons are in [test-evidence.md](/Users/ohayotaro/claude-finance/.claude/tasks/risk-ledger-accounting-001/test-evidence.md).

## Residual risks, debt, or blockers

- No real venue adapter yet validates cursor completeness or normalized venue PnL.
- Exposure still uses entry price; venue mark/current notional is deferred.
- Writer locking is host-local and cooperative.
- Ledger compaction, currency conversion, and shared-account cash-event allocation remain deferred.
- A fresh read-only seventh review remains required for PM acceptance; there is no implementation blocker.