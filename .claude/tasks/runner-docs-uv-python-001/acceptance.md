# Acceptance: runner-docs-uv-python-001

Decision: ACCEPTED (T1, PM acceptance)
Date: 2026-08-22
Accepted by: Claude PM, per user direction in session ("fix this project's docs")

## Evidence

- Implementation result: `implementation-result.md`, Status PASS.
- PM verification (independent grep/diff):
  - AC1: 0 remaining `python3 .claude/scripts/codex_handoff.py` outside `.claude/tasks/`.
  - AC2: 26 `uv run python .claude/scripts/codex_handoff.py` occurrences across the five target files.
  - AC3: Python 3.11+ note present exactly once in `.claude/rules/codex-delegation.md` and `.claude/docs/CODEX_TASK_CONTRACT.md`, directly after each runner block (visually confirmed).
  - AC4/AC5: diff limited to the five files; insert/delete counts reconcile with 26 replacements plus two notes on top of the previously accepted tier-policy diff; ASCII only.

## Tier record

- Phase ran on light tier (`gpt-5.6-luna`) at `medium` effort per the Model And Effort Tier Policy (T1 doc-only row).

## Follow-up (optional, not blocking)

- Interpreter version guard inside `codex_handoff.py` (fail with a clear message on Python < 3.11) remains an open T1 candidate.
- Downstream projects (btc-bbo-mm, reactvol-re) still document `python3` invocation; sync pending user confirmation.
