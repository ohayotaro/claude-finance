# codex-delegation-tier-policy-001: Add unified model/effort tier policy to codex-delegation rules

## Objective

Adopt the unified Codex model/effort tier selection policy (agreed by the user on 2026-08-22) into this template repository so downstream projects inherit one canonical policy instead of divergent local memos.

## Scope

1. In `.claude/rules/codex-delegation.md`, insert a new section `## Model And Effort Tier Policy` between the `## Runner` section and the `## Failure Handling` section. The section content is specified verbatim below and must be inserted exactly as written.
2. In `.claude/docs/CODEX_TASK_CONTRACT.md`, at the end of the `### Model And Effort` subsection (after the paragraph beginning "`state.json` and phase start markers"), add this single paragraph:

   PM tier selection practice (which model and effort to request per phase kind) is defined in `.claude/rules/codex-delegation.md` under "Model And Effort Tier Policy".

### Verbatim section content for codex-delegation.md

```markdown
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
```

## Non-Goals

- No changes to `.claude/scripts/codex_handoff.py` or any hook.
- No changes to any other rules file, skill, or source code.
- No renumbering, rewording, or reformatting of existing content in either target file.
- No commits or pushes.

## Acceptance Criteria

- AC1: `.claude/rules/codex-delegation.md` contains the new `## Model And Effort Tier Policy` section, byte-identical to the verbatim block above, placed between `## Runner` and `## Failure Handling`.
- AC2: `.claude/docs/CODEX_TASK_CONTRACT.md` contains the specified one-paragraph pointer at the end of the `### Model And Effort` subsection.
- AC3: `git diff` touches only these two files, and only as additions plus the surrounding blank lines.
- AC4: No emojis or non-ASCII characters are introduced (project language rules).

## Constraints And Context

- This repository is the template origin; downstream projects (btc-bbo-mm, reactvol-re) will receive this file by sync after acceptance.
- The policy text unifies two previously divergent local policies; the corrections-implementation effort was decided as `high` by the user.
- Markdown only; no build or test suite applies to these files beyond lint if configured.

## Risk Tier

T1 - Documentation-only, two files, exact content specified in the brief; no runtime behavior change.

## Required Validation

- `git diff --stat` shows exactly the two target files.
- `grep -n "Model And Effort Tier Policy" .claude/rules/codex-delegation.md .claude/docs/CODEX_TASK_CONTRACT.md` shows the section header and the pointer.
- Visual check that existing sections are unchanged.

## Forbidden Actions

- Editing any file other than the two listed targets.
- Rewriting or "improving" the verbatim section content.
- Git commits, pushes, or branch operations.
- Network access (not required; do not request it).

## Open Decisions Or Blockers

None.
