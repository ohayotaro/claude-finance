# Codex Delegation Rules

Codex is the technical lead for repository exploration, design, implementation, debugging, tests, and independent review. Claude owns the task brief, risk tier, approval gates, and final acceptance.

## Canonical Contract

Use `.claude/docs/CODEX_TASK_CONTRACT.md` for the task schema, risk tiers, phase outputs, and runner usage. Do not duplicate large prompts in skills or hooks.

## Workflow

1. Claude creates `.claude/tasks/<task-id>/brief.md` with objective, scope, non-goals, acceptance criteria, risk tier, required validation, forbidden actions, and blockers.
2. T1 may run one implementation phase directly when the brief justifies low localized risk.
3. T2 and T3 require `plan.md`, Claude `approval.md`, implementation, independent review, then Claude acceptance.
4. T3 additionally requires explicit user approval before implementation or any external action.

## Runner

```bash
python3 .claude/scripts/codex_handoff.py plan <task-id>
python3 .claude/scripts/codex_handoff.py implement <task-id>
python3 .claude/scripts/codex_handoff.py review <task-id>
```

The runner passes prompts through stdin, uses strict config, isolates phases with ephemeral invocations, uses read-only sandboxing for plan/review, uses workspace-write for implementation, and fails closed on missing prerequisites, empty output, Codex failure, task path traversal, or declared network requirements.

## Failure Handling

If Codex fails, do not silently continue. Report:

- Phase and task ID
- Exit status or runner error
- Missing prerequisite or validation gap
- Whether the task is `BLOCKED`, needs a revised brief, or needs explicit user approval

Acceptance criteria may not be relaxed without updating the brief and getting PM approval.
