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

## Addendum 1: Corrections for review findings (PM-approved, 2026-09-05)

The fresh review (`review.md`, verdict CHANGES_REQUIRED) enumerated eight
findings. Each must be fixed in this corrections pass, with the named
regression test added. The change surface is unchanged.

- C1 (Critical, finding 1): The consumer-side state validator must
  recompute freshness from `as_of_ts` against the caller's current time
  (injectable `now`), rejecting any enforcement metric whose recomputed age
  exceeds `max_age_s`. Stored `age_seconds` is informational only. The
  validator must also reject a state file whose `published_at` (add it if
  absent) is older than the health window. Test:
  `test_metric_consumer_recomputes_age_from_as_of_ts`.
- C2 (High, finding 2): Observation validation must enforce a maximum age
  for the account snapshot and ledger batch (bounded by `health_window_s`).
  A stale observation is a failed cycle: it must not reset `fail_closed`,
  must not recompute or clear `soft_cap`/`hard_cap`/`margin_emergency`,
  and must not clear residual strategies. Tests:
  `test_stale_snapshot_preserves_caps_and_fail_closed`.
- C3 (High, finding 3): `VenuePosition` and `VenueOrder` responses must
  carry their own observation timestamp and completeness. Introduce a
  positions/orders observation container (or fields on a snapshot-level
  result) with `as_of` and `complete`. Exposure, unrealized PnL, and counts
  publish provenance from that observation, not from the account snapshot.
  An incomplete or stale position/order observation is a failed cycle and
  cannot clear residual strategies. Tests:
  `test_incomplete_position_observation_cannot_clear_residual`,
  `test_position_metrics_carry_their_own_observation_age`.
- C4 (High, finding 4): Bind checkpoint and ledger. The checkpoint must
  record the ledger cursor/generation it was saved against, and the
  checkpoint must be saved in the same reconciliation step as drawdown
  updates, before or atomically with state publication. On restart, if the
  ledger is ahead of the checkpoint binding, drawdown baselines are treated
  as unverified and the aggregator stays unhealthy (fail closed) until a
  fresh authoritative cycle re-establishes them; HWM must never be lowered
  by the mismatch. The checkpoint must also persist last-known snapshot,
  exposure, PnL, and provenance so a failed first cycle after restart keeps
  cached venue state per multi-strategy.md section 6. Tests:
  `test_crash_between_ledger_commit_and_checkpoint_fails_closed_without_lowering_hwm`,
  `test_restart_then_venue_failure_retains_cached_state`.
- C5 (High, finding 5): Configuration validation rejects non-finite floats
  (`inf`, `nan`) for every numeric field. Test:
  `test_config_rejects_non_finite_values`.
- C6 (High, finding 6): Log parsing must treat `UnicodeDecodeError` (and
  any `ValueError` subclass from decoding) as a malformed line, never
  raising out of `reconcile_once`. Test:
  `test_invalid_utf8_log_line_is_malformed_not_fatal`.
- C7 (Medium, finding 7): Validate `risk_group` as a slug
  (`^[a-z0-9]+(?:-[a-z0-9]+)*$`) at config load and in `main`, and add a
  common-path check for the ledger, state, and checkpoint paths under the
  project root. Test: `test_unsafe_risk_group_is_rejected`.
- C8 (Low, finding 8): The implementation result must actually list every
  new test name, the failing-first evidence (which tests failed before the
  change and why), the modified legacy tests with the reason for each
  change, and map each AC to test names.

Acceptance criteria are unchanged; C1-C7 are the missing evidence for
AC4/AC5/AC6/AC7 and C8 is the AC7 evidence gap. Run the full required
validation again and report before/after counts.

## Addendum 2: Corrections for second review findings (PM-approved, 2026-09-05)

The second fresh review (`review-2.md`, CHANGES_REQUIRED) left three
findings. Fix all three; the change surface is unchanged.

- D1 (Critical): Observation freshness must be evaluated against a clock
  read after the venue fetches complete, not the `now_utc` captured before
  the calls. Introduce an injectable clock callable (default
  `lambda: datetime.now(UTC)`), read it once after all venue I/O for the
  freshness checks, and keep a small configurable future-skew tolerance
  for adapter timestamps. Tests:
  `test_observation_freshness_uses_post_fetch_clock` (an observation
  timestamped during the call is accepted) and
  `test_observation_that_ages_out_during_fetch_is_rejected` (an observation
  fresh at cycle start but stale after slow I/O is a failed cycle that
  preserves caps and residual strategies).
