# Plan

Plan ready for PM review. No repository files were edited. The pre-existing untracked `.claude/tasks/risk-ledger-accounting-001/state.json` remains untouched. Because this is T3 work, implementation remains blocked pending explicit PM and user approval.

## Recommended design and rationale

### 1. Make the authority boundary explicit

```text
Venue ledger batch -> durable fill ledger -> daily realized PnL --+
                                                                  +-> group daily PnL -> caps
Venue positions ---------------------> unrealized PnL ------------+
Venue positions/orders/snapshot -----> exposure, counts, margin, drawdown
Bot logs ----------------------------> telemetry only
```

A reconciliation cycle will update enforcement state only when the account snapshot, positions, orders, and ledger batch all succeed and pass validation. Partial success must not mix fresh and stale inputs. On failure, retain last-known authoritative values, let their ages increase, and preserve the existing five-failure fail-closed transition.

Logs will never contribute to realized PnL, unrealized PnL, exposure, or cap decisions. Log unrealized values may remain as clearly labeled telemetry.

### 2. Add a venue-agnostic durable ledger

Create `src/risk/ledger.py` using only `sqlite3` and the standard library. Store it separately at:

`data/aggregator/{risk_group}/ledger.sqlite3`

Use SQLite rather than embedding the ledger in `checkpoint.json` because it provides:

- Transactional insertion and cursor advancement.
- Composite uniqueness constraints for fill identity.
- Exact duplicate detection without rewriting an ever-growing JSON document.
- Durable restart behavior and all-or-nothing ingestion.
- Conflict detection when the same identity arrives with different financial data.

Proposed normalized records:

- `VenueFill`
  - `account_scope`, `strategy_id`, `symbol`, `order_id`, `fill_id`
  - UTC `occurred_at`
  - side, quantity, execution price
  - authoritative venue `gross_realized_pnl`
  - commission and fees
  - quote currency
- `VenueCashEvent`
  - account-wide stable event ID
  - optional strategy/symbol attribution
  - UTC `occurred_at`
  - kind such as funding, borrow cost, rebate, adjustment, deposit, or withdrawal
  - signed cash delta and explicitly classified realized-PnL delta
  - quote currency

The required fill primary key will be exactly:

`(account_scope, strategy_id, symbol, order_id, fill_id)`

An identical replay is a no-op. The same key with different contents raises a ledger identity conflict, aborts the whole batch, and makes reconciliation fail closed.

Daily realized PnL will be:

`sum(gross_realized_pnl - commission - fees) + sum(cash_event.realized_pnl_delta)`

All calculations and persisted financial fields use `Decimal` serialized as canonical strings. Fill prices already embody spread and slippage.

The ledger will consume venue-normalized gross realized PnL instead of imposing a generic average-cost formula. That avoids silently applying linear-contract accounting to inverse, quanto, FX, broker-netting, or venue-specific products. An adapter that cannot provide or correctly derive venue realized PnL must report an incomplete batch; the aggregator must not substitute bot logs or a guessed formula.

SQLite will use a versioned schema, transactions, `PRAGMA user_version`, and durable journal settings. Unknown or corrupt ledger schemas must be rejected without deleting or recreating the file.

### 3. Extend the venue protocol with gap-free ledger batches

Extend `VenueClient` with a required method returning a `VenueLedgerBatch` containing:

- Fills and cash/funding events.
- An opaque venue cursor.
- The batch's authoritative `as_of` timestamp.
- A completeness indicator.

Cursor ordering represents when records become visible through the venue history interface, not their financial timestamp. This allows a newly visible fill dated before the previous checkpoint to arrive after the stored cursor and still be ingested.

The ledger records and the next cursor will commit in the same SQLite transaction:

- Crash before commit: neither events nor cursor advance.
- Crash after commit but before JSON checkpoint/state publication: replay is harmless because identities are already present.
- Restart with an older venue response: duplicates are no-ops.
- Newly visible older fill: inserted and attributed to its own UTC date.

If a future adapter lacks a gap-free cursor, it must implement an overlapping/full replay behind this protocol and claim completeness only after pagination is gap-free. The aggregator will not advance an incomplete batch.

`NullVenueClient` will implement the expanded shape but remain explicitly non-authoritative. It will continue to produce unhealthy, fail-closed state and must not make empty results look like an authoritative zero.

