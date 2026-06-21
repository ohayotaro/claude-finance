---
name: backtest
description: PM intake for strategy backtest work with financial validation criteria and Codex execution.
allowed-tools: "Bash(python3 *) Read Write Edit Glob Grep"
---

# Backtest

Use `.claude/docs/CODEX_TASK_CONTRACT.md`. Backtest implementation, repair, metric validation, and report generation are normally T2 because they affect financial evidence.

## Intake

- Require `strategy_id`; verify it exists in `config/registry.toml`.
- Record `logic_version`, registry-resolved config/state/log/report paths, data source, timeframe, and benchmark.
- Define IS/OOS split, transaction costs, spread, commission, slippage, initial capital, sizing, and execution assumptions.
- State whether this is research-only, testnet evidence, or a live-promotion prerequisite.

## Acceptance Checklist

- AC includes causal signals with no look-ahead bias.
- AC includes explicit transaction costs and slippage.
- AC includes IS/OOS metrics and degraded-OOS handling.
- AC includes risk metrics: max drawdown, Sharpe, Sortino, Calmar, win rate, profit factor, recovery, max consecutive losses.
- AC includes generated artifacts under `reports/strategies/{strategy_id}/`.
- AC includes exact validation commands and threshold audit.

## Delegation

Create `.claude/tasks/<task-id>/brief.md`, then run the T2 flow unless the work is read-only analysis. For live-promotion evidence, classify as T3 if it can change deployment or risk-control state.
