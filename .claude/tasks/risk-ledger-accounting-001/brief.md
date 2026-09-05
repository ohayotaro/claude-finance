# risk-ledger-accounting-001: Venue-reconciled fill ledger and hardened risk accounting for the aggregator

## Objective

Make the cross-strategy risk aggregator's loss-limit and exposure decisions
rest on authoritative venue state and a reconciled fill ledger instead of bot
log telemetry. This is Step 1 and Step 2 of the repository improvement roadmap
(`.codex/plans/repository-improvement-roadmap.md`, section "1. Correct and
harden portfolio risk accounting"). Every later live-trading control depends
on this accounting being correct.

## Scope

Current behavior verified by the PM in `src/risk/aggregator.py`:

- `reconcile_once` accumulates `daily_realized_pnl` from `position_closed`
  log events (`pnl` field), so realized PnL is log-derived and excludes
  commission, fees, funding, borrow cost, and cash movements.
- `latest_unrealized` entries survive after a position closes or disappears
  from venue state; the venue-vs-log selection uses the heuristic
  `venue_unrealized != 0 or positions`.
- `load_group_strategies` drops strategies with `enabled == False` or a
  non-live-capable state, so residual positions and open orders of a paused
  or deprecated strategy vanish from group exposure, PnL, and caps.
- Reconciliation is keyed by strategy id only; there is no stable order/fill
  identity, so delayed, duplicated, or replayed fills are not detectable.
- Published state carries `last_success_ts` but no per-metric age or source.

Required changes:

1. Introduce an authoritative fill ledger (`src/risk/ledger.py` or as the
   plan recommends) fed from venue fills. Realized PnL is derived from
   ledger fills including commission, fees, funding, borrow cost, and
   explicit cash movements. Fills are keyed by
   (account_scope, strategy_id, symbol, stable order id, stable fill id) and
   ingestion is idempotent under replay and duplicates.
2. Extend the `VenueClient` protocol (or add a companion protocol) so venue
   adapters can supply fills and cash/funding events. `NullVenueClient` stays
   non-authoritative and keeps the existing fail-closed behavior. Create the
   `src/risk/venues/` package for adapters only if the plan justifies it;
   no real exchange adapter is in scope.
3. Unrealized PnL comes only from venue positions. Log-derived unrealized
   levels may be published as telemetry but must be dropped when the venue
   no longer reports the position, and must never feed cap decisions when a
   venue snapshot exists.
4. Continue monitoring strategies whose `enabled` flag is false or whose
   state is `deprecated`/`retired` until the venue confirms zero positions
   and zero open orders for that strategy. Their exposure and PnL count
   toward group caps until confirmed flat.
5. Define and test recovery behavior for: log rotation and truncation
   (offset beyond EOF, inode change), aggregator restart from checkpoint,
   fills arriving after the UTC day boundary for the day they belong to,
   and fills timestamped before the checkpoint that were not yet ingested.
6. Publish, per risk metric in the state file, its source
   (`venue`, `ledger`, `log`, `none`) and age in seconds, so consumers can
   fail closed on stale or non-authoritative data. Bump the published state
   schema explicitly and keep `_is_healthy` semantics fail-closed.
7. Provide `config/risk_groups.toml` as a documented example that matches
   `load_aggregator_config` (the file is referenced by rules and CI but does
   not exist in the repository).
8. Regression tests under `tests/test_risk/` for every item above, written
   as failing tests first where the current code is wrong, using `Decimal`
   fixtures with hand-calculated expected values.

## Non-Goals

- No real exchange or broker adapter, no network client, no ccxt usage.
- No changes to `src/orchestrator/registry.py` beyond what the aggregator
  strictly needs to read state/enabled flags (expected: none).
- No bot-side changes (`src/bot/`), no StateStore work, no backtest engine.
- No currency conversion across account scopes (recorded as a blocker for a
  later task); a single quote currency per risk group is assumed and must be
  asserted, not silently ignored.
- No change to the live-trading gate hook or KillSwitch semantics.
- No roadmap Steps 3 through 11.

## Acceptance Criteria

- AC1: A test proves realized PnL for a closed round trip equals the
  hand-calculated venue value net of commission, fees, and funding, and that
  the same fills ingested twice (and in shuffled order) yield identical
  ledger totals.
- AC2: A test proves a `position_update` log level does not contribute to
  `group_daily_pnl` once the venue snapshot omits that position, and that
  venue unrealized PnL is used whenever a venue snapshot is present, even
  when the venue total is exactly zero.
- AC3: A test proves a strategy with `enabled = false` (and one with
  `state = deprecated`) that still holds a venue position or open order is
  included in group exposure, PnL, and cap evaluation, and is excluded only
  after a cycle where the venue reports it flat.
- AC4: Tests prove correct behavior for log rotation/truncation, checkpoint
  restart without double counting, and a fill dated in the previous UTC day
  arriving after the boundary (attributed to its own day, not today).
- AC5: The published state includes source and age for daily PnL, exposure,
  drawdown, margin, and open order/position counts; a test proves a
  consumer can detect a `log`-sourced or stale metric.
- AC6: `config/risk_groups.toml` loads through `load_aggregator_config` and
  is validated by an existing or new test.
- AC7: `uv run --extra dev pytest -m "not integration and not slow"`,
  `uv run --extra dev ruff check src/ tests/ .claude/hooks/ .claude/scripts/`,
  and `uv run --extra dev mypy src/ .claude/scripts/` pass. All existing
  aggregator tests remain green or are updated with an explicit reason
  recorded in the implementation result.
- AC8: `.claude/docs/DESIGN.md` gains an ADR for the ledger/aggregator
  accounting model; the ADR notes that the aggregator is being changed under
  this task as the explicit exception to its "do not change" rule.

## Constraints And Context

- Financial safeguards: `Decimal` for money and size, UTC everywhere, no
  look-ahead (a fill may only affect the day it belongs to), explicit costs.
- Fail-closed by default: absence of authoritative data must never relax a
  cap. Reconciliation failure semantics in `.claude/rules/multi-strategy.md`
  section 6 remain binding.
- Known-failure-class checklist applies: identity binding (fill and order
  ids), fail-closed inspections, TOCTOU on log and checkpoint files, cache
  trust (checkpointed ledger vs. venue), boundary exactness (UTC day, zero
  unrealized), reserved names, duplicate keys.
- Keep the module's existing style: pure helpers, dataclasses with slots,
  stdlib-only runtime, JSON state publishing with atomic replace.
- Plain ASCII, English artifacts. Deliver `plan.md`, the implementation
  result, and `review.md` in English.

## Risk Tier

T3 - The change alters live risk-control logic (loss caps, exposure, and
fail-closed inputs) for every strategy in a risk group. Plan and review are
read-only; implementation requires explicit user approval after the plan is
approved by the PM. Effort is `xhigh` for all phases per the T3 rule.

## Required Validation

- `uv run --extra dev pytest -m "not integration and not slow"` (report
  counts before and after; list new tests by name)
- `uv run --extra dev pytest tests/test_risk/ -v`
- `uv run --extra dev ruff check src/ tests/ .claude/hooks/ .claude/scripts/`
- `uv run --extra dev mypy src/ .claude/scripts/`
- `uv run python -m src.orchestrator.registry audit` (or the equivalent
  audit entry point already used by CI) to confirm no registry impact
- Implementation result maps every AC to the test names that prove it.

## Forbidden Actions

- No network access, no new runtime dependencies.
- No live, testnet, or paper trading; no venue credentials.
- Do not commit, push, or otherwise mutate Git state.
- Do not modify `.claude/hooks/`, `.claude/scripts/`, `scripts/update.py`,
  or `config/registry.toml`.
- Do not weaken any existing fail-closed path or any existing test
  assertion without recording the reason in the implementation result.
- Do not delete existing checkpoint or state files formats without a
  documented migration path in the plan.

## Open Decisions Or Blockers

- Target venue and quote currency are not selected. The plan must keep the
  ledger venue-agnostic and state the assumptions it bakes in.
- Whether the ledger persists inside the existing aggregator checkpoint or
  in its own file is a plan decision; the plan must state the crash and
  restart implications of the choice.
- Cross-account currency conversion is deferred; the plan should note where
  the hook for it belongs.