No `src/risk/venues/` package is planned because no adapter is in scope. It should be created with the first real adapter, not as empty scaffolding.

### 4. Assert account and currency assumptions

Add a required `quote_currency` to `AggregatorConfig` and the example configuration. Validate that snapshots, positions, fills, fees, and cash events use that currency.

This task will continue supporting one configured `account_scope` per aggregator instance. Every risk-visible registry entry must match it; mismatches fail closed rather than being filtered away. Supporting multiple account scopes and currency conversion belongs at the venue-normalization boundary in a later task.

Venue-native fees in another asset must be normalized by a future adapter or reported incomplete. The ledger will not invent conversion rates.

### 5. Keep inactive strategies risk-visible

Change strategy discovery to query every target-group entry in these states regardless of `enabled`:

- `testnet`
- `live`
- `deprecated`
- `retired`

Draft entries remain excluded.

For each successful snapshot:

- Enabled live/testnet strategies remain active.
- Disabled, deprecated, or retired strategies remain in the residual set while they have any venue position or open order.
- They leave the residual set only after the same authoritative cycle reports both zero positions and zero open orders.
- A failed cycle cannot clear residual status.
- Venue queries may continue including these IDs after flat confirmation so delayed residuals can reappear safely.

Their positions, unrealized PnL, orders, and counts feed group metrics while residual. Same-day realized losses already booked in the ledger remain in daily group PnL after the strategy becomes flat; flattening or retirement must not erase a loss before the UTC day ends.

Returned records with a missing, foreign, or mismatched strategy ID will invalidate reconciliation rather than silently contaminate a group.

### 6. Remove all log-derived enforcement accounting

On a successful venue snapshot:

- Unrealized PnL is always the sum of venue positions, including an authoritative total of exactly zero.
- A missing venue position means its log telemetry entry is pruned.
- Log telemetry is retained only for keys present in the latest venue position set.
- It is never added to `group_daily_pnl`.
- Log `position_closed.pnl` is ignored for ledger and cap accounting.

This replaces the current zero-or-positions heuristic in [aggregator.py](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:645).

### 7. Harden log and checkpoint recovery

Extend `StrategyLogStatus` with file identity and a small prefix/boundary fingerprint. Open and inspect the file through one descriptor to reduce stat/open TOCTOU.

Reset the telemetry offset to zero when:

- Device/inode changes.
- File size is below the stored offset.
- The fingerprint changes, covering copy-truncate followed by rapid regrowth.

Partial final lines remain deferred. Replayed log lines are financially harmless because logs no longer drive caps.

Keep `checkpoint.json` for HWM, start-of-day equity, failure state, cap state, residual IDs, and log-tail metadata. Add an explicit checkpoint schema version.

Migration behavior:

- Treat an existing unversioned checkpoint as v1.
- Preserve safe date, drawdown baseline, HWM, and failure fields.
- Ignore v1 log-derived realized PnL and cached unrealized PnL.
- Reset v1 log offsets when identity metadata is unavailable.
- Bootstrap ledger authority from the venue before reporting healthy.
- Never delete or silently recreate an unknown/corrupt ledger.
- A missing checkpoint with a new empty ledger is first-start bootstrap; a missing/corrupt checkpoint beside an existing ledger fails closed because drawdown baselines may have been lost.

The ledger query, not a mutable daily accumulator, determines totals by `occurred_at.date()` in UTC. A previous-day event received today changes only the previous day's ledger total, never today's loss cap.

### 8. Publish state schema v2 with metric provenance

Bump the published state to `schema_version = 2`. Preserve existing top-level values and cap flags for a compatibility period, while adding `metric_metadata` entries containing:

- `source`: `venue`, `ledger`, `log`, or `none`
- `as_of_ts`
- `age_seconds`
- component sources where a metric is composite

Cover at least:

- `group_daily_pnl`: primary source `ledger`, with realized=`ledger` and unrealized=`venue`; age is the older component age.
- `daily_realized_pnl`: `ledger`
- `daily_unrealized_pnl`: `venue`
- net and gross exposure: `venue`
- start-of-day and HWM drawdown: `venue`
- margin used and margin ratio: `venue`
- open position and open order counts: `venue`
- supplemental log unrealized telemetry: `log`

If no authoritative observation exists, use source `none` and age `null`.

Make serialization time injectable so age tests are deterministic. Add a pure consumer-side validation helper that rejects:

