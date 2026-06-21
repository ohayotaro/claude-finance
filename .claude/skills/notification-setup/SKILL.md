---
name: notification-setup
description: PM intake for alert routing, notification integrations, and smoke-test requirements.
allowed-tools: "Bash(python3 *) Read Write Edit Glob Grep"
---

# Notification Setup

Notification work is T2 for code/config changes and T3 when real external channels or credentials are involved.

## Intake

- Record channels, severity mapping, routing by strategy_id/risk_group, rate limits, retries, and deduplication policy.
- Identify credentials and secret storage requirements.
- Define smoke-test scope and non-production test channel if available.

## Acceptance Checklist

- AC includes no committed secrets and no secrets in logs/errors.
- AC includes alert schema, delivery retry behavior, deduplication, and escalation.
- AC includes tests or fixtures for sample bot/risk events.
- AC includes explicit user approval before sending to production channels.

## Delegation

Create the task brief and use T2 or T3 based on external side effects.
