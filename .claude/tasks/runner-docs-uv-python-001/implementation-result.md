Status: PASS

Summary: Updated all runner documentation to use `uv run python`; added the required Python 3.11+ notes.

Files changed:

- [README.md](/Users/ohayotaro/claude-finance/README.md)
- [.claude/docs/CODEX_TASK_CONTRACT.md](/Users/ohayotaro/claude-finance/.claude/docs/CODEX_TASK_CONTRACT.md)
- [.claude/rules/codex-delegation.md](/Users/ohayotaro/claude-finance/.claude/rules/codex-delegation.md)
- [.claude/skills/codex-task/SKILL.md](/Users/ohayotaro/claude-finance/.claude/skills/codex-task/SKILL.md)
- [.claude/skills/codex-review/SKILL.md](/Users/ohayotaro/claude-finance/.claude/skills/codex-review/SKILL.md)

Material design decisions: Mechanical replacements only; preserved unrelated existing changes in the two already-dirty files. No network, runtime, hooks, or production actions.

Validation:

- AC1 grep: 0 matches outside `.claude/tasks/`
- AC2 replacement count: 26 total
- AC3 note count: exactly once per required file; immediately follows each runner block
- AC4 `git diff --name-only`: exactly 5 target files
- AC5 changed lines: ASCII-only; no whitespace errors via `git diff --check`
- No automated tests run because this is documentation-only.

Residual risks: None identified. Existing task-brief references to the old command remain intentionally under `.claude/tasks/`.