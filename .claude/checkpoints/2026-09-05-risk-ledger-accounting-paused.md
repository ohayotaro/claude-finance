# Checkpoint: risk-ledger-accounting-001 paused after eighth review

Date: 2026-09-05

## State

- Roadmap `.codex/plans/repository-improvement-roadmap.md` committed;
  Step 1-2 (risk accounting) in progress as task
  `risk-ledger-accounting-001` (T3, user-approved implementation).
- Cycle history: plan -> impl -> review x8 with corrections passes C, D,
  E, F, G, H, I (brief Addenda 1-7). Findings per review: 8, 3, 4, 4, 5,
  3, 6, 2. No Critical since review 4.
- Working tree holds the uncommitted implementation: `src/risk/ledger.py`
  (new), `src/risk/aggregator.py`, `tests/test_risk/test_ledger.py` (new),
  `tests/test_risk/test_aggregator.py`, `config/risk_groups.toml` (new),
  `.claude/docs/DESIGN.md` (ADR-005). Fast suite 215 -> 330.
- All PM artifacts (brief, plan, approval, review-1..8,
  implementation-result-1..8, test-evidence) are committed.

## Open

- One High finding (position cut newer than ledger watermark can hide a
  realized loss) and one Low (AC table format). Awaiting user decision:
  one more enumerated corrections pass, accept with recorded limitation,
  or stop.

## Process findings for backlog

- Codex implement phase once wrote `review.md` itself (preserved as
  `implement-phase-wrote-review.md`); runner should prevent this.
- Codex artifacts drifted to Japanese three times and repeatedly omitted
  the required evidence list; PM generated `test-evidence.md` instead.
- Follow-up tasks recorded in the brief: exposure at mark price, ledger
  retention, multi-currency, shared-account cash allocation.
