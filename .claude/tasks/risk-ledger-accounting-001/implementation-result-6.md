Status: PASS

## Summary

Implemented the approved task and corrections through G1-G5:

- Enforced a common position/ledger accounting cut.
- Published post-cut realized PnL as pending telemetry.
- Added configurable accounting-cut skew validation.
- Hardened schema-v3 checkpoint and SQLite metadata validation.
- Contained startup ledger failures with fail-closed publication.
- Preserved inactive-strategy exposure and existing safety behavior.

No network, trading, credentials, dependencies, commits, pushes, deployments, or forbidden-file edits occurred.

## Files changed

- [aggregator.py](/Users/ohayotaro/claude-finance/src/risk/aggregator.py)
- [ledger.py](/Users/ohayotaro/claude-finance/src/risk/ledger.py)
- [test_aggregator.py](/Users/ohayotaro/claude-finance/tests/test_risk/test_aggregator.py)
- [test_ledger.py](/Users/ohayotaro/claude-finance/tests/test_risk/test_ledger.py)
- [risk_groups.toml](/Users/ohayotaro/claude-finance/config/risk_groups.toml)
- [DESIGN.md](/Users/ohayotaro/claude-finance/.claude/docs/DESIGN.md)
- [test-evidence.md](/Users/ohayotaro/claude-finance/.claude/tasks/risk-ledger-accounting-001/test-evidence.md)
- [implementation-result.md](/Users/ohayotaro/claude-finance/.claude/tasks/risk-ledger-accounting-001/implementation-result.md)

Pre-existing `state.json`, stderr, and review artifacts were preserved. This phase did not write `review.md`.

## Material design decisions

- Caps include ledger events only through `positions_observation.as_of`.
- Later events remain pending until a position observation covers them.
- `accounting_cut_max_skew_s` defaults to the poll interval and cannot exceed the health window.
- Schema-v3 checkpoints require every field and exact JSON types; unsafe coercions and defaults were removed.
- Populated/non-initial ledgers require valid generation, cursor, and UTC `as_of` metadata.
- Metadata is revalidated before ingestion and metadata reads.
- Startup recovery failures publish unhealthy, fail-closed state and exit non-zero.

## Validation

Failing-first G regressions: `10 failed in 0.29s`; corrected: `10 passed in 0.08s`.

- `UV_OFFLINE=1 UV_CACHE_DIR=/private/tmp/risk-ledger-uv-cache uv run --extra dev pytest tests/test_risk/ -v`
  - `152 passed in 0.73s`
- `UV_OFFLINE=1 UV_CACHE_DIR=/private/tmp/risk-ledger-uv-cache uv run --extra dev pytest -m 'not integration and not slow'`
  - Before: `309 passed in 7.08s`
  - After: `321 passed in 7.31s`
- `UV_OFFLINE=1 UV_CACHE_DIR=/private/tmp/risk-ledger-uv-cache uv run --extra dev ruff check src/ tests/ .claude/hooks/ .claude/scripts/`
  - `All checks passed!`
- `UV_OFFLINE=1 UV_CACHE_DIR=/private/tmp/risk-ledger-uv-cache uv run --extra dev mypy src/ .claude/scripts/`
  - `Success: no issues found in 14 source files`
- `UV_OFFLINE=1 UV_CACHE_DIR=/private/tmp/risk-ledger-uv-cache uv run python -m src.orchestrator.registry audit`
  - `audit: ok (0 strategies, 0 accounts)`
- `git diff --check`
  - Exit code 0, no output; run last as required.

## Acceptance-criteria mapping

| AC | Result | Evidence |
|---|---|---|
| AC1 | PASS | `test_closed_round_trip_net_of_costs_and_funding_is_idempotent`, cash/borrow, identity-conflict, and generator tests |
| AC2 | PASS | Venue-zero, venue-omission, and `test_ledger_events_after_position_cut_do_not_double_count_unrealized` |
| AC3 | PASS | Independent disabled, deprecated, retired, residual-retention, and incomplete-observation tests |
| AC4 | PASS | Rotation/truncation, replay, UTC boundary, malformed checkpoint, startup ledger error, and ledger metadata tests |
| AC5 | PASS | State metadata, consumer freshness/source, independent observation-age, and common-cut pending telemetry tests |
| AC6 | PASS | Example configuration, unsafe value, non-finite, currency, and slug tests |
| AC7 | PASS | All required commands above pass; legacy-test changes and reasons are recorded in `test-evidence.md` |
| AC8 | PASS | ADR-005 and `test_design_records_ledger_aggregator_exception` |

## Residual risks, debt, or blockers

- No real venue adapter yet validates cursor and normalized PnL semantics.
- Exposure still uses `size * entry_price`; venue mark/current notional remains follow-up work.
- The writer lock is host-local and cooperative.
- Ledger compaction and multi-account/currency conversion remain out of scope.
- A fresh read-only sixth review is required before PM acceptance; no implementation blocker remains.