# Repository Improvement Roadmap

Date: 2026-09-05

## Purpose

This plan develops the repository from an orchestration template into a
reproducible research and trading platform for:

- market edge discovery;
- point-in-time fundamental analysis;
- MQL5 EA development; and
- automated trading bot development.

The repository already has useful control-plane foundations: strategy identity,
registry lifecycle management, per-strategy isolation, live-trading gates, and a
cross-strategy risk aggregator. The research and execution packages are still
mostly scaffolds, so the recommended order is to complete one vertical slice for
one market and one strategy before adding more strategies or venues.

## Current Assessment

Implemented foundations:

- strategy registration, lifecycle controls, and registry audit;
- per-strategy paths for config, state, logs, and reports;
- MagicNumber allocation and netting-account conflict checks;
- global and per-strategy KillSwitch command gates;
- cross-strategy exposure, PnL, drawdown, margin, and health state aggregation;
- lint, type-check, test, and registry-audit CI jobs.

Major gaps:

- `src/backtesting`, `src/strategies`, `src/bot`, `src/optimization`, and
  `src/monitoring` do not yet provide working domain implementations;
- the MQL5 tree contains no EA implementation or Python/MQL5 parity harness;
- no point-in-time fundamental data model or provenance contract exists;
- no common, machine-readable experiment and backtest result schema exists;
- no venue adapter or end-to-end paper/testnet trading implementation exists.

## Recommended Design

### 1. Correct and harden portfolio risk accounting

Treat venue/broker state and a reconciled fill ledger as authoritative. Bot logs
remain telemetry and supporting evidence, not the primary source for realized
PnL or live risk limits.

Required changes:

- derive realized PnL from authoritative fills, including commission, fees,
  funding, borrow cost, and explicit cash movements;
- prevent stale log-derived unrealized PnL from surviving after a position is
  closed or disappears from venue state;
- continue monitoring disabled/deprecated strategies until all positions and
  open orders are confirmed flat;
- reconcile by account, strategy, symbol, and stable order/fill identifiers;
- specify recovery behavior for log rotation, truncation, restarts, delayed
  fills, and UTC day boundaries;
- publish the age and source of each risk metric so consumers can fail closed on
  stale or non-authoritative data.

Rationale: under-counting a loss or silently dropping residual exposure makes
all later live-trading controls unreliable.

Likely components:

- `src/risk/aggregator.py`
- `src/risk/ledger.py` (new)
- `src/risk/venues/` (new)
- `tests/test_risk/`
- `config/risk_groups.toml` (new example/config contract)

### 2. Add a reproducible research and experiment ledger

Every explored hypothesis should record:

- hypothesis and proposed economic/mechanical cause of the edge;
- falsification criteria and known regime dependency;
- universe, venue, timeframe, and observation period;
- exact data snapshot identifiers and code/config hashes;
- all attempted variants, including rejected variants;
- IS, validation, OOS, and untouched final holdout periods;
- execution and cost assumptions;
- outputs, decision, reviewer, and decision timestamp.

Record the total search count and related trials. Add multiple-testing-aware
metrics such as Probabilistic/Deflated Sharpe Ratio where appropriate. Keep the
final holdout inaccessible to optimization code until the candidate is frozen.

Recommended artifact layout:

```text
research/
  hypotheses/{hypothesis_id}.md
  experiments/{experiment_id}/manifest.json
  catalogs/data-snapshots.jsonl
reports/strategies/{strategy_id}/{experiment_id}/
```

### 3. Build a point-in-time fundamental data layer

Use bitemporal records. At minimum, each value needs:

- `period_end`: the economic/accounting period represented;
- `published_at`: when the market could first know the value;
- `available_at`: provider availability time after processing delay;
- `revision_at` or a vintage identifier;
- source, accession/release identifier, currency, units, and restatement flag;
- ingestion timestamp and raw-content checksum.

