---
name: strategy-design
description: PM intake for strategy design briefs, registry planning, financial acceptance criteria, and Codex architecture.
allowed-tools: "Bash(python3 *) Read Write Edit Glob Grep"
---

# Strategy Design

Strategy design is T2 by default. It is T3 if it changes live trading, execution/risk controls, deployment, credentials, or production data.

## Intake

- Record market, venue, symbol, timeframe, runtime, edge hypothesis, benchmark, data availability, and intended execution platform.
- Define non-goals, risk constraints, and whether the design should register a new `strategy_id`.
- Capture relevant prior reports or structured research inputs.

## Acceptance Checklist

- AC includes statistical edge rationale and failure modes.
- AC includes entry/exit rules, position sizing, stop loss, and max-loss controls.
- AC includes no look-ahead bias and clear IS/OOS plan.
- AC includes transaction costs, slippage, capacity, and regime dependency.
- AC includes registry identity plan and downstream validation path.

## Delegation

Create the task brief and run `plan` before any implementation. Claude approves the Codex plan against user intent before implementation.
