"""Risk aggregator orchestration, compatibility facade, and CLI.

The implementation is decomposed by responsibility under ``src.risk``. This
module retains the stable command entry point and legacy import surface.
"""

# ruff: noqa: I001

from __future__ import annotations

import argparse
import copy
import json
import logging
import os
import signal
import sys
import threading
import time
from dataclasses import fields as dataclass_fields
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.orchestrator.registry import ExitCode, load_registry, validate_registry_relative_path
if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from src.orchestrator.registry import StrategyEntry

# Explicit aliases are the facade's compatibility surface.
from src.risk.accounting import (
    AggregatorState as AggregatorState,
    _apply_successful_reconciliation as _apply_successful_reconciliation,
    _invalidate_cached_enforcement_provenance as _invalidate_cached_enforcement_provenance,
    _record_reconciliation_failure as _record_reconciliation_failure,
    _require_derived_decimal as _require_derived_decimal,
    compute_group_metrics as compute_group_metrics,
    determine_signals as determine_signals,
)
from src.risk.config import (
    LIVE_CAPABLE_STATES as LIVE_CAPABLE_STATES,
    RISK_VISIBLE_STATES as RISK_VISIBLE_STATES,
    AggregatorConfig as AggregatorConfig,
    ConfigError as ConfigError,
    _checkpoint_file as _checkpoint_file,
    _ledger_file as _ledger_file,
    _load_risk_group_block as _load_risk_group_block,
    _state_file as _state_file,
    _validate_risk_group_slug as _validate_risk_group_slug,
    load_aggregator_config as load_aggregator_config,
)
from src.risk.ledger import (
    FillLedger,
    LedgerError,
    decimal_arithmetic_context,
)
from src.risk.ledger import VenueLedgerBatch as VenueLedgerBatch
from src.risk.observations import (
    LOG_FINGERPRINT_BYTES as LOG_FINGERPRINT_BYTES,
    LOG_READ_CHUNK_SIZE as LOG_READ_CHUNK_SIZE,
    VENUE_CLIENT_ALLOWED_PREFIXES as VENUE_CLIENT_ALLOWED_PREFIXES,
    LogParseResult as LogParseResult,
    NullVenueClient as NullVenueClient,
    ReconciliationValidationError as ReconciliationValidationError,
    StrategyLogStatus as StrategyLogStatus,
    VenueAccountSnapshot as VenueAccountSnapshot,
    VenueClient as VenueClient,
    VenueClientLoadError as VenueClientLoadError,
    VenueOrder as VenueOrder,
    VenueOrdersObservation as VenueOrdersObservation,
    VenuePosition as VenuePosition,
    VenuePositionsObservation as VenuePositionsObservation,
    _is_null_venue_client as _is_null_venue_client,
    _log_null_venue_risk_visible_refusal as _log_null_venue_risk_visible_refusal,
    _materialize_venue_collections as _materialize_venue_collections,
    _validate_venue_cycle as _validate_venue_cycle,
    load_group_strategies as load_group_strategies,
    load_venue_client as load_venue_client,
    read_strategy_log_delta as read_strategy_log_delta,
    resolve_venue_client_spec as resolve_venue_client_spec,
)
from src.risk.persistence import (
    CHECKPOINT_SCHEMA_VERSION as CHECKPOINT_SCHEMA_VERSION,
    AggregatorWriterLockError as AggregatorWriterLockError,
    _exclusive_ledger_directory_lock as _exclusive_ledger_directory_lock,
    load_checkpoint as load_checkpoint,
    save_checkpoint as save_checkpoint,
)
from src.risk.publication import (
    STATE_SCHEMA_VERSION as STATE_SCHEMA_VERSION,
    _publish_startup_fail_closed_state as _publish_startup_fail_closed_state,
    publish_state as publish_state,
    state_to_dict as state_to_dict,
    validate_state_metric_metadata as validate_state_metric_metadata,
)

logger = logging.getLogger("aggregator")

