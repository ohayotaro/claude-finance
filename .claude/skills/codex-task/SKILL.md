---
name: codex-task
description: Create and run a canonical Claude PM to Codex engineering task using T0-T3 risk gates.
allowed-tools: "Bash(python3 *) Read Write Edit Glob Grep"
---

# Codex Task

Use this for any repository task that needs substantial inspection, design, implementation, tests, or review.

## Workflow

1. Create `.claude/tasks/<task-id>/brief.md` using `.claude/docs/CODEX_TASK_CONTRACT.md`.
2. Classify risk as T0, T1, T2, or T3 based on scope, financial impact, external effects, secrets, deployment, data migration, and risk-control changes.
3. Add stable acceptance criteria (`AC1`, `AC2`, ...), required validation, and forbidden actions.
4. For T1, run one implementation phase:

```bash
python3 .claude/scripts/codex_handoff.py implement <task-id>
```

5. For T2, run plan, write Claude approval to `approval.md`, run implementation, then run review:

```bash
python3 .claude/scripts/codex_handoff.py plan <task-id>
python3 .claude/scripts/codex_handoff.py implement <task-id>
python3 .claude/scripts/codex_handoff.py review <task-id>
```

6. For T3, obtain explicit user approval before implementation or any external action. Automated live execution remains prohibited.
7. Accept or reject by comparing the brief, Codex result, validation evidence, and independent review.

## PM Rules

- Claude writes only task briefs, approvals, checkpoints, plans, and acceptance notes.
- Do not create a competing technical design before Codex planning.
- Do not relax acceptance criteria silently. Update the brief when scope changes.
- Keep user interaction in Japanese; task artifacts and code may be English.
