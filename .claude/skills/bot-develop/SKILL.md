---
name: bot-develop
description: PM intake for API trading bot engineering with exchange, risk, state, and testnet criteria.
allowed-tools: "Bash(python3 *) Read Write Edit Glob Grep"
---

# Bot Develop

Bot development is T2 by default and T3 if credentials, production endpoints, deployment, or risk-control changes are involved.

## Intake

- Require `strategy_id`; verify registry entry and `runtime = "python"`.
- Record exchange, market type, symbols, execution mode, API documentation status, testnet availability, rate limits, and order lifecycle details.
- Require official API documentation research before implementation. If network research is needed, declare it in the brief and fail closed until explicitly handled.
- Record registry-resolved config, state, database, and log paths.

## Acceptance Checklist

- AC includes `--strategy-id` and registry-resolved paths only.
- AC includes order state machine, partial fills, retries, rate limits, reconciliation, and crash recovery.
- AC includes pre-trade risk gates, stop loss, kill switch, daily loss, and max position controls.
- AC includes structured JSONL logs with `strategy_id` and no secrets.
- AC includes testnet or mocked exchange validation plus unit tests.

## Delegation

Create the task brief and run the T2 flow. For production credentials or live-mode changes, upgrade to T3 and require explicit user approval before implementation.