- D2 (High): Any `LedgerError` raised after the ledger transaction commits
  (for example the daily-total query) must force the cycle to fail closed,
  and the checkpoint must not be saved with a ledger binding newer than the
  state it describes. Either skip the checkpoint save on a failed cycle or
  bind the checkpoint to the generation that produced the cached state.
  On restart the mismatch must be detected and the aggregator stays
  unhealthy until a fresh authoritative cycle. Test:
  `test_post_commit_ledger_read_failure_does_not_bind_checkpoint_to_new_generation`
  covering commit -> total-read failure -> checkpoint attempt -> restart.
- D3 (Low, C8 again): Rewrite `implementation-result.md` in a single
  write operation (the previous pass failed on a multi-operation patch to
  this file; see `codex-implement.stderr.txt`). It must contain: every new
  test name in `tests/test_risk/`, the failing-first evidence per group,
  the three replaced legacy tests (`test_unrealized_pnl_no_double_count`,
  `test_realized_pnl_accumulates_across_cycles`,
  `test_restart_loads_checkpoint_no_replay`) each with its replacement and
  reason, and an AC-to-test-name map.

Recorded for a follow-up task, not this one: exposure uses
`size * entry_price`; venue mark or current notional should replace it
once an adapter supplies it.

## Addendum 3: Corrections for third review findings (PM-approved, 2026-09-05)

The third fresh review (`review-3.md`, CHANGES_REQUIRED) left four
findings. Fix all four; the change surface is unchanged.

- E1 (High, D1 incomplete): No code path may evaluate observation
  freshness against a pre-fetch timestamp. Remove the fallback that builds
  `clock` from a fixed `now_utc`; `now_utc` (if kept) is only the cycle
  start used for logging and UTC-day attribution, and freshness always
  uses `clock()` read after venue I/O, defaulting to `datetime.now(UTC)`.
  Update callers and tests so determinism comes from injecting `clock`.
  Test: `test_default_clock_path_rejects_observation_that_ages_out_during_fetch`
  (no explicit clock supplied by the test beyond monkeypatching the module
  clock source; must fail before the fix).
- E2 (High, D2 incomplete): `save_checkpoint` must not reread and adopt
  the latest ledger binding. It must persist the binding recorded by the
  reconciliation cycle that produced the cached state, and refuse (log
  CRITICAL, skip save) when the ledger's current binding differs from that
  recorded binding. Additionally take an exclusive advisory lock on the
  ledger directory for the lifetime of `run_forever` so a second aggregator
  process for the same risk group fails to start (single-writer). Tests:
  `test_checkpoint_save_refuses_when_ledger_advanced_concurrently`,
  `test_second_aggregator_instance_for_same_group_is_refused`.
- E3 (High): `authoritative` and `complete` on observations and ledger
  batches must be validated as exact booleans (`is True`, and reject any
  non-`bool` type with a validation error) in both `src/risk/aggregator.py`
  and `src/risk/ledger.py`. Tests:
  `test_non_boolean_completeness_flag_fails_closed` (aggregator) and
  `test_non_boolean_batch_flags_fail_closed` (ledger), covering the string
  `"false"`, integer `1`, and `None`.
- E4 (Low, C8/D3 again): The PM has generated
  `.claude/tasks/risk-ledger-accounting-001/test-evidence.md` from the
  diff (new test names, replaced legacy tests with reasons, counts).
  Codex must: (a) append to that file a "Failing-first evidence" section
  listing, per corrections group (C1-C7, D1-D2, E1-E3), which named tests
  failed before the fix and passed after, with the pytest summary lines;
  (b) write `implementation-result.md` in English, plain ASCII, via a
  single whole-file write (not an incremental patch), and reference
  `test-evidence.md` instead of claiming the list is inline.

## Addendum 4: Corrections for fourth review findings plus PM finding (PM-approved, 2026-09-05)

The fourth fresh review (`review-4.md`, CHANGES_REQUIRED) left four
findings; the PM found one more. Fix all six; the change surface is
unchanged. The implement phase must not write `review.md` (see approval
integrity incident note).

- F1 (PM, High): `src/risk/aggregator.py` imports `fcntl` unconditionally
  at module top. CI runs the fast suite on `windows-latest`, and `main`
  explicitly supports Windows (SIGBREAK). Make the writer lock portable:
  `fcntl.flock` on POSIX and `msvcrt.locking` on Windows behind a
  platform-conditional import, with the same fail-closed
  `AggregatorWriterLockError` semantics. The module must import on both
  platforms. Test: `test_writer_lock_backend_selected_per_platform`
  (monkeypatch `sys.platform` and the backend hooks; must not require a
  real Windows host).
