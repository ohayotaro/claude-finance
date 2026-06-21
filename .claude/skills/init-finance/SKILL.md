---
name: init-finance
description: PM intake for initializing or updating project finance identity, commands, and directory conventions.
allowed-tools: "Bash(python3 *) Read Write Edit Glob Grep"
---

# Init Finance

Initialization is T1 for PM-only project identity updates and T2 when it scaffolds or changes repository files.

## Intake

- Record markets, data sources, execution platforms, backtest frameworks, deployment style, primary/secondary languages, and project-specific commands.
- Preserve existing strategy registry, risk settings, state, logs, reports, and user project code.
- Identify whether the change touches runtime code, CI, hooks, or template-managed files.

## Acceptance Checklist

- AC includes updated Zone B or project-specific Codex notes only when requested.
- AC includes multi-strategy directory conventions and registry ownership.
- AC includes no secrets and no live-trading enablement.
- AC includes validation commands for any scaffolding or config changes.

## Delegation

For PM-only notes, write allowed orchestration artifacts. For repository changes, create a task brief and use `/codex-task`.
