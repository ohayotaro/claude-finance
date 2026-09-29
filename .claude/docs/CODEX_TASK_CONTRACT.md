# Codex Task Contract

This repository uses a two-provider workflow:

- Claude is the Japanese-speaking PM and the implementer: it scopes work, writes code and tests, runs validation, manages Git, and owns acceptance.
- Codex is the independent reviewer. It may also produce an optional plan for large or unfamiliar designs, or take a delegated implementation when the user asks for it.

The goal is fast delivery with one independent check where it matters, not a document relay. Claude does not write briefs or run Codex for work that does not need them.

## Risk Tiers

| Tier | Workflow |
|---|---|
| T0 | Advisory or read-only. Claude answers directly. |
| T1 | Low-risk localized change. Claude implements, runs validation, self-reviews, and commits. No brief or Codex review is required. |
| T2 | Code, multi-file, architecture, algorithms, or financial logic. Claude writes a brief, implements, validates, writes the implementation result, then runs a fresh Codex review and accepts once no blocking findings remain. An optional Codex plan may precede implementation. |
| T3 | Live trading, execution/risk controls, secrets/auth, deployment, external side effects, or schema/data migration. T2 flow plus explicit user approval before implementation or any external action, recorded in `approval.md`. Automated live execution remains prohibited. |

Risk classification is a PM judgment. Hooks enforce only deterministic safety and integrity rules.

## Task Directory

For T2 and T3, create `.claude/tasks/<task-id>/brief.md`. Task artifacts are tracked in Git for auditability, except `.claude/tasks/*/codex-events.jsonl`, which remains local because it is a large machine replay log. No task artifact may contain secrets.

### Brief Schema

```markdown
# <task-id>: <title>

Revision: <n> (<YYYY-MM-DD>)

## Objective
<User outcome.>

## Scope
<Included work.>

## Non-Goals
<Explicitly excluded work.>

## Acceptance Criteria
- AC1: <Stable, testable criterion.>
- AC2: <Stable, testable criterion.>

## Constraints And Context
<Business constraints and relevant repository context.>

## Risk Tier
T<n> - <rationale>

## Required Validation
<Commands in a bash fence, plus any audits, evidence, or manual checks required.>

## Forbidden Actions
<Actions that must not happen.>

## Open Decisions Or Blockers
<Unknowns requiring user decision.>
```

Keep the brief short: acceptance criteria and constraints, not implementation instructions.

### Brief Revisions

`brief.md` always states the current consolidated specification. When a decision changes, edit the brief in place, bump `Revision:`, and record the superseded decision with its date in `approval.md` (T3) or `acceptance.md`. Never append addenda that leave superseded text in the brief: every reviewer reads the brief cold.

If the network is required for Codex, state `Network access: required`. The runner fails closed because network is not enabled.

## Implementation Result

After implementing and validating, Claude writes `implementation-result.md` in the task directory. It is the reviewer's entry point and must include:

- Status: `PASS`, `PARTIAL`, or `BLOCKED`
- Summary
- Files changed
- Material design decisions
- Exact validation commands and results
- Acceptance-criteria mapping
- Residual risks, debt, or blockers

## Review

The reviewer is a fresh ephemeral Codex invocation and never receives the implementation transcript. It reads the brief, the plan if one exists, `implementation-result.md`, the delta scope file for delta reviews, the repository, and the diff.

### Runner Validation

The Codex review sandbox is read-only, so the reviewer cannot run commands that write caches or temp files. Instead, before invoking the reviewer, the runner executes the commands in bash fences under the brief's `## Required Validation` (every such section), writes the output to `review-validation.md`, and passes it to the reviewer as runner-executed evidence. Commands run without a shell and must match an allowlist (`uv run [--extra dev] pytest|ruff|mypy`, `uv run --extra dev python -m pytest`, `uv run python -m src.orchestrator.registry audit`, `git diff`, `git status`); any other command, environment assignment, or shell syntax fails the review closed before Codex starts. A failing validation command is a blocking finding.

### Findings

Every finding carries:

- Severity: `Critical`, `High`, `Medium`, or `Low`.
- Disposition: `blocking` or `follow-up`. A finding is blocking if and only if its severity is Critical or High, or it directly violates a stated acceptance criterion, or a required validation command fails, or it weakens a financial safeguard (look-ahead bias, costs/slippage, IS/OOS separation, risk controls, UTC handling, numerical precision). Everything else is a follow-up.
- Origin: `new`, or `carried` when it restates a finding from the previous round.

### Verdict

`CHANGES_REQUIRED` if and only if at least one blocking finding exists; otherwise `APPROVE`. Follow-ups never block acceptance. Claude lists them in `acceptance.md` and decides whether to fix them now or track them.

### Review Output

