---
name: optimize
description: PM intake for parameter optimization with walk-forward and overfitting controls.
allowed-tools: "Bash(python3 *) Read Write Edit Glob Grep"
---

# Optimize

Optimization work is T2 because it changes or validates trading logic evidence.

## Intake

- Require `strategy_id`; record parameters, ranges, constraints, objective, sample period, IS/OOS windows, and computational budget.
- Define transaction costs, slippage, turnover, and minimum trade count.
- Identify whether output may affect live promotion.

## Acceptance Checklist

- AC includes walk-forward validation and OOS performance.
- AC includes overfitting checks, parameter stability, and multiple-comparison adjustment.
- AC includes cost/turnover sensitivity.
- AC includes rejected-parameter rationale and reproducible random seeds.
- AC includes saved optimization artifacts under the strategy report path.

## Delegation

Create the task brief and run the T2 flow. Treat live-promotion decisions as T3.
