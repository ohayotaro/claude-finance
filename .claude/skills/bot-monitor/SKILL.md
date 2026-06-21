---
name: bot-monitor
description: PM intake for bot monitoring, alerting, health checks, and incident visibility.
allowed-tools: "Bash(python3 *) Read Write Edit Glob Grep"
---

# Bot Monitor

Monitoring changes are T2 unless they change production alert routing or external services, which makes them T3.

## Intake

- Require `strategy_id` or state that the scope is portfolio-wide.
- Record expected log paths, health endpoints, heartbeat frequency, alert destinations, and severity mapping.
- Identify operational thresholds for latency, API errors, WebSocket reconnects, stale data, drawdown, and risk gates.

## Acceptance Checklist

- AC includes structured log parsing without secrets.
- AC includes uptime, PnL, open positions, exchange connectivity, heartbeat, and risk-gate status.
- AC includes alert deduplication and escalation policy.
- AC includes tests or replay fixtures for bot events and incident patterns.

## Delegation

Create the brief and use the T2 flow. If alert provider credentials or live notification changes are required, obtain explicit user approval before implementation.
