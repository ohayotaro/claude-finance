# Checkpoint: updater hardening and PM artifact tracking

Date: 2026-08-22
Session scope: user question about git-tracking PM artifacts and update.sh
knowledge-loss risk led to two accepted T2 tasks.

## Task 1: update-preservation-and-pm-artifact-tracking-001

- Risk tier: T2. Status: ACCEPTED, committed `e40f118` (fix) + `92aba9f`
  (tracking policy), pushed to main.
- Artifacts: `.claude/tasks/update-preservation-and-pm-artifact-tracking-001/`
  (brief.md, plan.md, approval.md incl. acceptance record,
  implementation-result.md, review.md, state.json).
- Outcome: update.sh preserved only Zone B; Zone C, AGENTS.md post-boundary
  content, and (on second run) the fixed-name DESIGN archive were silently
  destroyed. Fixed with fail-closed marker preflight, byte-preserving
  composition, content-addressed DESIGN archives, and a persistent fixture
  validator. `.claude/tasks|checkpoints|plans` are now git-tracked
  (`codex-events.jsonl` excluded); `.claude/state/` and `.claude/logs/`
  remain ignored by design.
- Validation: fixture validator PASS, fast suite 180 passed at acceptance,
  independent review APPROVE (zero findings), PM local re-verification done.

## Task 2: updater-python-consolidation-001

- Risk tier: T2. Status: ACCEPTED, committed `54d7cf7`, pushed to main.
- Artifacts: `.claude/tasks/updater-python-consolidation-001/` (brief.md with
  Addenda 1-2, plan.md, approval.md incl. acceptance record,
  implementation-result.md, review.md, state.json).
- Outcome: single hardened Python updater (`scripts/update.py`, stdlib-only,
  Windows-compatible by construction); `scripts/update.sh` reduced to an
  interpreter-resolving exec wrapper (UPDATER_PYTHON -> python3/python ->
  python3.14..3.11 -> offline `uv python find '>=3.11'`); self-update of
  exactly the three updater files on every run.
- Review history: review 1 CHANGES_REQUIRED (rejection tests not
  parameterized over the wrapper; invalid AC5 grep evidence) -> corrections
  (mid tier) -> review 2 APPROVE, but PM real-machine verification caught an
  interpreter-resolution failure (bare python3 is 3.9.6 here; Codex sandbox
  had a newer one) -> Addendum 2 corrections -> review 3 APPROVE ->
  accepted after real-machine re-verification (validator PASS, 208 passed,
  ruff, mypy).
- Process note: one corrections run (background id bgeqpbn6o) was killed
  before writing anything; state.json was marked cancelled and the phase
  re-run cleanly.

## Blockers

None.

## Next actions

1. Downstream sync of `~/btc-bbo-mm` and `~/reactvol-re` (pending user
   go-ahead; downstream pushes require prior confirmation). CRITICAL: never
   run the stale downstream updaters -- bootstrap by copying the template's
   `scripts/update.py`, `scripts/update.sh`,
   `scripts/validate_update_preservation.sh` first, then run the updater.
2. Optional test-debt item from review 2: add a fixture for a pre-existing
   matching DESIGN archive while local DESIGN differs from the template
   (non-blocking).