class _JsonFormatter(logging.Formatter):
    """Emit one JSON object per line with ts, level, event, and risk_group."""

    def __init__(self, risk_group: str = "") -> None:
        super().__init__()
        self._risk_group = risk_group

    def format(self, record: logging.LogRecord) -> str:
        obj: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "event": record.getMessage(),
        }
        if self._risk_group:
            obj["risk_group"] = self._risk_group
        return json.dumps(obj, default=str)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def reconcile_once(
    client: VenueClient,
    config: AggregatorConfig,
    strategies: list[StrategyEntry],
    state: AggregatorState,
    log_statuses: dict[str, StrategyLogStatus],
    project_root: Path,
    *,
    now_utc: datetime | None = None,
    clock: Callable[[], datetime] | None = None,
    ledger: FillLedger | None = None,
) -> AggregatorState:
    """Reconcile one complete venue snapshot and ledger batch.

    Enforcement state is changed only after every authoritative input validates
    and the ledger transaction commits. Failures preserve the last-known state.
    """
    if now_utc is not None and (
        now_utc.tzinfo is None or now_utc.utcoffset() is None
    ):
        raise ValueError("now_utc must be timezone-aware")
    cycle_start = (
        now_utc.astimezone(UTC) if now_utc is not None else datetime.now(UTC)
    )
    if clock is None:
        clock = _utc_now
    using_null_venue = _is_null_venue_client(client)

    strategy_ids = [s.id for s in strategies]
    ledger_mutation_started = False
    try:
        active_ledger = ledger or FillLedger(
            _ledger_file(project_root, config.risk_group),
            config.account_scope,
            config.quote_currency,
        )
        snapshot = client.fetch_account_snapshot(config.account_scope)
        positions_observation = client.fetch_group_positions(strategy_ids)
        orders_observation = client.fetch_open_orders(strategy_ids)
        batch = client.fetch_ledger_batch(
            config.account_scope,
            strategy_ids,
            active_ledger.cursor,
        )
        (
            positions_observation,
            orders_observation,
            batch,
        ) = _materialize_venue_collections(
            positions_observation,
            orders_observation,
            batch,
        )
        # Read the clock only after all venue I/O. A slow fetch must not make
        # an observation look fresher than it is when enforcement consumes it.
        reconciliation_time = clock()
        if (
            not isinstance(reconciliation_time, datetime)
            or reconciliation_time.tzinfo is None
            or reconciliation_time.utcoffset() is None
        ):
            raise ReconciliationValidationError(
                "reconciliation clock must return a timezone-aware datetime"
            )
        reconciliation_time = reconciliation_time.astimezone(UTC)
        enforcement_cut = _validate_venue_cycle(
            snapshot,
            positions_observation,
            orders_observation,
            batch,
            strategies,
            config,
            reconciliation_time,
        )
        ledger_mutation_started = True
        active_ledger.ingest_batch(batch, set(strategy_ids))
        daily_realized_pnl = active_ledger.realized_pnl_for_day(
            cycle_start.date(),
            through=enforcement_cut,
        )
        full_daily_realized_pnl = active_ledger.realized_pnl_for_day(
            cycle_start.date()
        )
        with decimal_arithmetic_context():
            pending_daily_realized_pnl = (
                full_daily_realized_pnl - daily_realized_pnl
            )
        _require_derived_decimal(daily_realized_pnl, "daily_realized_pnl")
        _require_derived_decimal(
            pending_daily_realized_pnl,
            "pending_daily_realized_pnl",
        )
        ledger_binding = active_ledger.binding
        ledger_as_of = ledger_binding.as_of
    except Exception as exc:
        if ledger_mutation_started:
            state.checkpoint_save_allowed = False
        _record_reconciliation_failure(
            state,
            config,
            exc,
            force_fail_closed=(
                using_null_venue
                or ledger_mutation_started
                or isinstance(
                    exc,
                    (ReconciliationValidationError, LedgerError),
                )
            ),
        )
        if ledger_mutation_started:
            _invalidate_cached_enforcement_provenance(state)
        if using_null_venue:
            state.last_success_ts = None
        return state

    try:
        staged_state = copy.deepcopy(state)
        staged_log_statuses = copy.deepcopy(log_statuses)
        _apply_successful_reconciliation(
            state=staged_state,
            log_statuses=staged_log_statuses,
            config=config,
            strategies=strategies,
            project_root=project_root,
            cycle_start=cycle_start,
            reconciliation_time=reconciliation_time,
            snapshot=snapshot,
            positions_observation=positions_observation,
            orders_observation=orders_observation,
            daily_realized_pnl=daily_realized_pnl,
            pending_daily_realized_pnl=pending_daily_realized_pnl,
            ledger_as_of=ledger_as_of,
            ledger_binding=ledger_binding,
        )
    except Exception as exc:
        _record_reconciliation_failure(
            state,
            config,
            exc,
            force_fail_closed=True,
        )
        _invalidate_cached_enforcement_provenance(state)
        return state

    for state_field in dataclass_fields(AggregatorState):
        setattr(state, state_field.name, getattr(staged_state, state_field.name))
    log_statuses.clear()
    log_statuses.update(staged_log_statuses)
    return state


