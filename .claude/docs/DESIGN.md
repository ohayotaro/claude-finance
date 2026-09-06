# Architecture Design Record

## Current Architecture

This repository uses a two-provider architecture:

```text
Claude Opus  -> PM, Japanese user interaction, neutral task brief, risk tier, approvals, acceptance
Codex        -> technical lead, repository exploration, design, implementation, tests, independent review
```

Substantial work is represented by `.claude/tasks/<task-id>/brief.md` and executed through `.claude/scripts/codex_handoff.py`. Planning and review use read-only Codex invocations. Implementation uses workspace-write. The runner centralizes Codex flags, phase prompts, result artifacts, JSONL event logs, and Git metadata.

## Current Decisions

### ADR-001: Claude PM + Codex Engineering

- **Status**: Accepted
- **Decision**: Claude owns PM/change-control duties; Codex owns technical work.
- **Rationale**: The previous orchestration split created duplicate ownership, high PM context consumption, and non-deterministic delegation. A neutral brief plus phase artifacts makes the handoff auditable and keeps technical decisions in the engineering context.
- **Consequences**: Claude writes only approved local orchestration artifacts. Codex receives the brief, relevant rules, and phase prerequisites through the central runner.

### ADR-002: Risk-Tier Gates

- **Status**: Accepted
- **Decision**: Work is classified T0-T3. T2 requires plan, Claude approval, implementation, and fresh review. T3 adds explicit user approval before implementation or external action.
- **Rationale**: Financial trading tasks have materially different risk profiles. Tiered gates prevent low-risk documentation work from carrying heavyweight process while keeping live trading, credentials, deployment, migrations, and risk controls fail-closed.
- **Consequences**: Risk classification is a PM judgment, not a keyword route. Hooks only enforce deterministic constraints.

### ADR-003: Fresh Review Separation

- **Status**: Accepted
- **Decision**: Medium- and high-risk changes receive a fresh read-only Codex review that does not receive the implementation transcript.
- **Rationale**: Independent review catches gaps hidden by implementation context and keeps acceptance evidence auditable.
- **Consequences**: Review may read only the brief, approved plan, implementation result artifact, repository, and diff.

### ADR-004: Multi-Strategy As First-Class Runtime

- **Status**: Accepted
- **Decision**: Strategies are registry-managed, isolated units. `config/registry.toml` owns `strategy_id`, lifecycle state, runtime, paths, risk group, account scope, and MQL5 MagicNumber allocation.
- **Rationale**: One project may host multiple strategies without rewriting shared files. Registry isolation enables per-strategy configs/state/logs/reports and cross-strategy risk aggregation.
- **Consequences**: `src/orchestrator/registry.py` and `src/risk/aggregator.py` are financial runtime code with tests and must not be changed unless a task explicitly requires it.

### ADR-005: Venue-Reconciled Risk Ledger

