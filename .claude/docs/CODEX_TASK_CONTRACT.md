# Codex Task Contract

This repository uses a two-provider workflow:

- Claude Opus is the Japanese-speaking PM, change controller, approval gate, and acceptance owner.
- Codex is the technical lead, codebase explorer, architect, implementer, test executor, and independent reviewer.

Claude creates neutral task artifacts under `.claude/tasks/<task-id>/`. Codex receives those artifacts through `.claude/scripts/codex_handoff.py`.

## Risk Tiers

| Tier | Workflow |
|---|---|
| T0 | Advisory or no repository mutation. Claude answers directly; read-only Codex is used only when repository inspection is substantial. |
| T1 | Low-risk localized change. One Codex implementation run with tests and self-review; Claude performs acceptance. |
| T2 | Code, multi-file, architecture, algorithms, or financial logic. Fresh read-only Codex plan, Claude approval, fresh Codex implementation, fresh read-only Codex review, then Claude acceptance. |
| T3 | Live trading, execution/risk controls, secrets/auth, deployment, external side effects, or schema/data migration. T2 flow plus explicit user approval before implementation or external action. Automated live execution remains prohibited. |

Risk classification is a PM judgment. Hooks enforce only deterministic safety and integrity rules.

## Task Directory

Create `.claude/tasks/<task-id>/brief.md`. The directory is gitignored and must contain no secrets.

### Brief Schema

```markdown
# <task-id>: <title>

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
<Commands, audits, evidence, or manual checks required.>

## Forbidden Actions
<Actions Codex must not take.>

## Open Decisions Or Blockers
<Unknowns requiring PM or user decision.>
```

If network access is required, state `Network access: required`. The runner fails closed because network is not enabled by default.

## Plan Output

Codex plan output is saved as `plan.md` and must include:

- Recommended design and rationale
- Alternatives considered
- Impacted files and components
- Implementation sequence
- Test and validation plan
- Risks and blockers
- Mapping to every acceptance criterion

For T2 and T3, Claude must approve the plan by writing `approval.md` before implementation.

## Implementation Output

Codex implementation output is saved as the Markdown artifact with stem `implementation-result` and must include:

- Status: `PASS`, `PARTIAL`, or `BLOCKED`
- Summary
- Files changed
- Material design decisions
- Exact validation commands and results
- Acceptance-criteria mapping
- Residual risks, debt, or blockers

## Review Output

Codex review output is saved as `review.md` and must include:

- Verdict: `APPROVE` or `CHANGES_REQUIRED`
- Findings by severity with file and line references where applicable
- Acceptance-criteria gaps
- Validation gaps
- Residual financial, operational, security, and regression risks

The reviewer must be a fresh Codex invocation and must not receive the implementation transcript. It may read only the brief, approved plan, implementation result, repository, and diff.

## Runner

Use:

```bash
python3 .claude/scripts/codex_handoff.py plan <task-id>
python3 .claude/scripts/codex_handoff.py implement <task-id>
python3 .claude/scripts/codex_handoff.py review <task-id>
python3 .claude/scripts/codex_handoff.py status <task-id>
python3 .claude/scripts/codex_handoff.py collect <task-id>
python3 .claude/scripts/codex_handoff.py cancel <task-id>
```

The runner centralizes Codex flags, uses stdin prompts, strict config, phase-specific sandboxing, non-interactive approval policy, ephemeral invocations, append-only event logs, output files, state tracking, and Git metadata. It never enables network access by default and never uses deprecated automation or sandbox-bypass flags.

### Background Execution

`plan` runs in the foreground because Claude must inspect and approve the plan before implementation. `implement` and `review` are normal foreground OS processes designed to be launched through Claude Code's native background Bash execution. The runner does not use `nohup`, shell `&`, daemonization, PID supervision, or process signaling. Claude Code owns background task lifecycle management.

`cancel` only writes `status: cancelled` to `state.json`; it does not kill a running Codex process.

### Task Artifacts

Each task directory may contain:

- `brief.md` - PM-authored task brief.
- `plan.md` - Codex plan output.
- `approval.md` - Claude approval required before T2/T3 implementation.
- `implementation-result` + `.md` - Codex implementation output.
- `review.md` - fresh Codex review output.
- `state.json` - current or last phase state: task ID, phase, status, timestamps, PID, exit code, Git before/after, and result path.
- `codex-events.jsonl` - consolidated append-only operational event log with phase markers.
- `codex-<phase>.stderr.txt` - stderr capture when a phase writes non-empty stderr.

`status` prints `state.json` without modifying files. `collect` prints the current or last phase result artifact referenced by `state.json` without modifying files.