- F2 (Critical, finding 1): Materialize every venue collection
  (positions, orders, fills, cash events) exactly once into an immutable
  tuple before validation, and reject non-sequence or one-shot inputs fail
  closed. Reuse the materialized tuples for accounting. Tests:
  `test_generator_position_observation_is_materialized_once`,
  `test_generator_ledger_batch_is_materialized_once` (generators must
  yield the same accounting as tuples; nothing disappears and the cursor
  only advances with the records inserted).
- F3 (High, finding 2): `save_checkpoint` returns a result or raises; a
  ledger-binding mismatch must set `fail_closed`, invalidate provenance
  for cached PnL/exposure, and cause `_is_healthy` to be false in the
  published state. Test:
  `test_checkpoint_binding_mismatch_publishes_unhealthy_state`.
- F4 (High, finding 3): Validate `Decimal` magnitude and exponent ranges
  for size, price, PnL, fees, balance, equity, and margin (reject values
  outside a documented bound, for example `abs(adjusted()) > 40`), and
  wrap all post-commit accounting in the same fail-closed path as D2 so no
  exception escapes `reconcile_once` or `run_forever` without publishing
  fail-closed state. Tests:
  `test_extreme_finite_decimal_is_rejected_before_commit`,
  `test_post_commit_accounting_exception_publishes_fail_closed`.
- F5 (AC3 coverage gap): Split the combined residual test so deprecated
  strategy position PnL and cap contribution, and retired strategy
  residual behavior, are each proven independently. Tests:
  `test_deprecated_strategy_position_pnl_counts_toward_caps`,
  `test_retired_strategy_residual_order_counts_until_flat`.
- F6 (Low, finding 4, E4 again): `implementation-result.md` must be
  English, plain ASCII, written in one whole-file write, and its AC table
  must name the tests proving each AC. Also append an "AC-to-test map"
  section to `test-evidence.md`.

## Addendum 5: Corrections for fifth review findings (PM-approved, 2026-09-05)

The fifth fresh review (`review-5.md`, CHANGES_REQUIRED) left five
findings. Fix all five; the change surface is unchanged. The implement
phase must not write `review.md`.

