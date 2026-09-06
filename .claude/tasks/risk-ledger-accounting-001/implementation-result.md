Status: PASS

## Summary

Implemented the approved task through J1-J2. Position snapshots newer than the ledger watermark now fail closed unless the adapter explicitly supplies a historical `as_of_cut` equal to that watermark. Cached caps, PnL, and residual strategies are preserved, and unrealized-PnL provenance retains the true observation timestamp.

No network, trading, credentials, commits, pushes, deployments, or destructive Git operations were used.

## Files changed

- [aggregator.py](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:157)
- [ledger.py](/Users/ohayotaro/claude-finance/src/risk/ledger.py:1)
- [test_aggregator.py](/Users/ohayotaro/claude-finance/tests/test_risk/test_aggregator.py:3293)
- [test_ledger.py](/Users/ohayotaro/claude-finance/tests/test_risk/test_ledger.py:76)
- [risk_groups.toml](/Users/ohayotaro/claude-finance/config/risk_groups.toml:16)
- [DESIGN.md](/Users/ohayotaro/claude-finance/.claude/docs/DESIGN.md:49)
- [test-evidence.md](/Users/ohayotaro/claude-finance/.claude/tasks/risk-ledger-accounting-001/test-evidence.md)
- [implementation-result.md](/Users/ohayotaro/claude-finance/.claude/tasks/risk-ledger-accounting-001/implementation-result.md)

Pre-existing `state.json`, stderr, and review artifacts were preserved. `review.md` was not written.

## Material design decisions

- Unaligned positive position/ledger skew is rejected before ledger mutation.
- `VenuePositionsObservation.as_of_cut` permits explicitly historical position views only when exactly bound to the ledger watermark.
- Older position cuts remain bounded by `accounting_cut_max_skew_s`.
- Unrealized metrics publish the actual position observation time; composite group PnL publishes the enforcement cut.
- Venue/ledger authority, exact Decimal accounting, checkpoint binding, and fail-closed semantics remain intact.

## Validation

All successful `uv` commands used `UV_OFFLINE=1`.

- Baseline fast suite: `330 passed in 6.56s`
- J1 failing-first: `2 failed, 141 deselected in 0.15s`
- J1 after fix: `2 passed, 141 deselected in 0.11s`
- `UV_CACHE_DIR=/private/tmp/claude-finance-uv-cache UV_OFFLINE=1 uv run --extra dev pytest tests/test_risk/ -v`
  - `163 passed in 0.65s`
- `UV_CACHE_DIR=/private/tmp/claude-finance-uv-cache UV_OFFLINE=1 uv run --extra dev pytest -m "not integration and not slow"`
  - `332 passed in 6.55s`
- `UV_CACHE_DIR=/private/tmp/claude-finance-uv-cache UV_OFFLINE=1 uv run --extra dev ruff check src/ tests/ .claude/hooks/ .claude/scripts/`
  - `All checks passed!`
- `UV_CACHE_DIR=/private/tmp/claude-finance-uv-cache UV_OFFLINE=1 uv run --extra dev mypy src/ .claude/scripts/`
  - `Success: no issues found in 14 source files`
- `UV_CACHE_DIR=/private/tmp/claude-finance-uv-cache UV_OFFLINE=1 uv run python -m src.orchestrator.registry audit`
  - `audit: ok (0 strategies, 0 accounts)`
- `git diff --check`
  - Exit `0`, no output; run last.

The unprefixed initial pytest attempt could not access the sandboxed default uv cache; the writable-cache offline rerun passed without downloading anything.

## Acceptance-criteria mapping

- AC1: PASS — ledger known-value, costs, replay, shuffle, identity, and exact-accumulation tests pass.
- AC2: PASS — venue-zero/omission tests and both new J1 common-cut tests pass.
- AC3: PASS — disabled, deprecated, retired, residual, and failed-cycle retention tests pass.
- AC4: PASS — rotation, truncation, restart, late pre-checkpoint fill, UTC-day attribution, and checkpoint recovery tests pass.
- AC5: PASS — metric metadata, stale/log-source consumer detection, recomputed freshness, and truthful J1 provenance tests pass.
- AC6: PASS — the example configuration loads and all safety validations pass.
- AC7: PASS — all required tests, lint, type checking, registry audit, and whitespace checks pass.
- AC8: PASS — ADR-005 documents the accounting model and explicit ADR-004 exception.

Exact AC-to-test-name mappings are in [implementation-result.md](/Users/ohayotaro/claude-finance/.claude/tasks/risk-ledger-accounting-001/implementation-result.md).

## Residual risks, debt, or blockers

- No real venue adapter yet validates venue-specific completeness and normalized PnL.
- Mark-price/current-notional exposure remains deferred.
- Writer locking is host-local and cooperative.
- Ledger compaction, currency conversion, and shared-account cash allocation remain deferred.
- Implementation is complete; final acceptance still requires the scheduled ninth independent review.