def run_forever(
    config: AggregatorConfig,
    registry_path: Path,
    project_root: Path,
    client: VenueClient,
    stop_event: threading.Event | None = None,
    *,
    max_iterations: int | None = None,
) -> int:
    """Run one exclusively owned risk-group aggregator until stopped."""
    ledger_path = _ledger_file(project_root, config.risk_group)
    try:
        with _exclusive_ledger_directory_lock(ledger_path):
            return _run_forever_locked(
                config,
                registry_path,
                project_root,
                client,
                stop_event,
                max_iterations=max_iterations,
            )
    except AggregatorWriterLockError as exc:
        logger.critical("%s; refusing to start", exc)
        return int(ExitCode.INVARIANT_VIOLATION)


def _save_checkpoint_for_publication(
    path: Path,
    state: AggregatorState,
    log_statuses: dict[str, StrategyLogStatus],
    *,
    ledger: FillLedger,
) -> bool:
    """Contain checkpoint failures so the loop can publish fail-closed state."""
    try:
        return save_checkpoint(path, state, log_statuses, ledger=ledger)
    except Exception as exc:
        logger.critical("checkpoint save failed; publishing fail-closed state: %s", exc)
        _invalidate_cached_enforcement_provenance(state)
        return False


def _run_forever_locked(
    config: AggregatorConfig,
    registry_path: Path,
    project_root: Path,
    client: VenueClient,
    stop_event: threading.Event | None = None,
    *,
    max_iterations: int | None = None,
) -> int:
    """Reconcile every poll_interval_s. Returns 0 on clean shutdown."""
    state = AggregatorState(risk_group=config.risk_group)
    log_statuses: dict[str, StrategyLogStatus] = {}
    state_path = _state_file(project_root, config.risk_group)
    checkpoint_path = _checkpoint_file(project_root, config.risk_group)
    ledger_path = _ledger_file(project_root, config.risk_group)
    ledger_existed = ledger_path.exists()
    try:
        ledger = FillLedger(
            ledger_path,
            config.account_scope,
            config.quote_currency,
        )
    except Exception as exc:
        state.fail_closed = True
        logger.critical("ledger initialization failed; refusing to start: %s", exc)
        publish_state(state_path, state, config)
        return int(ExitCode.INVARIANT_VIOLATION)
    checkpoint_exists = checkpoint_path.exists()
    try:
        checkpoint_loaded = load_checkpoint(
            checkpoint_path,
            state,
            log_statuses,
            ledger=ledger,
            config=config,
        )
    except Exception as exc:
        state.fail_closed = True
        logger.critical(
            "checkpoint recovery failed; refusing to start: %s",
            exc,
        )
        publish_state(state_path, state, config)
        return int(ExitCode.INVARIANT_VIOLATION)
    if (ledger_existed or checkpoint_exists) and not checkpoint_loaded:
        state.fail_closed = True
        logger.critical(
            "ledger/checkpoint recovery pair is incomplete; drawdown baseline is unknown"
        )
        publish_state(state_path, state, config)
        return int(ExitCode.INVARIANT_VIOLATION)
    iterations = 0
    while True:
        if stop_event is not None and stop_event.is_set():
            break
        if max_iterations is not None and iterations >= max_iterations:
            break
        cycle_start = time.monotonic()
        try:
            doc = load_registry(registry_path)
        except Exception as exc:
            _record_reconciliation_failure(state, config, exc)
            _save_checkpoint_for_publication(
                checkpoint_path,
                state,
                log_statuses,
                ledger=ledger,
            )
            publish_state(state_path, state, config)
            time.sleep(min(config.poll_interval_s, 5.0))
            iterations += 1
            continue
        strategies = load_group_strategies(doc, config.risk_group)
        if _is_null_venue_client(client) and strategies:
            _log_null_venue_risk_visible_refusal(config.risk_group, strategies)
            state.fail_closed = True
            _save_checkpoint_for_publication(
                checkpoint_path,
                state,
                log_statuses,
                ledger=ledger,
            )
            publish_state(state_path, state, config)
            return int(ExitCode.INVARIANT_VIOLATION)
        state = reconcile_once(
            client,
            config,
            strategies,
            state,
            log_statuses,
            project_root,
            ledger=ledger,
        )
        _save_checkpoint_for_publication(
            checkpoint_path,
            state,
            log_statuses,
            ledger=ledger,
        )
        publish_state(state_path, state, config)
        iterations += 1
        elapsed = time.monotonic() - cycle_start
        sleep_for = max(0.0, config.poll_interval_s - elapsed)
        if stop_event is not None:
            stop_event.wait(sleep_for)
        else:
            time.sleep(sleep_for)
    # Final shutdown publish with healthy=false (last_success_ts is preserved but
    # bots should not trust an aggregator that has exited).
    state.fail_closed = True
    _save_checkpoint_for_publication(
        checkpoint_path,
        state,
        log_statuses,
        ledger=ledger,
    )
    publish_state(state_path, state, config)
    return int(ExitCode.OK)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="risk.aggregator")
    parser.add_argument("--risk-group", required=True)
    parser.add_argument(
        "--project-root",
        default=os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()),
    )
    parser.add_argument("--registry", default=None)
    parser.add_argument("--config", default=None)
    parser.add_argument(
        "--venue-client",
        default=None,
        help=(
            "Dotted-path spec for the VenueClient implementation, e.g. "
            "'src.risk.venues.binance:BinanceVenueClient'. "
            "Overrides the 'venue_client' key in risk_groups.toml."
        ),
    )
    args = parser.parse_args(argv)

    project_root = Path(args.project_root).resolve()
    registry_path = (
        Path(args.registry) if args.registry else project_root / "config" / "registry.toml"
    )
    config_path = (
        Path(args.config) if args.config else project_root / "config" / "risk_groups.toml"
    )

    handler = logging.StreamHandler()
    handler.setFormatter(_JsonFormatter(risk_group=args.risk_group))
    logging.basicConfig(level=logging.INFO, handlers=[handler])

    try:
        _validate_risk_group_slug(args.risk_group)
        config = load_aggregator_config(config_path, args.risk_group)
        _ledger_file(project_root, config.risk_group)
        _state_file(project_root, config.risk_group)
        _checkpoint_file(project_root, config.risk_group)
    except ConfigError as exc:
        logger.error("config error: %s", exc)
        return int(ExitCode.INVARIANT_VIOLATION)

    # Resolve and load the venue client.
    raw_block = _load_risk_group_block(config_path, args.risk_group)
    venue_spec = resolve_venue_client_spec(args.venue_client, raw_block)
    client: VenueClient
    if venue_spec is not None:
        try:
            client = load_venue_client(venue_spec)
        except VenueClientLoadError as exc:
            logger.critical(
                "failed to load venue client from spec %r: %s -- "
                "refusing to start (fail-closed)",
                venue_spec,
                exc,
            )
            _publish_startup_fail_closed_state(project_root, config)
            return int(ExitCode.INVARIANT_VIOLATION)
        logger.info("venue client loaded from spec: %s", venue_spec)
    else:
        client = NullVenueClient()
        logger.warning(
            "no venue client configured; using NullVenueClient (empty data). "
            "Set --venue-client or 'venue_client' in risk_groups.toml for live use."
        )

    # Startup-time path validation for every strategy in this risk_group.
    try:
        doc = load_registry(registry_path)
    except Exception as exc:
        logger.error("registry load failed at startup: %s", exc)
        _publish_startup_fail_closed_state(project_root, config)
        return int(ExitCode.INVARIANT_VIOLATION)
    risk_visible = load_group_strategies(doc, config.risk_group)
    if _is_null_venue_client(client) and risk_visible:
        _log_null_venue_risk_visible_refusal(config.risk_group, risk_visible)
        _publish_startup_fail_closed_state(project_root, config)
        return int(ExitCode.INVARIANT_VIOLATION)
    for entry in load_group_strategies(doc, config.risk_group):
        try:
            validate_registry_relative_path(project_root, entry.log_path, "logs/strategies")
            validate_registry_relative_path(project_root, entry.state_path, "state/strategies")
            validate_registry_relative_path(project_root, entry.config_path, "config/strategies")
        except ValueError as exc:
            logger.error("path validation failed for %s: %s", entry.id, exc)
            _publish_startup_fail_closed_state(project_root, config)
            return int(ExitCode.INVARIANT_VIOLATION)

    entry_count = len(load_group_strategies(doc, config.risk_group))
    if entry_count:
        logger.info(
            "aggregator starting for risk_group=%s (%d strategies)",
            config.risk_group,
            entry_count,
        )
    else:
        logger.warning(
            "aggregator starting with zero active strategies for risk_group=%s",
            config.risk_group,
        )

    stop_event = threading.Event()

    def _signal_handler(signum: int, frame: Any) -> None:  # noqa: ARG001
        logger.info("received signal %d, shutting down", signum)
        stop_event.set()

    signal.signal(signal.SIGINT, _signal_handler)
    if sys.platform != "win32":
        signal.signal(signal.SIGTERM, _signal_handler)
    else:
        signal.signal(signal.SIGBREAK, _signal_handler)  # type: ignore[attr-defined]

    return run_forever(config, registry_path, project_root, client, stop_event)


if __name__ == "__main__":
    raise SystemExit(main())
