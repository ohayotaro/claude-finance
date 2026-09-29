# Codex Delegation Rules

Claude implements repository changes and owns the task brief, risk tier, approval gates, Git, and final acceptance. Codex is the independent reviewer; it can also produce an optional plan or take a delegated implementation when the user asks for it.

## Canonical Contract

Use `.claude/docs/CODEX_TASK_CONTRACT.md` for the task schema, risk tiers, review rules, and runner usage. Do not duplicate large prompts in skills or hooks.

## Workflow

1. T0: answer directly.
2. T1: implement, run validation, self-review, commit. No brief and no Codex review.
3. T2: write a short `brief.md`, implement, validate, write `implementation-result.md`, run a `full` Codex review, fix blocking findings, re-review with `--scope delta`, then accept. Run `plan` first only when the design is large or uncertain.
4. T3: T2 flow plus explicit user approval before implementation or any external action, recorded in `approval.md`, and a final `full` review before acceptance.

Keep the brief as the current consolidated spec (edit in place, bump `Revision:`). Superseded decisions go to `approval.md` or `acceptance.md`, never as addenda in the brief.

## Review Convergence

- Every finding has a severity, a disposition, and an origin (`new` or `carried`). A finding is blocking if and only if it is Critical or High, directly violates a stated acceptance criterion, is a failing required validation command, or weakens a financial safeguard; any severity can therefore be blocking. All other findings are follow-ups: list them in `acceptance.md`, fix them now if cheap, otherwise track them.
- `CHANGES_REQUIRED` if and only if at least one blocking finding exists; otherwise `APPROVE`.
- Re-reviews after corrections use `--scope delta` with a `review-scope.md` listing the addressed findings and touched files.
- Stop rule: after the third `CHANGES_REQUIRED` verdict in one task, stop and report the cycle history and options to the user before another round.
- If reviews keep finding new issues in one large module, treat the module size as the problem and propose a decomposition rather than another round.

## Runner

```bash
uv run python .claude/scripts/codex_handoff.py review <task-id>
uv run python .claude/scripts/codex_handoff.py review <task-id> --scope delta
uv run python .claude/scripts/codex_handoff.py plan <task-id>
uv run python .claude/scripts/codex_handoff.py implement <task-id>
uv run python .claude/scripts/codex_handoff.py status <task-id>
uv run python .claude/scripts/codex_handoff.py collect <task-id>
uv run python .claude/scripts/codex_handoff.py cancel <task-id>
```

The runner requires Python 3.11+ (`datetime.UTC`); `uv run python` guarantees the project interpreter, while a bare `python3` may resolve to an older system Python and fail at import time.

The runner passes prompts through stdin, uses strict config, isolates phases with ephemeral invocations, uses read-only sandboxing for plan and review and workspace-write for delegated implementation, executes the brief's allowlisted Required Validation commands before a review and passes the output to the reviewer (`review-validation.md`), archives the previous `review.md` as `review-<n>.md`, writes `state.json` and an append-only `codex-events.jsonl`, and fails closed on missing prerequisites, empty output, Codex failure, task path traversal, or declared network requirements.

Phase commands accept `--model` and `--effort`; `review` also accepts `--scope full|delta`. CLI values override phase env vars (`CODEX_PLAN_MODEL`, `CODEX_PLAN_EFFORT`, `CODEX_IMPLEMENT_MODEL`, `CODEX_IMPLEMENT_EFFORT`, `CODEX_REVIEW_MODEL`, `CODEX_REVIEW_EFFORT`), which override general env vars (`CODEX_MODEL`, `CODEX_EFFORT`). If no model is set, the runner omits the model flag. If no effort is set, the runner applies the default effort matrix from the task risk tier and records the source in `state.json` and `codex-events.jsonl`.

Run reviews through Claude Code background Bash execution and keep working while they run. The runner itself does not daemonize, detach, kill processes, or manage background PIDs. `status` and `collect` are read-only; `cancel` only marks `state.json` as cancelled.

## Model And Effort Tier Policy

The Codex CLI global default (`~/.codex/config.toml`) is the strongest model tier at high effort, so any phase that omits `--model` runs at maximum token cost. Tiers are roles, not fixed model IDs; update the mapping when the Codex CLI model lineup changes.

| Tier | Role | Current mapping (2026-09) |
|---|---|---|
| strong | Highest capability, CLI configured default | `gpt-6-astra` (omit `--model`) |
| mid | Bounded, fully-specified work | `gpt-6-sol` |
| light | Trivial mechanical work | `gpt-6-luna` |

| Phase kind | Model | Effort |
|---|---|---|
| Review, `full` scope | strong | default matrix (T2 `high`, T3 `xhigh`) |
| Review, `delta` scope | strong | default matrix (T2 `high`, T3 `high`) |
| Optional plan | strong | default matrix |
| Delegated implementation | strong | default matrix |
| Delegated corrections implementation (every finding enumerated) | mid | `high` |

Rules:

1. Any review whose verdict is used for acceptance runs on the strong tier. Delta scope keeps it cheap; the model tier is not economized.
2. T3 plan, delegated implementation, and full review fail closed below `xhigh`; T3 delta reviews fail closed below `high`.
3. Escalation is one-way per item within a cycle: if a mid-tier output is defective, that item re-runs on the strong tier.
4. Record the chosen tier in `acceptance.md` whenever it deviates from the defaults.
5. For fail-closed or security-sensitive changes, self-check the known failure classes before the first review (identity binding, fail-closed inspections, TOCTOU, cache trust, boundary exactness, reserved names, duplicate keys) to reduce review round-trips.

## Git Cadence

Commit PM artifacts at cycle boundaries only: the implementation plus its first review, user approval gates, stop-rule reports, and acceptance. Do not create a separate commit for every intermediate review or corrections pass.

## Failure Handling

If Codex fails, do not silently continue. Report:

- Phase and task ID
- Exit status or runner error
- Missing prerequisite or validation gap
- Whether the task is `BLOCKED`, needs a revised brief, or needs explicit user approval

Acceptance criteria may not be relaxed without updating the brief and telling the user.
