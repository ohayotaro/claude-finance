---
name: strategy-register
description: PM intake for strategy registry operations and lifecycle gates.
allowed-tools: "Bash(python3 *) Read Write Edit Glob Grep"
---

# Strategy Register

`config/registry.toml` is the single source of truth for strategy identity. Registry changes are T2, except live promotion or risk-control changes, which are T3.

## Intake

- Action: `register`, `transition`, `enable`, `disable`, `list`, `show`, or `audit`.
- For registration, collect venue, market, logic_slug, symbol, timeframe, runtime, account_scope, risk_group, family_id, and logic_version.
- For transitions, record current state, target state, precondition evidence, and operator approval requirements.

## Acceptance Checklist

- AC includes `strategy_id` canonicalization and uniqueness validation.
- AC includes deterministic MagicNumber allocation for MQL5 in the reserved range.
- AC includes lifecycle rule enforcement with no backward transitions.
- AC includes no secrets in registry entries.
- AC includes registry audit command and tests if code changes are needed.

## Delegation

For read-only `list`, `show`, or `audit`, Claude may run safe commands. For writes, create a task brief and use the T2/T3 flow. Live transition requires explicit user approval.
