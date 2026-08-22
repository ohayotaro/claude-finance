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
uv run python .claude/scripts/codex_handoff.py plan <task-id>
uv run python .claude/scripts/codex_handoff.py implement <task-id>
uv run python .claude/scripts/codex_handoff.py review <task-id>
uv run python .claude/scripts/codex_handoff.py status <task-id>
uv run python .claude/scripts/codex_handoff.py collect <task-id>
uv run python .claude/scripts/codex_handoff.py cancel <task-id>
```

The runner requires Python 3.11+ (`datetime.UTC`); `uv run python` guarantees the project interpreter, while a bare `python3` may resolve to an older system Python and fail at import time.

The runner passes prompts through stdin, uses strict config, isolates phases with ephemeral invocations, uses read-only sandboxing for plan/review, uses workspace-write for implementation, writes `plan.md`, the `implementation-result` Markdown artifact, `review.md`, `state.json`, and an append-only `codex-events.jsonl`, and fails closed on missing prerequisites, empty output, Codex failure, task path traversal, or declared network requirements.

Phase commands accept `--model` and `--effort`. CLI values override phase env vars (`CODEX_PLAN_MODEL`, `CODEX_PLAN_EFFORT`, `CODEX_IMPLEMENT_MODEL`, `CODEX_IMPLEMENT_EFFORT`, `CODEX_REVIEW_MODEL`, `CODEX_REVIEW_EFFORT`), which override general env vars (`CODEX_MODEL`, `CODEX_EFFORT`). If no model is set, the runner omits the model flag. If no effort is set, the runner applies the default effort matrix from the task risk tier and records the source in `state.json` and `codex-events.jsonl`.

Run `implement` and `review` through Claude Code background Bash execution when long-running work should continue asynchronously. The runner itself does not daemonize, detach, kill processes, or manage background PIDs. `status` and `collect` are read-only; `cancel` only marks `state.json` as cancelled.

## Model And Effort Tier Policy

The Codex CLI global default (`~/.codex/config.toml`) is the strongest model tier at high effort, so any phase that omits `--model` runs at maximum token cost. Phase commands therefore select a model tier and effort by phase kind. Tiers are roles, not fixed model IDs; update the mapping when the Codex CLI model lineup changes.

| Tier | Role | Current mapping (2026-08) |
|---|---|---|
| strong | Highest capability, CLI configured default | `gpt-5.6-sol` (omit `--model`) |
| mid | Bounded, fully-specified work | `gpt-5.6-terra` |
| light | Trivial mechanical work | `gpt-5.6-luna` |

| Phase kind | Model | Effort |
|---|---|---|
| Plan | strong | default matrix |
| First implementation | strong | default matrix |
| First review | strong | default matrix |
| Corrections implementation (every finding enumerated, design approved) | mid | `high` |
| Intermediate delta re-review (diff-scoped: findings list plus touched files) | mid | `medium` |
| Final pre-acceptance review (full scope) | strong | `high` |
| T1 doc-only or trivial mechanical implementation | light | `medium` |

Rules:

1. The final review before any T2 acceptance always runs on the strong tier at `high` effort. The last gate is never economized; a false PASS costs the most there.
2. A corrections implementation drops to the mid tier only when every finding is enumerated with an approved design. Open-ended design work stays on the strong tier.
3. Delta re-reviews must be scoped in a PM addendum (findings list plus regression on touched files) so the smaller model reviews a bounded surface. The full-scope pass still happens at the final gate.
4. Escalation is one-way per item within a cycle: if a mid or light tier output is defective, that item re-runs one tier up.
5. Record the chosen tier in the task approval addendum whenever it deviates from the defaults, so acceptance records show which gate ran on which tier.
6. This policy applies to T1 and T2 phases only. T3 phases keep the `xhigh` fail-closed rule from the task contract.
7. Briefs carry the known-failure-class checklist (identity binding, fail-closed inspections, TOCTOU, cache trust, boundary exactness, reserved names, duplicate keys) to reduce review round-trips.

## Failure Handling

If Codex fails, do not silently continue. Report:

- Phase and task ID
- Exit status or runner error
- Missing prerequisite or validation gap
- Whether the task is `BLOCKED`, needs a revised brief, or needs explicit user approval

Acceptance criteria may not be relaxed without updating the brief and getting PM approval.
