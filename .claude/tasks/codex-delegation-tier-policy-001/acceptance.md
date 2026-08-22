# Acceptance: codex-delegation-tier-policy-001

Decision: ACCEPTED (T1, PM acceptance)
Date: 2026-08-22
Accepted by: Claude PM, per user direction in session (policy unification, corrections effort = high, template-first update)

## Evidence

- Implementation result: `implementation-result.md`, Status PASS.
- Independent PM diff review: full `git diff` inspected; content byte-identical to the verbatim block in `brief.md`, placed between `## Runner` and `## Failure Handling`; contract pointer placed at end of `### Model And Effort`.
- AC1-AC4 verified (two files only, additions only, ASCII only).

## Tier record

- Phase ran on light tier (`gpt-5.6-luna`) at `medium` effort per the new policy's T1 doc-only row; selection recorded in `state.json` / `codex-events.jsonl` (`selection_source: cli`).

## Follow-up (out of task scope)

- Runner docs instruct `python3 .claude/scripts/codex_handoff.py ...`, which fails on macOS system Python 3.9 (`datetime.UTC` requires 3.11+). First invocation this session hit this; workaround is `uv run python`. Candidate T1: update docs or add an interpreter version guard.