An as-of query at time `T` may only return rows with `available_at <= T` and the
latest vintage that was available by `T`. Store raw immutable releases and build
normalized derived tables from them. Corporate actions, delistings, constituent
membership, fiscal calendars, and timezone/session alignment must also be
point-in-time.

Likely components:

- `src/data/contracts.py` (new)
- `src/data/storage.py` (new)
- `src/data/providers/` (new; one adapter per documented provider)
- `src/fundamentals/` (new)
- `tests/test_data/` and point-in-time fixtures

### 4. Implement one canonical event-driven backtest engine

Define common contracts for market data, signals, orders, fills, portfolios,
cost models, and metrics. The engine must make timing explicit:

- when an observation becomes available;
- when a signal is evaluated;
- the earliest legal order time;
- intrabar rules when stop loss and take profit are both touched;
- partial fills, minimum sizes, tick sizes, spread, commission, slippage,
  funding, borrow cost, and market impact assumptions.

Use fixed, hand-calculated fixtures to verify orders, cash, positions, fees, and
PnL. Add walk-forward evaluation and purging/embargo for overlapping labels.
Keep IS/OOS results separated in both code and output.

Create a versioned result schema such as `backtest-result.v1.json` containing
strategy identity, logic version, data snapshot, split boundaries, trial count,
cost model, metrics, and artifact checksums. Replace stdout-regex thresholds as
the primary gate with validation of this structured artifact.

Likely components:

- `src/backtesting/contracts.py` (new)
- `src/backtesting/engine.py` (new)
- `src/backtesting/costs.py` (new)
- `src/backtesting/metrics.py` (new)
- `src/optimization/walk_forward.py` (new)
- `tests/test_backtesting/` and `tests/fixtures/`

### 5. Create a shared execution domain for bot and EA parity

Keep pure decision logic separate from runtime adapters. Given the same
normalized observations and state, Python backtest, Python bot, and MQL5 EA must
produce equivalent signals, target positions, size, stop loss, and take profit.

For Python bots, implement:

- idempotent client order IDs and an explicit order state machine;
- recovery from unknown submission outcomes by querying the venue;
- partial-fill handling, cancel/replace, and order/position reconciliation;
- persistent StateStore implementation with schema migrations;
- stale-market-data, clock-skew, aggregator-health, registry, margin, spread,
  and KillSwitch checks in the order path itself;
- deterministic market-data replay and fault-injection tests;
- paper and testnet adapters before any live adapter is enabled.

For MQL5 EAs, implement:

- a reusable risk/execution include library;
- MagicNumber loaded from the generated preset/config;
- deterministic bar/tick fixtures shared with Python;
- a parity report comparing decisions between Python and MQL5;
- MetaEditor compile evidence, Strategy Tester reports, and demo-account soak
  evidence linked to `strategy_id` and `logic_version`.

Likely components:

- `src/execution/` (new shared domain)
- `src/bot/` and `src/bot/state_store.py`
- `mql5/include/`, `mql5/experts/`, and `mql5/presets/`
- `tests/test_execution/`, replay fixtures, and MQL5 validation scripts

### 6. Add operational observability and promotion evidence

Create machine-readable promotion evidence for draft -> testnet -> live. A live
promotion should verify:

- recent backtest and final OOS artifacts pass their schema and thresholds;
- paper/testnet run duration and order/reconciliation error budgets pass;
- KillSwitch, stale-data, disconnect, partial-fill, and restart drills pass;
- notification delivery is confirmed;
- strategy and aggregate limits are non-zero and compatible;
- code, config, data, and deployed artifact hashes match the accepted evidence.

Add dashboards/alerts for stale data, reconciliation lag, rejected orders,
unknown order state, slippage drift, PnL divergence, drawdown, margin, and
heartbeat age.

## Alternatives Considered

### Implement separate backtest engines for each strategy

Rejected as the default because execution timing, cost assumptions, and metrics
would drift. Strategy-specific extensions should plug into shared contracts.

### Use current revised fundamentals for historical analysis

Rejected because revisions introduce look-ahead bias. Point-in-time/vintage
queries are required even if this limits initial provider choice.

