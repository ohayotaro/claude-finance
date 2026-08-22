# runner-docs-uv-python-001: Fix runner invocation docs to use uv-managed Python

## Objective

Documentation instructs invoking the Codex runner with `python3 .claude/scripts/codex_handoff.py ...`. On machines where `python3` resolves to an older interpreter (e.g., macOS system Python 3.9), the runner crashes at import time (`datetime.UTC` requires Python 3.11+). This happened in practice on 2026-08-22. Update all docs to the interpreter-safe invocation.

## Scope

1. In the five files below, replace every occurrence of the exact string
   `python3 .claude/scripts/codex_handoff.py`
   with
   `uv run python .claude/scripts/codex_handoff.py`
   (26 occurrences total):
   - `README.md`
   - `.claude/docs/CODEX_TASK_CONTRACT.md`
   - `.claude/rules/codex-delegation.md`
   - `.claude/skills/codex-task/SKILL.md`
   - `.claude/skills/codex-review/SKILL.md`
2. In `.claude/rules/codex-delegation.md`, immediately after the runner command block in the `## Runner` section, add this single line as its own paragraph:

   The runner requires Python 3.11+ (`datetime.UTC`); `uv run python` guarantees the project interpreter, while a bare `python3` may resolve to an older system Python and fail at import time.

3. Add the same single-line paragraph in `.claude/docs/CODEX_TASK_CONTRACT.md`, immediately after the runner command block in its `## Runner` section.

## Non-Goals

- No changes to `.claude/scripts/codex_handoff.py` (an interpreter version guard is a separate task if wanted).
- No changes to hooks or `settings.json` (hook scripts are 3.9-compatible and unaffected).
- No other rewording, reformatting, or content changes in the touched files.
- No commits or pushes.

## Acceptance Criteria

- AC1: `grep -rn "python3 .claude/scripts/codex_handoff.py" --include="*.md" .` returns zero matches outside `.claude/tasks/`.
- AC2: `grep -rc "uv run python .claude/scripts/codex_handoff.py"` over the five files totals 26.
- AC3: The Python 3.11+ note appears exactly once in each of `.claude/rules/codex-delegation.md` and `.claude/docs/CODEX_TASK_CONTRACT.md`, directly after the runner command block.
- AC4: `git diff` touches only the five listed files; no deletions other than the replaced string.
- AC5: ASCII only; no emojis (project language rules).

## Constraints And Context

- This repository is the template origin; downstream projects will receive the change by sync after acceptance.
- The working tree already contains uncommitted accepted changes in `.claude/rules/codex-delegation.md` and `.claude/docs/CODEX_TASK_CONTRACT.md` from task `codex-delegation-tier-policy-001`. Do not revert or modify those sections; only apply the replacements and notes described here.

## Risk Tier

T1 - Documentation-only, mechanical string replacement plus two one-line notes; exact content specified.

## Required Validation

- The grep checks in AC1-AC3.
- `git diff --stat` shows exactly the five target files.

## Forbidden Actions

- Editing any file other than the five listed targets.
- Touching the Model And Effort Tier Policy section content beyond leaving it unchanged.
- Git commits, pushes, or branch operations.
- Network access (not required; do not request it).

## Open Decisions Or Blockers

None.
