---
name: dashboard-develop
description: PM intake for dashboards over bot monitoring, backtests, portfolio risk, or research data.
allowed-tools: "Bash(python3 *) Read Write Edit Glob Grep"
---

# Dashboard Develop

Dashboard engineering is T2 when it adds or changes application code. It is T3 if it exposes credentials, external services, or production operational controls.

## Intake

- Define dashboard type: bot monitoring, backtest report, portfolio risk, data quality, or research.
- Record data sources, refresh cadence, access controls, deployment target, and privacy constraints.
- Identify whether charts are generated from structured data only.

## Acceptance Checklist

- AC includes no secrets in rendered pages, logs, or configs.
- AC includes UTC/timezone correctness for time-series displays.
- AC includes large-data handling and deterministic sample fixtures.
- AC includes tests for data transforms and smoke checks for the UI entry point.

## Delegation

Create the task brief and run the T2 flow. Do not deploy or expose externally without explicit T3 approval.
