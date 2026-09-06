# Checkpoint: risk ledger accepted, roadmap Steps 1-2 done

Date: 2026-09-06
Session: https://claude.ai/code/session_01Q9Xwb8P8CpTYjHxnRGSvZz

## Task state

| Task | Tier | Status | Artifacts |
|---|---|---|---|
| risk-ledger-accounting-001 | T3 | Superseded by 002 (NOT ACCEPTED standalone; implementation carried into 002) | `.claude/tasks/risk-ledger-accounting-001/` brief (Addenda 1-8), plan.md, approval.md, review-1..9.md, implementation-result-1..9.md, test-evidence.md, state.json |
| risk-ledger-accounting-002 | T3 | ACCEPTED 2026-09-06, committed `3096f0d`, pushed to origin/main | `.claude/tasks/risk-ledger-accounting-002/` brief (Addenda 1-3), plan.md, approval.md (acceptance section with AC-to-test map), review-1..4.md, implementation-result-1..4.md, test-evidence.md, state.json |

Validation at acceptance (PM, real machine): fast suite 372 passed, risk
suite 203 passed, ruff, mypy (19 files), registry audit, CLI help,
`git diff --check` clean. Module budgets and inward dependency direction
verified. Working tree clean after commit; branch in sync with origin.

## Blockers

None open. Codex-side transient "model at capacity" failure occurred once
on a review phase and was retried successfully.

## Next action

Roadmap Step 3 (`.codex/plans/repository-improvement-roadmap.md`):
define versioned data, experiment-manifest, and backtest-result schemas.
Expected tier T2 (schemas and validation code, no live controls). Write
the brief as `.claude/tasks/research-schemas-001/brief.md` when the user
asks to continue. Blocker recorded in the roadmap still applies: target
market, venue, timeframe, and fundamental provider are not selected;
schemas must stay venue-agnostic.

## Follow-ups recorded (not scheduled)

- Real venue adapter under `src/risk/venues/` (first adapter creates the
  package); validates cursor completeness and normalized realized PnL.
- Exposure at venue mark or current notional instead of entry price.
- Ledger retention and compaction with a finality guarantee.
- Multi-currency and cross-account conversion; shared-account cash
  allocation across risk groups.
- Runner hardening: phase-owned output paths so an implement phase cannot
  write `review.md`; artifact language and ASCII validation; evidence
  table validation. Codex never produced the required evidence table
  across 001 and 002; the PM generated `test-evidence.md` instead.
- `persistence.py` sits at 897 of its 900-line budget.

## Drift detection

- CLAUDE.md Zone C: updated 2026-09-06 (src/risk package protection,
  venue-authoritative accounting decision). Line count checked at this
  checkpoint; see session log.
- DESIGN.md: ADR-005 covers the ledger and the module map; no src module
  without an ADR mention.
- No api_specs exist yet; no CODEX_TASK_CONTRACT drift observed.