- Missing or unknown state schema versions.
- Missing/malformed metadata.
- `log` or `none` for enforcement metrics.
- Negative or over-limit ages.

Update `_is_healthy` to require the existing fail-closed conditions plus fresh authoritative metadata for every cap input. Stale or partial data must not clear an existing cap.

### 9. Supply configuration and architecture documentation

Add `config/risk_groups.toml` with:

- A documented example group.
- Explicit `account_scope` and `quote_currency`.
- A poll interval no greater than the binding 60-second maximum.
- Current threshold and health settings.
- A commented venue-client example, without naming or configuring a real adapter.

Strengthen `load_aggregator_config` to reject invalid threshold ordering, missing currency, non-positive intervals, or intervals above 60 seconds.

Append ADR-005 to [.claude/docs/DESIGN.md](/Users/ohayotaro/claude-finance/.claude/docs/DESIGN.md:31), documenting:

- Venue and ledger authority.
- SQLite and crash/restart decisions.
- State/checkpoint migration.
- Single-account and single-quote-currency assumptions.
- The explicit `risk-ledger-accounting-001` exception to ADR-004's protected-aggregator rule.

## Alternatives considered

| Alternative | Decision |
|---|---|
| Store ledger rows inside `checkpoint.json` | Rejected. Full rewrites, growing files, and weak uniqueness/transaction guarantees are poor fits for an authoritative ledger. |
| Use a separate SQLite ledger | Recommended. Composite keys, atomic cursor commits, durable restart, and stdlib-only runtime fit the risk level. |
| Derive gross PnL generically from price and quantity | Rejected. It bakes in unsupported linear/average-cost assumptions before a venue/product is selected. |
| Make ledger history an optional companion protocol | Rejected. A snapshot-only client could accidentally pass runtime validation and publish incomplete PnL as authoritative. |
| Fall back to logs during venue failure | Rejected. It violates the binding authority and fail-closed rules. |
| Stop querying inactive strategies permanently after one flat snapshot | Rejected. Continuing to request their IDs detects delayed orders, fills, or residual positions; only their metric contribution becomes zero. |
| Create an empty `src/risk/venues/` package | Deferred until a real adapter is approved. |

## Impacted files and components

Planned changes:

- `src/risk/ledger.py` - new normalized records, SQLite schema, ingestion, totals, cursor, and conflict handling.
- [src/risk/aggregator.py](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:89) - venue protocol, reconciliation, strategy visibility, log recovery, metric metadata, health, checkpoint migration, and config validation.
- `tests/test_risk/test_ledger.py` - new known-value and recovery tests.
- [tests/test_risk/test_aggregator.py](/Users/ohayotaro/claude-finance/tests/test_risk/test_aggregator.py:1) - authority, residual-strategy, state-schema, log recovery, and migration regressions.
- `config/risk_groups.toml` - new documented example.
- [.claude/docs/DESIGN.md](/Users/ohayotaro/claude-finance/.claude/docs/DESIGN.md:1) - ADR-005.

Explicitly untouched:

- `src/orchestrator/registry.py`
- `src/bot/`
- `.claude/hooks/`
- `.claude/scripts/`
- `scripts/update.py`
- `config/registry.toml`
- Live-trading gates and KillSwitch behavior
- Dependencies and venue adapters

## Implementation sequence

1. Obtain explicit T3 approval and recheck the dirty worktree.
2. Run the existing fast suite before edits and record its test count.
3. Add failing tests for AC1-AC6 and recovery edge cases; run targeted tests to confirm they fail for the intended current behavior.
4. Implement `src/risk/ledger.py`, including schema/version checks, identity conflicts, transactional cursor commits, UTC attribution, and exact Decimal totals.
5. Extend the venue dataclasses/protocol, `NullVenueClient`, loader validation, and offline stubs.
6. Refactor reconciliation into fetch, validate, transactional ledger ingest, compute, and publish stages. Do not mutate enforcement state before the complete input set is validated.
7. Change registry selection and residual-state handling for disabled/deprecated/retired strategies.
8. Remove log PnL from enforcement and implement rotation/truncation identity handling.
9. Version and migrate checkpoints; add state schema v2 provenance, consumer validation, and margin publication.
10. Add and validate `config/risk_groups.toml`.
11. Add ADR-005.
12. Run targeted and complete validation, record before/after counts and exact new test names, and produce the implementation result for independent review.

## Test and validation plan

