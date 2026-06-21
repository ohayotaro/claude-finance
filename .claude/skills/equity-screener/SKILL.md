---
name: equity-screener
description: PM intake for equity screening criteria, validation, and implementation.
allowed-tools: "Bash(python3 *) Read Write Edit Glob Grep"
---

# Equity Screener

Equity screener implementation is T2. Live trading or production data mutation makes it T3.

## Intake

- Record universe, market, sector taxonomy, data fields, rebalance cadence, and ranking or filtering method.
- Define point-in-time data requirements and survivorship-bias controls.
- Identify missing-data policy and corporate-action handling.

## Acceptance Checklist

- AC includes no look-ahead or survivorship bias.
- AC includes sector concentration checks and redundant-factor review.
- AC includes threshold sensitivity or stability analysis.
- AC includes source and timestamp evidence for numeric fields.
- AC includes tests with representative fixtures.

## Delegation

Create the task brief and run the T2 flow.