### Build a broad multi-venue platform immediately

Deferred. A single end-to-end vertical slice exposes contract problems earlier
and provides reusable fixtures for later venues.

### Treat bot logs as the financial ledger

Rejected for live risk accounting because logs can be delayed, truncated,
duplicated, or lost. A venue-reconciled fill ledger is required.

## Implementation Sequence

1. Write a task brief for risk-accounting correctness and add failing
   regression tests for disabled strategies, stale unrealized PnL, missing log
   lines, fees/funding, restarts, and day boundaries.
2. Implement the authoritative ledger/reconciliation model and integrate it with
   the aggregator.
3. Define versioned data, experiment-manifest, and backtest-result schemas.
4. Implement one point-in-time provider pipeline with immutable raw data and
   as-of query tests.
5. Implement the canonical backtest engine and a simple reference strategy
   against hand-calculated fixtures.
6. Add walk-forward, final holdout, trial ledger, robustness statistics, and
   cost/capacity stress scenarios.
7. Implement one paper/testnet bot using the same signal and sizing contracts.
8. Add replay, restart, partial-fill, disconnect, stale-data, and KillSwitch
   fault tests.
9. Generate one MQL5 EA for the reference strategy and add Python/MQL5 parity
   evidence.
10. Add structured promotion evidence, monitoring, and CI gates.
11. Run an extended paper/testnet soak before proposing any live deployment.

Each implementation step involving financial logic is T2 or T3 under the
repository contract and requires its own `.claude/tasks/<task-id>/brief.md`,
acceptance criteria, validation, and independent review.

## Validation Plan

- Unit tests against known financial calculations using `Decimal` where exact
  money/size behavior matters.
- Property tests for conservation of cash/position and idempotent event replay.
- Golden fixtures for point-in-time joins and Python/MQL5 decision parity.
- No-network replay tests for market data, fills, restarts, disconnects, and
  partial fills.
- Walk-forward and untouched final OOS evaluation with explicit trial counts.
- Cost and capacity stress tests at multiple spread, slippage, latency, volume,
  funding, and commission assumptions.
- Registry audit, Ruff, mypy strict, and fast pytest in CI.
- Provider sandbox integration tests behind the `integration` marker.
- MetaEditor compilation, Strategy Tester, and demo/testnet soak reports stored
  under the strategy report directory.

## Risks and Blockers

- The first target market, venue, asset class, timeframe, and fundamental data
  provider have not been selected. These choices affect schemas, execution
  details, costs, and integration tests.
- Reliable point-in-time fundamentals may require a paid provider or custom raw
  filing/release archive.
- MetaTrader compile and Strategy Tester validation require a compatible
  terminal environment, usually Windows or a dedicated runner.
- Cross-venue/account risk aggregation needs explicit currency conversion and
  timestamp-alignment rules.
- The environment used for the original assessment was read-only; the complete
  pytest suite could not create temporary files. Ruff, mypy, registry audit,
  and selected write-free unit tests passed.

## Success Criteria

- SC1: One registered strategy can run the same decision logic in backtest,
  replay, paper/testnet bot, and MQL5 EA with explained and bounded parity
  differences.
- SC2: Every research result is reproducible from immutable data identifiers,
  code/config hashes, split definitions, cost assumptions, and trial history.
- SC3: Fundamental features pass as-of tests proving that later publications or
  revisions cannot enter earlier decisions.
- SC4: Backtests enforce legal event timing, complete costs, IS/OOS separation,
  robustness checks, and an untouched final holdout.
- SC5: Live-capable order paths enforce per-strategy and aggregate risk gates,
  and remain safe under restart, stale data, disconnect, and unknown order
  outcomes.
- SC6: Disabled or deprecated strategies remain risk-visible until confirmed
  flat, and venue-reconciled realized/unrealized PnL drives loss limits.
- SC7: CI validates structured research/backtest artifacts, financial regression
  tests, registry invariants, lint, and strict typing.