- **Status**: Accepted
- **Decision**: Group enforcement uses independently timestamped, complete venue observations for account state, positions, orders, exposure, margin, drawdown, and unrealized PnL, plus a separate SQLite fill ledger for realized PnL. Bot logs are telemetry only. This ADR and `risk-ledger-accounting-001` are the explicit approved exception to ADR-004's protected-aggregator rule.
- **Ledger model**: Fills use the composite identity `(account_scope, strategy_id, symbol, order_id, fill_id)`. Cash events use an account-scoped venue event ID. Exact replay is a no-op; conflicting reuse of an identity aborts the batch and fails closed. Net realized PnL is venue-normalized gross realized PnL minus commission and fees, plus each cash event's explicit realized-PnL delta.
- **Common accounting cut**: The ledger completeness watermark is the upper bound for enforcement accounting. A position data cut may trail that watermark by no more than `accounting_cut_max_skew_s`, with the bound defaulting to the poll interval; realized PnL is then limited to the earlier position cut so it cannot double-count a still-open unrealized position. A position observation whose true `as_of` timestamp is newer than the ledger watermark is rejected at any positive skew unless the adapter explicitly supplies a historical `as_of_cut` equal to the ledger watermark. In that aligned case the ledger watermark is the enforcement cut. Daily realized PnL includes only ledger events at or before the enforcement cut; later visible events are pending ledger telemetry until a later complete position view covers them. Unrealized PnL provenance always carries the true position observation timestamp, while composite group PnL carries the older effective enforcement timestamp.
- **Durability**: Each risk group stores `data/aggregator/{risk_group}/ledger.sqlite3`. SQLite uniqueness and one transaction bind record insertion to venue-cursor advancement. A crash before commit advances neither; a crash after commit can safely replay stable identities. `run_forever` holds a non-blocking exclusive advisory lock in the ledger directory so only one aggregator process can write a risk group on a host, using `fcntl.flock` on POSIX and `msvcrt.locking` on Windows. Checkpoint save compares the ledger's current binding with the binding recorded by the reconciliation cycle and refuses to adopt a concurrent advance. A refusal invalidates enforcement provenance before unhealthy state publication. If a ledger-dependent calculation fails after commit, reconciliation enters fail-closed and checkpoint publication is blocked until a complete authoritative cycle binds the cached state to the current ledger generation. Unknown or corrupt schemas are refused and are never deleted or silently recreated.
- **Checkpoint migration**: `checkpoint.json` schema v3 retains the last authoritative snapshot, PnL, pending ledger telemetry, exposure, provenance, drawdown baselines, cap/failure state, residual strategy IDs, and log-tail identity metadata. Every current-schema field is required and restored only from its exact JSON type; missing financial values, boolean coercion, negative counts, inconsistent caps, unbound drawdown baselines, and inconsistent ledger metadata are corruption. The checkpoint binds state to the SQLite cursor and monotonic ledger generation. If the ledger is ahead after a crash, cached caps and the HWM are retained, but the baseline is unverified and enforcement remains fail-closed until a fresh complete venue cycle re-establishes it. Checkpoints are replaced before their corresponding state publication. Unversioned v1 checkpoints preserve safe baselines and failure state but discard log-derived PnL and reset unverifiable log offsets; v2 checkpoints bootstrap through the same fail-closed authority check. A missing or corrupt checkpoint beside an existing ledger, or any ledger metadata-read failure during startup, publishes fail-closed state because the drawdown baseline cannot be reconstructed safely.
- **Published state**: State schema v2 retains compatibility values and adds `published_at` plus per-metric source, authoritative observation timestamp, and informational age. Consumers recompute freshness from `as_of_ts` and their current UTC clock, and independently reject an old `published_at`; they never trust the stored age as a liveness signal. Producer and consumer health both use the state's published `future_skew_tolerance_s`, allowing negative ages only within that bound and rejecting larger future skew. Producer freshness is evaluated from one injectable UTC clock read after all venue I/O, with at most five configurable seconds of tolerance. Health requires fresh account, position, order, and ledger observations whose `complete` and `authoritative` fields are exact booleans set to `True`. Incomplete/non-authoritative batches, non-boolean flags, and identity, account, currency, or freshness mismatches cannot replace last-known enforcement values or clear existing caps. A CLI startup refusal caused by `NullVenueClient` replaces any prior state with an unhealthy fail-closed publication before returning non-zero.
- **Scope assumptions**: One aggregator instance covers one `account_scope` and one `quote_currency`; all registry and venue records must match both. Cross-account currency conversion is deferred. Its future hook belongs in venue normalization before records enter the ledger, with explicit conversion timestamps and rates.
- **Residual risk**: Disabled, deprecated, and retired strategies remain venue-queryable. Their positions and orders remain in group risk until one complete authoritative cycle reports both flat, while same-day realized ledger PnL remains counted after flattening.
- **Numeric boundary**: Venue-normalized `Decimal` inputs are finite and limited to an adjusted exponent and scale of at most 40 in absolute value. Derived and persisted aggregate values, including exposures, daily totals, drawdowns, and checkpoint financial fields, use a separate wider bound of 100 for adjusted exponent and scale so valid boundary products and accumulated totals remain storable and restorable. Ledger accumulation, exposure multiplication/accumulation, unrealized summation, composite PnL addition, cap-boundary arithmetic, checkpoint consistency arithmetic, and drawdown numerators use an isolated 256-significant-digit context that traps `Inexact`, `Rounded`, `Overflow`, and `InvalidOperation`. Cap decisions use exact cross-multiplication rather than division. Because repeating ratios cannot be represented exactly as `Decimal`, the final published drawdown percentage is explicitly rounded to two decimal places inside that isolated context, matching the repository risk-metric precision rule; ambient context never controls it. The precision covers the 162 digits possible when multiplying two maximally sized supported input coefficients and retains 94 digits of accumulation headroom; exceeding the derived bound or exact context fails closed instead of silently rounding. Collections are materialized once before validation; any validation or post-commit accounting failure preserves cached amounts, invalidates their enforcement provenance, and fails closed.

