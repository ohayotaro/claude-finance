Status: PASS

## Summary

Implemented the venue-reconciled ledger and all approved C1–C8 corrections. Risk enforcement now uses:

- SQLite fill/cash-event ledger for realized PnL.
- Fresh, complete venue observations for positions and orders.
- Venue-only unrealized PnL and exposure.
- Ledger-bound checkpoint schema v3 with cached-state recovery.
- Consumer-recomputed metric freshness using `as_of_ts` and `published_at`.
- Fail-closed handling for stale/incomplete data, unsafe paths, invalid configuration, and identity conflicts.

No network access, trading, credentials, dependency changes, commits, or forbidden-file edits occurred.

## Files changed

- [aggregator.py](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:137)
- [ledger.py](/Users/ohayotaro/claude-finance/src/risk/ledger.py:125)
- [test_aggregator.py](/Users/ohayotaro/claude-finance/tests/test_risk/test_aggregator.py:1803)
- [test_ledger.py](/Users/ohayotaro/claude-finance/tests/test_risk/test_ledger.py:74)
- [risk_groups.toml](/Users/ohayotaro/claude-finance/config/risk_groups.toml:1)
- [DESIGN.md](/Users/ohayotaro/claude-finance/.claude/docs/DESIGN.md:44)
- [implementation-result.md](/Users/ohayotaro/claude-finance/.claude/tasks/risk-ledger-accounting-001/implementation-result.md:1)

The pre-existing modified task `state.json` was preserved without editing.

## Material design decisions

- Ledger events and the venue cursor/generation commit transactionally.
- Checkpoints bind to that cursor/generation and are saved before state publication.
- Position and order observations have independent timestamps, completeness, and authority.
- Stale or incomplete cycles preserve cached caps, exposure, PnL, residual strategies, and HWM.
- Stored metric age is informational; consumers recompute age using their own UTC clock.
- Risk-group paths require a safe slug and pass a resolved common-path check.
- Checkpoint v1/v2 migration remains fail-closed until refreshed authoritatively.

## Validation

All commands ran with `UV_OFFLINE=1`.

- Baseline fast suite: `239 passed in 6.44s`
- `UV_OFFLINE=1 UV_CACHE_DIR=/private/tmp/risk-ledger-uv-cache uv run --extra dev pytest tests/test_risk/ -v`
  - PASS: `85 passed in 0.42s`
- `UV_OFFLINE=1 UV_CACHE_DIR=/private/tmp/risk-ledger-uv-cache uv run --extra dev pytest -m "not integration and not slow"`
  - PASS: `254 passed in 6.49s`
- `UV_OFFLINE=1 UV_CACHE_DIR=/private/tmp/risk-ledger-uv-cache uv run --extra dev ruff check src/ tests/ .claude/hooks/ .claude/scripts/`
  - PASS: `All checks passed!`
- `UV_OFFLINE=1 UV_CACHE_DIR=/private/tmp/risk-ledger-uv-cache uv run --extra dev mypy src/ .claude/scripts/`
  - PASS: `Success: no issues found in 14 source files`
- `UV_OFFLINE=1 UV_CACHE_DIR=/private/tmp/risk-ledger-uv-cache uv run python -m src.orchestrator.registry audit`
  - PASS: `audit: ok (0 strategies, 0 accounts)`
- `git diff --check`
  - PASS

## Acceptance-criteria mapping

- AC1: PASS — known-value costs/funding, shuffled replay, and identity-conflict tests.
- AC2: PASS — venue-zero and position-omission tests.
- AC3: PASS — disabled/deprecated residual and incomplete/stale observation tests.
- AC4: PASS — rotation, truncation, restart, late fill, UTC attribution, ledger/checkpoint crash, and cached restart tests.
- AC5: PASS — schema-v2 metadata, `published_at`, consumer-clock freshness, independent observation-age, and non-authoritative-source tests.
- AC6: PASS — example config, finite-value validation, quote currency, slug, and path-confinement tests.
- AC7: PASS — all required test, lint, type, and audit commands pass; complete failing-first and legacy-test evidence is in the implementation result.
- AC8: PASS — ADR-005 documents the model and explicit ADR-004 exception.

## Residual risks and blockers

- No real venue adapter exists, so venue-specific cursor and normalized-PnL behavior remains unvalidated.
- Ledger retention/compaction is deferred.
- Multi-account currency conversion remains unsupported and fail-closed.
- A fresh independent T3 review and PM acceptance remain pending; implementation itself is not blocked.