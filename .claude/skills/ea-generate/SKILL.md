---
name: ea-generate
description: PM intake for MQL5 Expert Advisor generation or review with registry and risk controls.
allowed-tools: "Bash(python3 *) Read Write Edit Glob Grep"
---

# EA Generate

EA work is T2 by default and T3 if it changes live execution/risk controls or deployment.

## Intake

- Require `strategy_id`; verify registry entry and `runtime = "mql5"`.
- Record MagicNumber, account position mode, symbol, timeframe, preset path, and broker constraints.
- Define signal parity with Python/backtest logic and required MetaTrader tester evidence.

## Acceptance Checklist

- AC includes `#property strict`, `GetLastError()` handling, indicator handle release, and dynamic array cleanup.
- AC includes MagicNumber from registry/preset only, never hardcoded in source.
- AC includes stop loss, position sizing, spread/slippage checks, and emergency stop behavior.
- AC includes no look-ahead signal logic and no live deployment.
- AC includes MQL5 review evidence and regression tests or tester instructions.

## Delegation

Create the task brief and run the T2 flow. Live account deployment requires T3 approval and remains manually gated.