Planned named regressions include:

- `test_closed_round_trip_net_of_costs_and_funding_is_idempotent`
- `test_cash_and_borrow_events_have_explicit_pnl_effects`
- `test_conflicting_duplicate_fill_identity_fails_closed`
- `test_venue_zero_unrealized_overrides_log_telemetry`
- `test_venue_omission_prunes_log_unrealized_from_caps`
- `test_disabled_strategy_residual_position_counts_until_flat`
- `test_deprecated_strategy_open_order_counts_until_flat`
- `test_failed_reconciliation_cannot_clear_residual_strategy`
- `test_log_inode_change_restarts_from_zero`
- `test_log_truncation_beyond_offset_restarts_from_zero`
- `test_ledger_restart_replay_does_not_double_count`
- `test_late_precheckpoint_fill_is_ingested_by_availability_cursor`
- `test_previous_utc_day_fill_arriving_today_is_not_today_pnl`
- `test_v1_checkpoint_does_not_restore_log_derived_pnl`
- `test_state_schema_v2_publishes_required_metric_metadata`
- `test_metric_consumer_rejects_log_source_and_stale_age`
- `test_null_venue_publishes_none_sources_and_is_unhealthy`
- `test_quote_currency_mismatch_fails_closed`
- `test_example_risk_groups_config_loads`

Required commands:

```bash
uv run --extra dev pytest tests/test_risk/ -v
uv run --extra dev pytest -m "not integration and not slow"
uv run --extra dev ruff check src/ tests/ .claude/hooks/ .claude/scripts/
uv run --extra dev mypy src/ .claude/scripts/
uv run python -m src.orchestrator.registry audit
```

Run the fast pytest command before and after implementation and record both counts. All tests use temporary files and stub clients; no network, venue credentials, paper trading, or live trading is required. If `uv` cannot execute from the existing environment without downloading anything, stop and report `BLOCKED`.

## Risks and blockers

- No venue is selected, so the protocol's cursor, completeness, and normalized gross-PnL contract cannot yet be validated against a real API. `NullVenueClient` ensures this cannot be mistaken for live readiness.
- Some venues do not expose per-fill realized PnL or charge fees in another asset. A future adapter must derive and normalize these accurately or remain incomplete and fail closed.
- SQLite history will grow because pruning authoritative identities without a venue-specific finality guarantee is unsafe. Retention/compaction requires a later task.
- The current task supports one account scope and one quote currency per aggregator. Cross-account aggregation or currency conversion must fail configuration validation until a later design supplies conversion timestamps and rates.
- Platform inode behavior varies. The persisted fingerprint is required as a fallback for copy-truncate and inode reuse.
- Existing tests that assert log-derived realized PnL or NullVenue unrealized fallback must be replaced, with the reason recorded in the implementation result.
- No technical or network blocker exists for the planned offline implementation. T3 approval is the current implementation gate.

## Acceptance-criteria mapping

| Criterion | Planned evidence |
|---|---|
| AC1 | `test_closed_round_trip_net_of_costs_and_funding_is_idempotent` uses hand-calculated Decimal values, duplicate replay, and fixed shuffled order; cash/borrow and conflicting-key tests cover the remaining ledger semantics. |
| AC2 | `test_venue_zero_unrealized_overrides_log_telemetry` and `test_venue_omission_prunes_log_unrealized_from_caps` prove authoritative zero and disappearance behavior. |
| AC3 | Disabled and deprecated residual tests assert requested strategy IDs, exposure/unrealized PnL, order/position counts, cap effects, failed-cycle retention, and removal only after an authoritative flat cycle. |
| AC4 | Rotation, truncation, restart replay, pre-checkpoint late fill, v1 migration, and previous-UTC-day tests prove each required recovery boundary without double counting or wrong-day attribution. |
| AC5 | State-schema and consumer-validation tests cover source and age for daily PnL, exposure, both drawdowns, margin, and both counts, including rejection of log-sourced and stale values. |
| AC6 | `test_example_risk_groups_config_loads` reads the repository example through `load_aggregator_config`; additional validation covers currency, interval, and threshold invariants. |
| AC7 | Run and record all five required commands, before/after fast-test counts, all new test names, and explicit reasons for changed legacy assertions. |
| AC8 | ADR-005 documents the venue/ledger model, persistence and migration choices, assumptions, fail-closed behavior, and the explicit exception to ADR-004. |