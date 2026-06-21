---
name: bot-deploy
description: PM intake for deployment work with live-trading gates, deployment evidence, and Codex execution.
allowed-tools: "Bash(python3 *) Read Write Edit Glob Grep"
---

# Bot Deploy

Deployment is T3 when it can affect live systems, credentials, infrastructure, external services, or trading state. Do not deploy directly from Claude.

## Intake

- Require `strategy_id`; verify registry state is `testnet` or `live`.
- Record deployment target, runtime mode, service name, risk group, account scope, environment file plan, health endpoint, logging path, and rollback plan.
- Identify whether secrets, production credentials, or external side effects are involved.
- Confirm user approval is required before implementation or external action.

## Acceptance Checklist

- AC includes no secrets committed or printed.
- AC includes testnet validation evidence within 7 days for first live promotion.
- AC includes `MAX_POSITION_SIZE`, `MAX_DAILY_LOSS`, stop loss, kill switch test, notification smoke test, and recent risk report.
- AC includes per-strategy Docker/systemd/launchd naming and registry-resolved paths.
- AC includes health checks, logs, rollback, and risk aggregator status.
- AC states that automated live execution remains prohibited.

## Delegation

Create the task brief, run `plan`, obtain Claude and explicit user approval, then run `implement` and `review`. External deployment commands require a separate user gate after Codex produces the plan.
