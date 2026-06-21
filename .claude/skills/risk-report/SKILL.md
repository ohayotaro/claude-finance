---
name: risk-report
description: PM intake for per-strategy and aggregated risk reporting with Codex validation.
allowed-tools: "Bash(python3 *) Read Write Edit Glob Grep"
---

# Risk Report

Risk reporting is T2 and becomes T3 when it changes risk controls, live thresholds, or production enforcement.

## Intake

- Record strategy_id or risk_group, account_scope, date range, positions, trades, balances, and venue reconciliation source.
- Define required metrics: exposure, realized/unrealized PnL, VaR, CVaR, drawdown, correlation, concentration, and margin/leverage.
- Identify whether the report is evidence for deployment or incident recovery.

## Acceptance Checklist

- AC includes venue-reconciled source of truth, not only bot self-reporting.
- AC includes daily PnL UTC-day boundaries and high-water mark handling.
- AC includes per-strategy and aggregated views when applicable.
- AC includes threshold breach interpretation and recommended operator action.
- AC includes tests for known-value calculations and edge cases.

## Delegation

Create the task brief and run the T2 flow. Threshold or enforcement changes require T3 approval.