#### Module map (risk-ledger-accounting-002)

The venue-reconciled aggregator is decomposed along one-way ownership boundaries:

- `config.py` owns typed risk-group configuration, lifecycle constants, and safe aggregator artifact paths.
- `observations.py` owns venue DTOs and adapter loading, log-tail parsing, collection materialization, freshness, identity, currency, completeness, and accounting-cut validation.
- `accounting.py` owns cached state, exact exposure and PnL composition, drawdown, cap evaluation, UTC-day transitions, residual-strategy accounting, and staged successful-cycle application.
- `persistence.py` owns schema-v3 checkpoint decoding and semantic ledger binding, atomic checkpoint replacement, migrations, and the portable single-writer lock.
- `publication.py` owns schema-v2 state serialization, metric provenance, consumer validation, atomic publication, and startup fail-closed publication.
- `aggregator.py` is the stable compatibility facade and contains only reconciliation orchestration, the run loop, and CLI startup handling.

The dependency direction is `ledger.py` and `config.py` into `observations.py`, then `accounting.py`, then `persistence.py` and `publication.py`, and finally `aggregator.py`. No extracted module imports `aggregator.py`. The facade remains below 600 lines; every extracted module remains below 900 lines.

## Superseded History

### ADR-S1: Three-Provider Orchestration

- **Status**: Superseded
- **Former decision**: Claude coordinated Codex CLI, a multimodal CLI, and role-based Opus agents.
- **Reason superseded**: The architecture duplicated ownership, increased always-loaded context, and made responsibility boundaries unclear. Multimodal extraction and role-agent coordination are no longer active architecture.

### ADR-S2: Hook Keyword Routing

- **Status**: Superseded
- **Former decision**: Prompt and tool hooks used keyword routing to suggest provider or role assignment.
- **Reason superseded**: Risk tier and acceptance criteria are PM judgments. Deterministic hooks should enforce safety and integrity only, not infer technical ownership.

### ADR-S3: Inline Codex Prompt Templates

- **Status**: Superseded
- **Former decision**: Skills and documents embedded many one-off Codex command templates.
- **Reason superseded**: Centralizing prompt assembly in `.claude/scripts/codex_handoff.py` prevents drift, allows tests for safe flags, and preserves phase isolation.

## Financial Safety Contracts

- No look-ahead bias.
- Explicit transaction costs, spread, commission, and slippage.
- In-sample and out-of-sample separation.
- Stop loss, daily loss, drawdown, kill switch, and cross-strategy risk controls.
- UTC/timezone correctness.
- Appropriate numerical precision for financial calculations.
- Regression tests for financial logic changes.

## Deterministic Hooks

- `pm-write-guard.py`: blocks Claude source/config writes outside allowed PM artifact paths.
- `live-trading-gate.py`: blocks live-trading Bash commands unless kill switch is clear and a fresh acknowledgment exists.
- `post-bash-dispatcher.py`: runs concise post-command detectors and telemetry.
- `error-to-codex.py`: points failures to the canonical task/debug flow.
- `post-backtest-analysis.py`: detects real backtest failures and metric threshold warnings.
- `post-bot-execution.py`: detects bot execution and connectivity incidents.
- `log-cli-tools.py`: logs minimal Codex metadata without raw prompts or command bodies.