`review.md` must include the verdict, blocking findings and follow-ups (each with severity, origin, and file and line references), acceptance-criteria gaps, validation commands run with results, and residual financial, operational, security, and regression risks. When a new review runs, the runner moves the previous `review.md` to the next free `review-<n>.md`.

### Scopes And Rounds

- The first review of a task is `full`: the whole diff against the brief.
- After corrections, re-review with `--scope delta`. Claude writes `review-scope.md` listing the blocking findings addressed and the files touched; the reviewer checks those findings plus regressions in the touched files and reports anything else only if it is blocking. The runner fails closed when `review-scope.md` is missing.
- If intermediate rounds were delta reviews, run one final `full` review before accepting T3 work. For T2, a delta `APPROVE` is sufficient when the corrections touched only the files in scope.
- Stop rule: after the third `CHANGES_REQUIRED` verdict in one task (all scopes counted), Claude stops and reports the cycle history and options to the user before any further round.

## Optional Plan

For large or unfamiliar designs, Claude may run `plan` to get a read-only Codex design before implementing. For T2 and T3 this is optional; Claude decides based on design uncertainty, not by default.

## Delegated Implementation

When the user asks for it, `implement` runs Codex in a workspace-write sandbox. For T2 and T3, it requires `plan.md` and `approval.md` first. Codex writes `implementation-result.md` itself in this mode.

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

The runner centralizes Codex flags, uses stdin prompts, strict config, phase-specific sandboxing, a non-interactive approval policy, ephemeral invocations, append-only event logs, output files, state tracking, and Git metadata. It never enables network access and never uses deprecated automation or sandbox-bypass flags.

### Model And Effort

Phase commands may select a Codex model and reasoning effort without changing prompt content or phase contracts.

Model precedence, highest to lowest:

1. CLI: `--model`
2. Phase env: `CODEX_PLAN_MODEL`, `CODEX_IMPLEMENT_MODEL`, `CODEX_REVIEW_MODEL`
3. General env: `CODEX_MODEL`
4. Optional T0 read-only env: `CODEX_FAST_MODEL`
5. Omitted model flag, allowing the Codex CLI configured default

Effort precedence, highest to lowest:

1. CLI: `--effort`
2. Phase env: `CODEX_PLAN_EFFORT`, `CODEX_IMPLEMENT_EFFORT`, `CODEX_REVIEW_EFFORT`
3. General env: `CODEX_EFFORT`
4. Default matrix from the brief risk tier

Valid effort values are `minimal`, `low`, `medium`, `high`, and `xhigh`. The runner passes effort with a Codex config override and rejects unknown values before invoking Codex.

| Risk tier | Default effort |
|---|---|
| T0 | `medium` |
| T1 | `medium` |
| T2 | `high` |
| T3 | `xhigh`; `high` for delta reviews |

T3 plan, implement, and full review fail closed unless the resolved effort is `xhigh`; T3 delta reviews fail closed below `high`. A lower phase or general env effort is rejected. A lower CLI effort is treated as a deliberate operator override.

`state.json` and phase markers in `codex-events.jsonl` record `review_scope`, `requested_model`, `resolved_model`, `requested_effort`, `resolved_effort`, and `selection_source`.

PM tier selection practice (which model and effort to request per phase kind) is defined in `.claude/rules/codex-delegation.md` under "Model And Effort Tier Policy".

### Background Execution

`review`, `plan`, and `implement` are normal foreground OS processes that Claude may launch through Claude Code's native background Bash execution. The runner does not use `nohup`, shell `&`, daemonization, PID supervision, or process signaling. Claude Code owns background task lifecycle management.

`cancel` only writes `status: cancelled` to `state.json`; it does not kill a running Codex process.

### Task Artifacts

Each task directory may contain:

- `brief.md` - Claude-authored task brief (current consolidated spec).
- `plan.md` - optional Codex plan output.
- `approval.md` - T3 user approval and superseded-decision history; also required before a delegated T2/T3 `implement`.
- `implementation-result.md` - implementation output (Claude, or Codex when delegated).
- `review-scope.md` - Claude-written scope for a delta review.
- `review-validation.md` - runner-executed validation evidence for the latest review.
- `review.md` - latest fresh Codex review; earlier rounds are kept as `review-<n>.md`.
- `acceptance.md` - Claude acceptance note, including accepted follow-ups.
- `state.json` - current or last phase state: task ID, phase, status, review scope, timestamps, PID, exit code, Git before/after, and result path.
- `codex-events.jsonl` - consolidated append-only operational event log with phase markers.
- `codex-<phase>.stderr.txt` - stderr capture when a phase writes non-empty stderr.

`status` prints `state.json` without modifying files. `collect` prints the current or last phase result artifact referenced by `state.json` without modifying files.
