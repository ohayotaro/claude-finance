"""Exact accounting and enforcement state transitions."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal, Inexact, Rounded
from typing import TYPE_CHECKING

from src.orchestrator.registry import validate_registry_relative_path
from src.risk.config import LIVE_CAPABLE_STATES, AggregatorConfig
from src.risk.ledger import (
    DECIMAL_DERIVED_MAX_ADJUSTED_EXPONENT,
    DECIMAL_DERIVED_MAX_SCALE,
    LedgerBinding,
    decimal_arithmetic_context,
)
from src.risk.observations import (
    StrategyLogStatus,
    VenueAccountSnapshot,
    VenueOrdersObservation,
    VenuePosition,
    VenuePositionsObservation,
    _require_decimal_in_domain,
    _require_input_decimal,
    read_strategy_log_delta,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from pathlib import Path
    from typing import Any

    from src.orchestrator.registry import StrategyEntry

logger = logging.getLogger("aggregator")

@dataclass(slots=True)
class AggregatorState:
    risk_group: str
    last_success_ts: datetime | None = None
    consecutive_failures: int = 0
    fail_closed: bool = False
    soft_cap: bool = False
    hard_cap: bool = False
    margin_emergency: bool = False
    warnings: list[str] = field(default_factory=list)
    quarantined_strategies: set[str] = field(default_factory=set)
    last_snapshot: VenueAccountSnapshot | None = None
    group_net_exposure: Decimal = Decimal("0")
    group_gross_exposure: Decimal = Decimal("0")
    group_daily_pnl: Decimal = Decimal("0")
    open_position_count: int = 0
    open_order_count: int = 0
    daily_realized_pnl: Decimal = Decimal("0")
    # Ledger PnL observed after the enforcement cut. Telemetry only until a
    # later position observation covers the events.
    pending_daily_realized_pnl: Decimal = Decimal("0")
    daily_unrealized_pnl: Decimal = Decimal("0")
    # Supplemental log telemetry only. Never contributes to cap decisions.
    latest_unrealized: dict[tuple[str, str], Decimal] = field(default_factory=dict)
    current_utc_date: date | None = None
    start_of_day_equity: Decimal | None = None
    high_water_mark: Decimal | None = None
    drawdown_sod_pct: Decimal = Decimal("0")
    drawdown_hwm_pct: Decimal = Decimal("0")
    residual_strategy_ids: set[str] = field(default_factory=set)
    # Account, position, and order observations have independent authority.
    venue_as_of_ts: datetime | None = None
    positions_as_of_ts: datetime | None = None
    orders_as_of_ts: datetime | None = None
    ledger_as_of_ts: datetime | None = None
    log_as_of_ts: datetime | None = None
    checkpoint_ledger_cursor: str | None = None
    checkpoint_ledger_generation: int | None = None
    drawdown_baseline_verified: bool = False
    # Transient crash-safety gate. A ledger write followed by a failed state
    # calculation must not let a checkpoint claim the newer ledger binding.
    checkpoint_save_allowed: bool = True


def compute_group_metrics(
    positions: Iterable[VenuePosition],
) -> tuple[Decimal, Decimal, int]:
    """Return (net_exposure, gross_exposure, position_count). Signs by side."""
    with decimal_arithmetic_context():
        net = Decimal("0")
        gross = Decimal("0")
        count = 0
        for p in positions:
            notional = p.size * p.entry_price
            gross += abs(notional)
            net += notional if p.side == "long" else -notional
            count += 1
    return net, gross, count


def determine_signals(state: AggregatorState, config: AggregatorConfig) -> AggregatorState:
    """Apply threshold rules to mutate cap flags. Pure: returns the same instance."""
    snapshot = state.last_snapshot
    state.soft_cap = False
    state.hard_cap = False
    state.margin_emergency = False
    if snapshot is None or snapshot.balance == 0:
        return state
    with decimal_arithmetic_context():
        loss_numerator = -state.group_daily_pnl * Decimal("100")
        hard_cap_boundary = (
            Decimal(str(config.hard_cap_daily_loss_pct)) * snapshot.balance
        )
        soft_cap_boundary = (
            Decimal(str(config.soft_cap_daily_loss_pct)) * snapshot.balance
        )
        if loss_numerator >= hard_cap_boundary:
            state.hard_cap = True
            state.soft_cap = True
        elif loss_numerator >= soft_cap_boundary:
            state.soft_cap = True
        if snapshot.margin_ratio >= Decimal(str(config.margin_emergency_threshold)):
            state.margin_emergency = True
    return state


def _drawdown_percentage(equity: Decimal, baseline: Decimal) -> Decimal:
    """Return a deterministic two-decimal risk metric from an exact numerator."""
    with decimal_arithmetic_context() as arithmetic_context:
        numerator = (equity - baseline) * Decimal("100")
        # A Decimal cannot exactly represent repeating ratios. Risk metrics are
        # published to the repository-standard two decimal places; rounding is
        # enabled only for this explicit final representation step.
        arithmetic_context.traps[Inexact] = False
        arithmetic_context.traps[Rounded] = False
        return (numerator / baseline).quantize(Decimal("0.01"))


def _parse_event_ts(event: dict[str, Any]) -> datetime | None:
    """Best-effort parse of the ``ts`` field to a UTC datetime."""
    raw = event.get("ts")
    if raw is None:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except (ValueError, TypeError):
        return None


def _check_day_boundary(state: AggregatorState, today: date) -> None:
    """Reset daily levels when a successful UTC-day reconciliation arrives."""
    if state.current_utc_date is not None and state.current_utc_date == today:
        return
    # Day boundary crossed (or first cycle ever).
    state.current_utc_date = today
    state.daily_realized_pnl = Decimal("0")
    state.pending_daily_realized_pnl = Decimal("0")
    state.daily_unrealized_pnl = Decimal("0")
    state.latest_unrealized = {}
    # SoD equity baseline will be set on the first successful venue fetch
    # of the new day (in reconcile_once, after the snapshot arrives).
    state.start_of_day_equity = None
    logger.info("UTC day boundary: counters reset for %s", today.isoformat())


def _record_reconciliation_failure(
    state: AggregatorState,
    config: AggregatorConfig,
    exc: Exception,
    *,
    force_fail_closed: bool = False,
) -> None:
    state.consecutive_failures += 1
    msg = f"venue reconciliation failed (attempt {state.consecutive_failures}): {exc}"
    if force_fail_closed or (
        state.consecutive_failures >= config.fail_closed_after_consecutive_failures
    ):
        if not state.fail_closed:
            logger.critical("entering fail-closed: %s", msg)
        state.fail_closed = True
    elif state.consecutive_failures >= 3:
        logger.critical(msg)
    else:
        logger.warning(msg)


def _invalidate_cached_enforcement_provenance(state: AggregatorState) -> None:
    """Keep cached amounts but make their unbound authority visibly unusable."""
    state.fail_closed = True
    state.checkpoint_save_allowed = False
    state.drawdown_baseline_verified = False
    state.last_success_ts = None
    state.venue_as_of_ts = None
    state.positions_as_of_ts = None
    state.orders_as_of_ts = None
    state.ledger_as_of_ts = None


def _require_derived_decimal(value: Decimal, field_name: str) -> None:
    """Validate a computed or persisted aggregate against its wider domain."""
    _require_decimal_in_domain(
        value,
        field_name,
        max_adjusted_exponent=DECIMAL_DERIVED_MAX_ADJUSTED_EXPONENT,
        max_scale=DECIMAL_DERIVED_MAX_SCALE,
    )


def _apply_successful_reconciliation(
    *,
    state: AggregatorState,
    log_statuses: dict[str, StrategyLogStatus],
    config: AggregatorConfig,
    strategies: Sequence[StrategyEntry],
    project_root: Path,
    cycle_start: datetime,
    reconciliation_time: datetime,
    snapshot: VenueAccountSnapshot,
    positions_observation: VenuePositionsObservation,
    orders_observation: VenueOrdersObservation,
    daily_realized_pnl: Decimal,
    pending_daily_realized_pnl: Decimal,
    ledger_as_of: datetime | None,
    ledger_binding: LedgerBinding,
) -> None:
    """Stage all post-commit accounting so failures cannot leak partial state."""
    positions = positions_observation.positions
    orders = orders_observation.orders
    _check_day_boundary(state, cycle_start.date())
    state.consecutive_failures = 0
    state.fail_closed = False
    state.last_snapshot = snapshot
    state.last_success_ts = reconciliation_time
    state.venue_as_of_ts = snapshot.timestamp.astimezone(UTC)
    state.positions_as_of_ts = positions_observation.as_of.astimezone(UTC)
    state.orders_as_of_ts = orders_observation.as_of.astimezone(UTC)
    state.ledger_as_of_ts = ledger_as_of
    state.checkpoint_ledger_cursor = ledger_binding.cursor
    state.checkpoint_ledger_generation = ledger_binding.generation
    state.checkpoint_save_allowed = True
    net, gross, count = compute_group_metrics(positions)
    _require_derived_decimal(net, "group_net_exposure")
    _require_derived_decimal(gross, "group_gross_exposure")
    state.group_net_exposure = net
    state.group_gross_exposure = gross
    state.open_position_count = count
    state.open_order_count = len(orders)
    state.daily_realized_pnl = daily_realized_pnl
    state.pending_daily_realized_pnl = pending_daily_realized_pnl
    with decimal_arithmetic_context():
        state.daily_unrealized_pnl = sum(
            (position.unrealized_pnl for position in positions), Decimal("0")
        )
    _require_derived_decimal(state.daily_unrealized_pnl, "daily_unrealized_pnl")

    risk_by_strategy = {
        position.strategy_id
        for position in positions
        if position.strategy_id is not None
    } | {
        order.strategy_id for order in orders if order.strategy_id is not None
    }
    inactive_ids = {
        strategy.id
        for strategy in strategies
        if not (strategy.enabled and strategy.state in LIVE_CAPABLE_STATES)
    }
    state.residual_strategy_ids = risk_by_strategy & inactive_ids

    equity = snapshot.equity
    if state.start_of_day_equity is None and equity > 0:
        state.start_of_day_equity = equity
    if state.high_water_mark is None or equity > state.high_water_mark:
        state.high_water_mark = equity
    if state.start_of_day_equity and state.start_of_day_equity > 0:
        state.drawdown_sod_pct = _drawdown_percentage(
            equity,
            state.start_of_day_equity,
        )
    if state.high_water_mark and state.high_water_mark > 0:
        state.drawdown_hwm_pct = _drawdown_percentage(
            equity,
            state.high_water_mark,
        )
    _require_derived_decimal(state.drawdown_sod_pct, "drawdown_sod_pct")
    _require_derived_decimal(state.drawdown_hwm_pct, "drawdown_hwm_pct")
    state.drawdown_baseline_verified = True

    quarantine_threshold = config.malformed_log_quarantine_per_minute
    position_keys = {
        (position.strategy_id, position.symbol)
        for position in positions
        if position.strategy_id is not None
    }
    state.latest_unrealized = {
        key: value
        for key, value in state.latest_unrealized.items()
        if key in position_keys
    }
    if not state.latest_unrealized:
        state.log_as_of_ts = None
    for strategy in strategies:
        if strategy.id not in log_statuses:
            log_statuses[strategy.id] = StrategyLogStatus(strategy_id=strategy.id)
        status = log_statuses[strategy.id]
        if status.quarantined:
            state.quarantined_strategies.add(strategy.id)
            continue
        try:
            full_log = validate_registry_relative_path(
                project_root,
                f"{strategy.log_path}/bot.jsonl",
                strategy.log_path,
            )
        except ValueError as exc:
            logger.error("path validation failed for %s: %s", strategy.id, exc)
            continue
        try:
            result = read_strategy_log_delta(
                full_log,
                status,
                quarantine_threshold=quarantine_threshold,
            )
        except OSError as exc:
            logger.warning(
                "strategy log read failed: strategy_id=%s error=%s",
                strategy.id,
                exc,
            )
            continue
        status.log_offset = result.new_offset
        for event in result.events:
            if event.get("event") != "position_update":
                continue
            strategy_id = str(event.get("strategy_id", ""))
            symbol = str(event.get("symbol", ""))
            if (strategy_id, symbol) not in position_keys:
                continue
            event_ts = _parse_event_ts(event)
            if event_ts is None or event_ts > reconciliation_time:
                continue
            try:
                telemetry_value = Decimal(str(event.get("unrealized_pnl", 0)))
                _require_input_decimal(telemetry_value, "log unrealized telemetry")
            except Exception:
                continue
            state.latest_unrealized[(strategy_id, symbol)] = telemetry_value
            if state.log_as_of_ts is None or event_ts > state.log_as_of_ts:
                state.log_as_of_ts = event_ts

    with decimal_arithmetic_context():
        state.group_daily_pnl = state.daily_realized_pnl + state.daily_unrealized_pnl
    _require_derived_decimal(state.group_daily_pnl, "group_daily_pnl")
    determine_signals(state, config)


def _validate_persisted_state_decimals(
    state: AggregatorState,
) -> VenueAccountSnapshot | None:
    """Validate the separate input and derived domains before serialization."""
    for derived_value, field_name in (
        (state.group_net_exposure, "group_net_exposure"),
        (state.group_gross_exposure, "group_gross_exposure"),
        (state.group_daily_pnl, "group_daily_pnl"),
        (state.daily_realized_pnl, "daily_realized_pnl"),
        (state.pending_daily_realized_pnl, "pending_daily_realized_pnl"),
        (state.daily_unrealized_pnl, "daily_unrealized_pnl"),
        (state.drawdown_sod_pct, "drawdown_sod_pct"),
        (state.drawdown_hwm_pct, "drawdown_hwm_pct"),
    ):
        _require_derived_decimal(derived_value, field_name)
    for optional_value, field_name in (
        (state.start_of_day_equity, "start_of_day_equity"),
        (state.high_water_mark, "high_water_mark"),
    ):
        if optional_value is not None:
            _require_derived_decimal(optional_value, field_name)
    for telemetry_value in state.latest_unrealized.values():
        _require_input_decimal(telemetry_value, "log unrealized telemetry")
    snapshot = state.last_snapshot
    if snapshot is not None:
        for input_value, field_name in (
            (snapshot.balance, "last_snapshot.balance"),
            (snapshot.equity, "last_snapshot.equity"),
            (snapshot.margin_used, "last_snapshot.margin_used"),
            (snapshot.margin_ratio, "last_snapshot.margin_ratio"),
        ):
            _require_input_decimal(input_value, field_name)
    return snapshot
