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

## Update after ninth review (2026-09-05)

- User approved one more corrections pass (Addendum 8, J1-J2). Ninth
  review: CHANGES_REQUIRED (High checkpoint semantic trust, High startup
  refusal publication, two Low). Loop stopped; awaiting user decision.
- Fast suite now 332 passed on the real machine. Findings per review:
  8, 3, 4, 4, 5, 3, 6, 2, 4.
- Recommended path recorded in approval.md: bounded follow-up task
  `risk-ledger-accounting-002` including an aggregator decomposition
  plan.

## Task 002 status (2026-09-06)

- 002 plan approved (PM and user). Implementation done: Part A fixes plus
  decomposition into config/observations/accounting/persistence/
  publication with aggregator.py as a 553-line facade; tests split along
  the same lines. Fast suite 358, risk 189, all budgets and inward
  dependencies verified by the PM.
- Review 1: CHANGES_REQUIRED (Medium x2, Low). Corrections pass K1-K3
  done. Review 2: CHANGES_REQUIRED (High null-day checkpoint bypass, Low
  artifact). Stopped per the one-pass policy; awaiting user decision.
- Working tree still holds all 001+002 code uncommitted.

## Acceptance (2026-09-06)

- Task 002 ACCEPTED after the fourth review (single Low, artifact format).
  Task 001 implementation is accepted transitively as the base of 002.
- Committed as one feat commit with all task artifacts. Roadmap Steps 1-2
  (risk accounting) are done; next roadmap step is 3 (versioned data,
  experiment-manifest, and backtest-result schemas).
