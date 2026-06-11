# Architecture Design Document

## System Overview

This project is an AI-orchestrated financial trading system that coordinates three AI agents:

```
┌─────────────────────────────────────────────────┐
│                   Claude Code                    │
│              ── Orchestrator ──                  │
│  Delegates, integrates, does NOT implement       │
├─────────────┬─────────────┬─────────────────────┤
│  Subagents  │  Codex CLI  │    Gemini CLI       │
│             │             │                     │
│ - Codebase  │ - Design    │ - Chart analysis    │
│ - Review    │ - Debug     │ - PDF extraction    │
│ - Docs      │ - Algorithm │ - Research          │
│ - Tests     │ - Stats     │ - Visualization     │
└─────────────┴─────────────┴─────────────────────┘
```

## Specialized Team Agents

| Agent | Domain | File Scope |
|-------|--------|------------|
| data-engineer | Market data pipelines | src/data/* |
| quant-analyst | Backtesting, statistics, risk | src/backtesting/*, src/risk/* |
| strategist | Trade logic, signals | src/strategies/* |
| ea-developer | MQL5 Expert Advisors | mql5/* |
| bot-engineer | API-based Python trading bots (ccxt, WebSocket) | src/bot/* |
| infra-ops | Deployment, Docker, monitoring, dashboards | docker/*, deploy configs, src/monitoring/* |
| ml-engineer | ML model pipelines, feature engineering | src/ml/* (when present) |
| codex-debugger | Error analysis via Codex | (any — via Codex CLI) |
| general-purpose | Codebase exploration, utilities, tests | src/utils/*, tests/* |

## Skill Pipeline

```
/data-pipeline → /strategy-design → /backtest → /optimize → /ea-generate
     │                  │               │            │            │
  Fetch data      Design logic     Validate     Tune params   Convert to
  Clean/store     Define signals   Measure      Walk-forward  MQL5 EA
                  Set rules        Report       Monte Carlo   Deploy
```

## Architecture Decisions

### ADR-001: Orchestrator Pattern
- **Decision**: Claude Code delegates, does not implement
- **Rationale**: Conserve 1M context for coordination; leverage specialized models

### ADR-002: Dual Language Stack
- **Decision**: Python for analysis/backtesting, MQL5 for EA execution
- **Rationale**: Python has superior data science ecosystem; MQL5 is required for MetaTrader

### ADR-003: Data Format
- **Decision**: Parquet for storage, DataFrame for processing
- **Rationale**: Parquet offers columnar compression and fast I/O; pandas/polars interop

### ADR-004: Hook-Driven Routing
- **Decision**: Python hooks intercept tool calls to suggest AI routing
- **Rationale**: Enforcement at tool-call level is more reliable than prompt instructions alone

### ADR-005: Multi-Strategy as First-Class Concern (2026-05-14)
- **Decision**: Scaffolded projects treat strategies as first-class, isolated, registry-managed units. Identity is a `strategy_id` of the form `<venue>.<market>.<logic_slug>.<symbol>.<timeframe>.v<major>`. The canonical source of truth is `config/registry.toml`, written only by `/strategy-register`. Default runtime model is one process / container per strategy with per-strategy config, SQLite, and JSONL log.
- **Rationale**: The previous implicit model ("one project = one strategy") forced file rewrites whenever a new strategy was added or switched, broke audit trails, and made cross-strategy risk impossible to enforce. A registry-driven model lets the orchestrator scaffold N strategies without touching each other's files, gives a deterministic MagicNumber allocation for MQL5, and creates the seam needed for a cross-strategy risk aggregator service.
- **Skills affected**: new `/strategy-register`; `init-finance`, `strategy-design`, `bot-develop`, `ea-generate`, `bot-deploy`, `bot-monitor`, `risk-report` updated to consume / write registry. Contract lives in `.claude/rules/multi-strategy.md`.
- **MagicNumber allocation**: range `20_000_000`-`89_999_999` reserved for orchestrator. Initial candidate is `20M + (crc32(strategy_id) mod 70M)`; on collision the `magic_salt` field is incremented and the hash recomputed. Final value is frozen in the registry; EA reads it from a `.set` preset rather than hardcoding.
- **Risk aggregation**: separate `src/risk/aggregator.py` service, scoped per `risk_group`, reconciling against exchange/broker state every 60s. Soft cap freezes new entries across the group; hard cap flatten-and-halts.
- **Forward compatibility**: per-strategy SQLite is the default backend behind the `StateStore` protocol; future migration to a central operational DB (e.g. PostgreSQL) is possible without changing skill contracts, as long as bots respect the protocol.
- **Lifecycle gates**: `draft -> testnet -> live -> deprecated -> retired`, no backward transitions. Only `/bot-deploy` may promote to `live`, after the six preconditions defined in `multi-strategy.md` section 4. The daily live-trading acknowledgment in `.claude/state/live-trading-*.ack` remains an independent human gate enforced by the existing hook.
- **Open follow-ups**: schema migration policy when `registry.toml` `schema_version` is bumped; CI audit step (`/strategy-register audit`) wiring; reference implementation of `src/orchestrator/registry.py` and `src/risk/aggregator.py` (currently scaffolded as stubs by `/init-finance`).
