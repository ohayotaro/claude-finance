Status: PASS

## Summary

venue-authoritative risk accounting was implemented. Realized PnL now comes from an idempotent SQLite fill ledger; venue snapshots exclusively determine unrealized PnL, exposure, margin, drawdown, and position/order counts. Logs are telemetry only.

Fast-suite results increased from 215 to 239 passing tests.

## Files changed

- [ledger.py](/Users/ohayotaro/claude-finance/src/risk/ledger.py)
- [aggregator.py](/Users/ohayotaro/claude-finance/src/risk/aggregator.py)
- [test_ledger.py](/Users/ohayotaro/claude-finance/tests/test_risk/test_ledger.py)
- [test_aggregator.py](/Users/ohayotaro/claude-finance/tests/test_risk/test_aggregator.py)
- [risk_groups.toml](/Users/ohayotaro/claude-finance/config/risk_groups.toml)
- [DESIGN.md](/Users/ohayotaro/claude-finance/.claude/docs/DESIGN.md)
- [implementation-result.md](/Users/ohayotaro/claude-finance/.claude/tasks/risk-ledger-accounting-001/implementation-result.md)

The unrelated pre-existing `state.json` modification was preserved.

## Material decisions

- SQLite inserts and venue-cursor advancement are one transaction.
- Duplicate fills/cash events are idempotent; conflicting stable identities fail closed.
- PnL uses venue gross realized PnL minus commission/fees plus explicit funding/borrow/cash PnL effects.
- Disabled, deprecated, and retired strategies remain venue-monitored until authoritatively flat.
- Checkpoint and state schemas were bumped to v2 with safe v1 migration.
- Every enforcement metric publishes source, observation timestamp, and age.
- Account-scope, quote-currency, identity, completeness, and schema violations fail closed immediately.
- No venue adapter, network client, dependency, trading action, or Git mutation was introduced.

## Validation

All final commands ran with `UV_OFFLINE=1` and an isolated writable `UV_CACHE_DIR` because the sandbox rejects the default `~/.cache/uv`.

- `uv run --extra dev pytest tests/test_risk/ -v`
  - PASS: 70 passed.
- `uv run --extra dev pytest -m "not integration and not slow"`
  - PASS: 239 passed; baseline was 215 passed.
- `uv run --extra dev ruff check src/ tests/ .claude/hooks/ .claude/scripts/`
  - PASS.
- `uv run --extra dev mypy src/ .claude/scripts/`
  - PASS: 14 source files checked.
- `uv run python -m src.orchestrator.registry audit`
  - PASS: `audit: ok (0 strategies, 0 accounts)`.
- `git diff --check`
  - PASS.

Failing-test-first evidence and all 22 new test names are recorded in the implementation result.

## Acceptance criteria

- AC1: PASS — known-value net PnL, costs, funding, shuffled duplicate replay, and conflict rollback tested.
- AC2: PASS — venue zero and position omission override/prune log telemetry.
- AC3: PASS — disabled/deprecated/retired residual exposure and failed-cycle retention tested.
- AC4: PASS — rotation, truncation, checkpoint restart, late historical fills, and UTC boundaries tested.
- AC5: PASS — schema-v2 provenance, age, stale-source rejection, and NullVenue behavior tested.
- AC6: PASS — example configuration loads and unsafe configurations are rejected.
- AC7: PASS — all required tests, lint, typing, and registry audit pass.
- AC8: PASS — ADR-005 documents the approved accounting model and ADR-004 exception.

## Residual risks and blockers

- No real venue adapter exists, so venue-specific cursor and normalized realized-PnL behavior remains unvalidated.
- Ledger retention and compaction remain deferred.
- Multi-currency and cross-account conversion remain unsupported and fail closed.
- Future adapters must implement the expanded ledger-batch protocol.
- Independent T3 review and PM acceptance remain separate workflow steps; there is no implementation blocker.