- G1 (High, finding 1, accounting cut skew): Realized and unrealized PnL
  must describe one consistent accounting cut. Enforce a common-cut
  invariant: the daily realized total used for caps only includes ledger
  events with `occurred_at <= positions_observation.as_of` (events after
  the position cut are held in a pending bucket that is published as
  telemetry and folded in on the next cycle whose position cut covers
  them), and a position observation older than the ledger batch by more
  than a configurable skew (default: the poll interval) is a failed cycle.
  Document the invariant in ADR-005. Tests:
  `test_ledger_events_after_position_cut_do_not_double_count_unrealized`
  (the review's 12:00/12:01 example must yield -50, not +50) and
  `test_position_cut_older_than_ledger_skew_fails_cycle`.
- G2 (High, finding 2, checkpoint trust): Schema-v3 checkpoint loading
  must validate every field with exact types and required presence (no
  zero defaults for financial values or counts, no `bool(...)` coercion,
  `is True`/`is False` only), and enforce invariants (hard cap implies
  soft cap; drawdown baselines present when `drawdown_baseline_verified`
  is true; non-negative counts). Any violation is a corrupt checkpoint and
  follows the existing fail-closed corrupt-checkpoint path. Tests:
  `test_malformed_schema_v3_checkpoint_is_rejected` parameterized over a
  missing financial field, a string boolean, and a cap-invariant
  violation.
- G3 (High, finding 3, startup containment): `load_checkpoint` and the
  startup path in `_run_forever_locked` must catch `LedgerError` (and any
  `Exception` from ledger metadata reads), publish fail-closed state, and
  either retry on the next cycle or exit non-zero after publishing; no
  exception may escape `run_forever` without a fail-closed publication.
  Test: `test_ledger_error_during_checkpoint_load_publishes_fail_closed`.
- G4 (Medium, finding 4, ledger metadata): Ledger metadata validation must
  require `generation`, `cursor`, and `as_of` with exact types once the
  ledger has any row or a non-initial generation; a missing or
  inconsistent value is `LedgerSchemaError`, never a silent generation
  zero. A brand-new empty ledger is the only state allowed to initialize
  metadata. Test: `test_missing_or_inconsistent_ledger_metadata_is_refused`
  parameterized over missing generation, missing cursor, and generation
  present with rows but cursor absent.
- G5 (Low, finding 5): Rewrite `implementation-result.md` with no trailing
  whitespace; `git diff --check` must be run last and its exit code
  recorded truthfully.

## Addendum 6: Corrections for sixth review findings (PM-approved, 2026-09-05)

The sixth fresh review (`review-6.md`, CHANGES_REQUIRED) left three
findings. Fix all three; the change surface is unchanged. The implement
phase must not write `review.md`.

- H1 (High, finding 1, cut symmetry): The common accounting cut must be
  two-sided. The enforcement cut is `min(positions_observation.as_of,
  batch.as_of)`; a position observation newer than the ledger completeness
  watermark by more than `accounting_cut_max_skew_s` is a failed cycle
  that preserves caps, `fail_closed`, and residual state, exactly like the
  older-than case. Where the position cut is within skew but newer than
  the ledger watermark, realized PnL is cut at the ledger watermark and
  the unrealized component is labeled with the ledger watermark as its
  effective cut in provenance. Update ADR-005 wording. Tests:
  `test_position_cut_newer_than_ledger_watermark_fails_cycle` (the
  review's 12:00 / 12:01 / 12:00:30 example must not publish healthy zero
  PnL) and `test_enforcement_cut_is_min_of_position_and_ledger_cuts`.
- H2 (High, finding 2, Decimal exactness): All ledger accumulation,
  exposure multiplication, and unrealized summation must run under an
  isolated `decimal.localcontext()` whose precision is sufficient for the
  documented bound (exponent/scale 40 implies at least 82 significant
  digits for products; choose and document the value) with
  `traps=[Inexact, Rounded, Overflow, InvalidOperation]` so any rounding
  raises and is handled as a fail-closed validation error, never silent.
  Ambient global-context changes must not affect results. Tests:
  `test_ledger_accumulation_is_exact_for_supported_domain` (the review's
  0.01 example and a shuffled-order equality check) and
  `test_accounting_is_independent_of_global_decimal_context`.
- H3 (Low, finding 3, F6 again): Every row of the AC table in
  `implementation-result.md` must contain only exact test function names
  (comma separated), no prose descriptions.

## Addendum 7: Corrections for seventh review findings (PM-approved, 2026-09-05)

The seventh fresh review (`review-7.md`, CHANGES_REQUIRED) left six
findings. Fix all six; the change surface is unchanged. The implement
phase must not write `review.md`.

- I1 (High, finding 1, domain closure): Separate the input bound from the
  derived-value bound. Inputs keep the documented bound (adjusted exponent
  40); derived and persisted values (exposure, daily totals, drawdown,
  checkpoint fields) use a documented wider bound (for example adjusted
  exponent 100, comfortably inside the 256-digit context) so every value
  computable from valid inputs is storable, restorable, and queryable.
  Update ADR-005 and the ledger/aggregator docstrings. Tests:
  `test_exposure_from_boundary_inputs_round_trips_through_checkpoint` and
  `test_daily_total_from_boundary_ledger_entries_is_queryable`.
- I2 (High, finding 2, ambient rounding in caps): `determine_signals`,
  drawdown percentage arithmetic, and checkpoint PnL-consistency
  arithmetic must run inside the isolated exact context. Cap comparisons
  must be exact: compare `-pnl * 100` against `threshold * balance` (or
  equivalent cross-multiplication) rather than dividing, so no rounding
  occurs. Test: `test_hard_cap_boundary_is_exact_without_ambient_rounding`
  (the review's `-4.9999999999999999999999999999` / `100` example must
  not set `hard_cap`).
- I3 (Medium, finding 3, allowed skew health): `_is_healthy` and the
  consumer validator must accept negative ages down to
  `-future_skew_tolerance_s` (published in the state so consumers can
  apply the same bound) and reject beyond it. Test:
  `test_allowed_future_skew_publishes_healthy_and_validates`.
- I4 (Medium, finding 4, CLI NullVenue path): The `main` NullVenue
  refusal for live-capable strategies must publish fail-closed unhealthy
  state before returning non-zero, using the same publication path as
  `run_forever`. Test: `test_main_null_venue_refusal_publishes_fail_closed_state`.
- I5 (Low, finding 5, H3 again): Every AC row in
  `implementation-result.md`, including AC4, AC6, AC7, and AC8, contains
  only exact comma-separated test function names. For AC7, list the
  regression tests added in this pass.
- I6 (Low, finding 6): Fix the `accounting_cut_max_skew_s` comment in
  `config/risk_groups.toml` to describe the symmetric rule.
