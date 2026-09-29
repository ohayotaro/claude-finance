---
name: codex-task
description: Run a canonical T0-T3 task where Claude implements and Codex independently reviews.
allowed-tools: "Bash(python3 *) Read Write Edit Glob Grep"
---

# Codex Task

Use this for repository work that needs a risk tier, acceptance criteria, and (for T2/T3) an independent Codex review. The canonical rules are in `.claude/docs/CODEX_TASK_CONTRACT.md`.

## Workflow

1. Classify risk as T0, T1, T2, or T3 based on scope, financial impact, external effects, secrets, deployment, data migration, and risk-control changes.
2. T0: answer directly. T1: implement, run validation, self-review, commit. Stop here.
3. T2/T3: create a short `.claude/tasks/<task-id>/brief.md` with stable acceptance criteria (`AC1`, `AC2`, ...), required validation, and forbidden actions.
4. T3: obtain explicit user approval before implementation or any external action and record it in `approval.md`. Automated live execution remains prohibited.
5. Optional: run `plan` first when the design is large or uncertain.
6. Implement, run the required validation, and write `implementation-result.md` (status, summary, files changed, decisions, exact commands and results, AC mapping, residual risks).
7. Run the review in the background and keep working meanwhile:

```bash
uv run python .claude/scripts/codex_handoff.py review <task-id>
```

8. Fix blocking findings, write `review-scope.md` (findings addressed plus files touched), and re-review:

```bash
uv run python .claude/scripts/codex_handoff.py review <task-id> --scope delta
```

9. T3 only: finish with a `full` review. Accept when no blocking findings remain; write `acceptance.md` with the follow-ups and your decision on each.

Other runner commands: `plan`, `implement` (delegated implementation on user request), `status`, `collect`, `cancel`.

## Rules

- Keep the brief as the current consolidated spec; edit in place and bump `Revision:` instead of appending addenda.
- Only blocking findings stop acceptance. After the third `CHANGES_REQUIRED` in a task, stop and report to the user.
- Do not relax acceptance criteria silently. Update the brief and tell the user when scope changes.
- Keep user interaction in Japanese; task artifacts and code are English.
