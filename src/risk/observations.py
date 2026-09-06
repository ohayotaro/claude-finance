"""Venue observations, adapter loading, and input validation."""

from __future__ import annotations

import hashlib
import importlib
import json
import logging
import math
import os
import re
import time
from collections import deque
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from src.risk.config import RISK_VISIBLE_STATES
from src.risk.ledger import (
    DECIMAL_INPUT_MAX_ADJUSTED_EXPONENT,
    DECIMAL_INPUT_MAX_SCALE,
    VenueLedgerBatch,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path
    from typing import Any

    from src.orchestrator.registry import RegistryDocument, StrategyEntry
    from src.risk.config import AggregatorConfig

logger = logging.getLogger("aggregator")
VENUE_CLIENT_ALLOWED_PREFIXES: tuple[str, ...] = ("src.risk.",)
LOG_READ_CHUNK_SIZE: int = 4 * 1024 * 1024
LOG_FINGERPRINT_BYTES = 256

@dataclass(frozen=True, slots=True)
class VenuePosition:
    strategy_id: str | None
    symbol: str
    side: str
    size: Decimal
    entry_price: Decimal
    unrealized_pnl: Decimal
    account_scope: str
    quote_currency: str


@dataclass(frozen=True, slots=True)
class VenueOrder:
    order_id: str
    strategy_id: str | None
    symbol: str
    side: str
    size: Decimal
    price: Decimal
    status: str
    account_scope: str
    quote_currency: str


@dataclass(frozen=True, slots=True)
class VenuePositionsObservation:
    """One complete, independently timestamped venue position observation.

    ``as_of`` is the true observation timestamp used for provenance and
    freshness. When an adapter returns a later observation containing a
    historical position view, ``as_of_cut`` identifies the financial cut of
    those position values. A supplied cut is accepted only when it exactly
    matches the ledger completeness watermark.
    """

    positions: tuple[VenuePosition, ...]
    as_of: datetime
    complete: bool
    authoritative: bool = True
    as_of_cut: datetime | None = None


@dataclass(frozen=True, slots=True)
class VenueOrdersObservation:
    """One complete, independently timestamped venue open-order observation."""

    orders: tuple[VenueOrder, ...]
    as_of: datetime
    complete: bool
    authoritative: bool = True


@dataclass(frozen=True, slots=True)
class VenueAccountSnapshot:
    account_scope: str
    balance: Decimal
    equity: Decimal
    margin_used: Decimal
    margin_ratio: Decimal
    timestamp: datetime
    quote_currency: str


@runtime_checkable
class VenueClient(Protocol):
    def fetch_account_snapshot(self, account_scope: str) -> VenueAccountSnapshot: ...
    def fetch_group_positions(
        self, strategy_ids: Sequence[str]
    ) -> VenuePositionsObservation: ...
    def fetch_open_orders(
        self, strategy_ids: Sequence[str]
    ) -> VenueOrdersObservation: ...
    def fetch_ledger_batch(
        self,
        account_scope: str,
        strategy_ids: Sequence[str],
        cursor: str | None,
    ) -> VenueLedgerBatch: ...


class NullVenueClient:
    """Returns empty non-authoritative data for test/development setups only."""

    def fetch_account_snapshot(self, account_scope: str) -> VenueAccountSnapshot:
        return VenueAccountSnapshot(
            account_scope=account_scope,
            balance=Decimal("0"),
            equity=Decimal("0"),
            margin_used=Decimal("0"),
            margin_ratio=Decimal("0"),
            timestamp=datetime.now(UTC),
            quote_currency="",
        )

    def fetch_group_positions(
        self, strategy_ids: Sequence[str]
    ) -> VenuePositionsObservation:
        return VenuePositionsObservation(
            positions=(),
            as_of=datetime.now(UTC),
            complete=False,
            authoritative=False,
        )

    def fetch_open_orders(
        self, strategy_ids: Sequence[str]
    ) -> VenueOrdersObservation:
        return VenueOrdersObservation(
            orders=(),
            as_of=datetime.now(UTC),
            complete=False,
            authoritative=False,
        )

    def fetch_ledger_batch(
        self,
        account_scope: str,
        strategy_ids: Sequence[str],
        cursor: str | None,
    ) -> VenueLedgerBatch:
        return VenueLedgerBatch(
            fills=(),
            cash_events=(),
            next_cursor=cursor or "null-non-authoritative",
            as_of=datetime.now(UTC),
            complete=False,
            authoritative=False,
        )


class VenueClientLoadError(Exception):
    """Raised when an explicit venue client spec cannot be loaded or validated."""


def load_venue_client(spec: str) -> VenueClient:
    """Import and instantiate a VenueClient from a dotted-path spec.

    The module portion of the spec is validated against
    ``VENUE_CLIENT_ALLOWED_PREFIXES`` before any import is attempted.
    This prevents arbitrary code execution from a malformed config.

    Args:
        spec: A string in ``module:ClassName`` form, e.g.
            ``"src.risk.venues.binance:BinanceVenueClient"``.

    Returns:
        An instance of the resolved class that satisfies the ``VenueClient``
        protocol.

    Raises:
        VenueClientLoadError: If the module prefix is not in the allowlist,
            the module cannot be imported, the class cannot be found, the
            instance fails the ``VenueClient`` protocol check, or
            instantiation (with no args) raises.
    """
    if ":" not in spec:
        raise VenueClientLoadError(
            f"venue client spec must be 'module:ClassName', got: {spec!r}"
        )
    module_path, class_name = spec.rsplit(":", 1)
    if not any(module_path.startswith(prefix) for prefix in VENUE_CLIENT_ALLOWED_PREFIXES):
        logger.critical(
            "venue client module %r does not match allowed prefixes %r -- "
            "refusing to import (fail-closed)",
            module_path,
            VENUE_CLIENT_ALLOWED_PREFIXES,
        )
        raise VenueClientLoadError(
            f"module {module_path!r} is not in the allowed prefix list "
            f"{VENUE_CLIENT_ALLOWED_PREFIXES!r}"
        )
    try:
        module = importlib.import_module(module_path)
    except Exception as exc:
        raise VenueClientLoadError(
            f"failed to import module {module_path!r}: {exc}"
        ) from exc
    cls = getattr(module, class_name, None)
    if cls is None:
        raise VenueClientLoadError(
            f"class {class_name!r} not found in module {module_path!r}"
        )
    try:
        instance = cls()
    except Exception as exc:
        raise VenueClientLoadError(
            f"failed to instantiate {spec!r}: {exc}"
        ) from exc
    if not isinstance(instance, VenueClient):
        missing = [
            name
            for name in (
                "fetch_account_snapshot",
                "fetch_group_positions",
                "fetch_open_orders",
                "fetch_ledger_batch",
            )
            if not callable(getattr(instance, name, None))
        ]
        raise VenueClientLoadError(
            f"instance from {spec!r} does not satisfy VenueClient protocol; "
            f"missing or non-callable: {missing}"
        )
    return instance


def resolve_venue_client_spec(
    cli_arg: str | None,
    config_block: dict[str, Any] | None,
) -> str | None:
    """Determine the venue client spec from CLI arg or config.

    Precedence (highest first):
      1. ``cli_arg`` (``--venue-client`` on the command line)
      2. ``venue_client`` key in the risk-group config block
      3. ``None`` (fall back to ``NullVenueClient``)

    Args:
        cli_arg: Value of ``--venue-client`` CLI argument, or ``None``.
        config_block: The raw dict for this risk-group from
            ``risk_groups.toml``, or ``None``.

    Returns:
        The dotted-path spec string, or ``None`` if no spec was configured.
    """
    if cli_arg is not None:
        return cli_arg
    if config_block is not None:
        val = config_block.get("venue_client")
        if val is not None:
            return str(val)
    return None


@dataclass(slots=True)
class StrategyLogStatus:
    strategy_id: str
    log_offset: int = 0
    malformed_timestamps: deque[float] = field(default_factory=lambda: deque(maxlen=10_000))
    quarantined: bool = False
    file_device: int | None = None
    file_inode: int | None = None
    prefix_length: int = 0
    prefix_fingerprint: str | None = None
    boundary_start: int = 0
    boundary_fingerprint: str | None = None


@dataclass(frozen=True, slots=True)
class LogParseResult:
    events: list[dict[str, Any]]
    malformed_count: int
    new_offset: int


def load_group_strategies(
    registry_doc: RegistryDocument, risk_group: str
) -> list[StrategyEntry]:
    """Return every registry entry that can carry venue-visible residual risk."""
    return [
        e
        for e in registry_doc.strategies
        if e.risk_group == risk_group and e.state in RISK_VISIBLE_STATES
    ]


def _is_null_venue_client(client: VenueClient) -> bool:
    return isinstance(client, NullVenueClient)


def _log_null_venue_risk_visible_refusal(
    risk_group: str, strategies: Sequence[StrategyEntry]
) -> None:
    strategy_states = ", ".join(f"{entry.id}:{entry.state.value}" for entry in strategies)
    logger.critical(
        "refusing to start risk aggregator for risk_group=%s with NullVenueClient: "
        "risk-visible strategies require authoritative venue reconciliation "
        "(strategy_states=%s)",
        risk_group,
        strategy_states,
    )


def read_strategy_log_delta(
    log_path: Path,
    status: StrategyLogStatus,
    *,
    quarantine_threshold: int,
    now: float | None = None,
    max_bytes: int = LOG_READ_CHUNK_SIZE,
) -> LogParseResult:
    """Tail the JSONL log from `status.log_offset`, parse, skip malformed lines.

    At most ``max_bytes`` (default 4 MB) are read per call. If the unread
    portion of the file is larger, the remainder will be picked up on the
    next cycle via the returned ``new_offset``.
    """
    events: list[dict[str, Any]] = []
    malformed = 0
    try:
        fh = log_path.open("rb")
    except FileNotFoundError:
        return LogParseResult(events=[], malformed_count=0, new_offset=status.log_offset)
    with fh:
        file_stat = os.fstat(fh.fileno())
        identity_known = status.file_device is not None and status.file_inode is not None
        reset_offset = (
            (identity_known and (
                status.file_device != file_stat.st_dev
                or status.file_inode != file_stat.st_ino
            ))
            or file_stat.st_size < status.log_offset
            or (status.log_offset > 0 and not identity_known)
        )
        if not reset_offset and status.prefix_fingerprint and status.prefix_length > 0:
            fh.seek(0)
            prefix = fh.read(status.prefix_length)
            reset_offset = (
                len(prefix) != status.prefix_length
                or hashlib.sha256(prefix).hexdigest() != status.prefix_fingerprint
            )
        if not reset_offset and status.boundary_fingerprint and status.log_offset > 0:
            boundary_length = status.log_offset - status.boundary_start
            fh.seek(status.boundary_start)
            boundary = fh.read(boundary_length)
            reset_offset = (
                len(boundary) != boundary_length
                or hashlib.sha256(boundary).hexdigest() != status.boundary_fingerprint
            )
        start_offset = 0 if reset_offset else status.log_offset
        if reset_offset:
            logger.info(
                "log rotation or truncation detected; replaying telemetry: strategy_id=%s",
                status.strategy_id,
            )
        fh.seek(start_offset)
        remaining = fh.read(max_bytes)
        last_newline = remaining.rfind(b"\n")
        complete = remaining[: last_newline + 1] if last_newline >= 0 else b""
        current_offset = start_offset + len(complete)

        prefix_length = min(file_stat.st_size, LOG_FINGERPRINT_BYTES)
        fh.seek(0)
        prefix = fh.read(prefix_length)
        boundary_start = max(0, current_offset - LOG_FINGERPRINT_BYTES)
        fh.seek(boundary_start)
        boundary = fh.read(current_offset - boundary_start)
        status.file_device = file_stat.st_dev
        status.file_inode = file_stat.st_ino
        status.prefix_length = prefix_length
        status.prefix_fingerprint = hashlib.sha256(prefix).hexdigest()
        status.boundary_start = boundary_start
        status.boundary_fingerprint = hashlib.sha256(boundary).hexdigest()

    if not complete:
        return LogParseResult(events=[], malformed_count=0, new_offset=current_offset)
    ts_now = now if now is not None else time.time()
    relative_offset = 0
    for raw_with_ending in complete.splitlines(keepends=True):
        raw_offset = start_offset + relative_offset
        relative_offset += len(raw_with_ending)
        raw = raw_with_ending.rstrip(b"\r\n")
        if not raw.strip():
            continue
        extracted_strategy_id: object = None
        try:
            event = json.loads(raw)
        except ValueError:
            malformed += 1
            status.malformed_timestamps.append(ts_now)
            match = re.search(
                rb'"strategy_id"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"',
                raw,
            )
            if match is not None:
                extracted_strategy_id = match.group(1).decode(
                    "utf-8", errors="replace"
                )
            logger.warning(
                "malformed log line skipped: strategy_id=%s "
                "extracted_strategy_id=%s offset=%d",
                status.strategy_id,
                extracted_strategy_id,
                raw_offset,
            )
            continue
        if isinstance(event, dict):
            extracted_strategy_id = event.get("strategy_id")
        if (
            not isinstance(event, dict)
            or not all(k in event for k in ("event", "strategy_id", "ts"))
            or event.get("strategy_id") != status.strategy_id
        ):
            malformed += 1
            status.malformed_timestamps.append(ts_now)
            logger.warning(
                "malformed log line skipped: strategy_id=%s "
                "extracted_strategy_id=%s offset=%d",
                status.strategy_id,
                extracted_strategy_id,
                raw_offset,
            )
            continue
        events.append(event)
    # Prune malformed timestamps older than 60s.
    cutoff = ts_now - 60.0
    while status.malformed_timestamps and status.malformed_timestamps[0] < cutoff:
        status.malformed_timestamps.popleft()
    if not status.quarantined and len(status.malformed_timestamps) >= quarantine_threshold:
        status.quarantined = True
        logger.critical(
            "quarantining strategy due to malformed log rate: strategy_id=%s rate_per_minute=%d",
            status.strategy_id,
            len(status.malformed_timestamps),
        )
    return LogParseResult(events=events, malformed_count=malformed, new_offset=current_offset)


class ReconciliationValidationError(ValueError):
    """Raised when an authoritative cycle violates identity or scope invariants."""


def _require_observation_timestamp(
    value: datetime,
    field_name: str,
    now_utc: datetime,
    max_age_s: float,
    future_skew_tolerance_s: float,
) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ReconciliationValidationError(f"{field_name} must be timezone-aware")
    normalized = value.astimezone(UTC)
    if normalized - now_utc > timedelta(seconds=future_skew_tolerance_s):
        raise ReconciliationValidationError(f"{field_name} cannot be in the future")
    if now_utc - normalized > timedelta(seconds=max_age_s):
        raise ReconciliationValidationError(f"{field_name} is stale")
    return normalized


def _require_decimal_in_domain(
    value: Decimal,
    field_name: str,
    *,
    max_adjusted_exponent: int,
    max_scale: int,
) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ReconciliationValidationError(f"{field_name} must be finite")
    exponent = value.as_tuple().exponent
    if (
        abs(value.adjusted()) > max_adjusted_exponent
        or not isinstance(exponent, int)
        or abs(exponent) > max_scale
    ):
        raise ReconciliationValidationError(
            f"{field_name} is outside the supported Decimal range"
        )


def _require_input_decimal(value: Decimal, field_name: str) -> None:
    """Validate a venue or log input against the normalized input domain."""
    _require_decimal_in_domain(
        value,
        field_name,
        max_adjusted_exponent=DECIMAL_INPUT_MAX_ADJUSTED_EXPONENT,
        max_scale=DECIMAL_INPUT_MAX_SCALE,
    )


def _require_true_boolean(value: object, field_name: str) -> None:
    if type(value) is not bool:
        raise ReconciliationValidationError(f"{field_name} must be a boolean")
    if value is not True:
        raise ReconciliationValidationError(f"{field_name} must be true")


def _accounting_cut_max_skew_s(config: AggregatorConfig) -> float:
    raw = config.accounting_cut_max_skew_s
    value = config.poll_interval_s if raw is None else raw
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or value < 0
        or value > config.health_window_s
    ):
        raise ReconciliationValidationError(
            "accounting_cut_max_skew_s must be finite and within the health window"
        )
    return float(value)


def _parse_aware_timestamp(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} is missing or malformed")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} is malformed") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return parsed.astimezone(UTC)


def _materialize_venue_collections(
    positions_observation: VenuePositionsObservation,
    orders_observation: VenueOrdersObservation,
    batch: VenueLedgerBatch,
) -> tuple[VenuePositionsObservation, VenueOrdersObservation, VenueLedgerBatch]:
    """Consume each adapter collection once and retain immutable snapshots."""
    if not isinstance(positions_observation, VenuePositionsObservation):
        raise ReconciliationValidationError("position observation has an invalid type")
    if not isinstance(orders_observation, VenueOrdersObservation):
        raise ReconciliationValidationError("order observation has an invalid type")
    if not isinstance(batch, VenueLedgerBatch):
        raise ReconciliationValidationError("ledger batch has an invalid type")
    try:
        positions = tuple(positions_observation.positions)
        orders = tuple(orders_observation.orders)
        fills = tuple(batch.fills)
        cash_events = tuple(batch.cash_events)
        return (
            replace(positions_observation, positions=positions),
            replace(orders_observation, orders=orders),
            replace(batch, fills=fills, cash_events=cash_events),
        )
    except Exception as exc:
        raise ReconciliationValidationError(
            "venue collections must be finite iterables"
        ) from exc


def _validate_venue_cycle(
    snapshot: VenueAccountSnapshot,
    positions_observation: VenuePositionsObservation,
    orders_observation: VenueOrdersObservation,
    batch: VenueLedgerBatch,
    strategies: Sequence[StrategyEntry],
    config: AggregatorConfig,
    now_utc: datetime,
) -> datetime:
    if not isinstance(snapshot, VenueAccountSnapshot):
        raise ReconciliationValidationError("account snapshot has an invalid type")
    if not isinstance(positions_observation, VenuePositionsObservation):
        raise ReconciliationValidationError("position observation has an invalid type")
    if not isinstance(orders_observation, VenueOrdersObservation):
        raise ReconciliationValidationError("order observation has an invalid type")
    if not isinstance(batch, VenueLedgerBatch):
        raise ReconciliationValidationError("ledger batch has an invalid type")
    if snapshot.account_scope != config.account_scope:
        raise ReconciliationValidationError(
            "snapshot account_scope does not match configuration"
        )
    if snapshot.quote_currency != config.quote_currency:
        raise ReconciliationValidationError(
            "snapshot quote_currency does not match configuration"
        )
    _require_true_boolean(
        positions_observation.authoritative,
        "positions_observation.authoritative",
    )
    _require_true_boolean(positions_observation.complete, "positions_observation.complete")
    _require_true_boolean(
        orders_observation.authoritative,
        "orders_observation.authoritative",
    )
    _require_true_boolean(orders_observation.complete, "orders_observation.complete")
    _require_true_boolean(batch.authoritative, "ledger_batch.authoritative")
    _require_true_boolean(batch.complete, "ledger_batch.complete")
    _require_observation_timestamp(
        snapshot.timestamp,
        "snapshot.timestamp",
        now_utc,
        config.health_window_s,
        config.future_skew_tolerance_s,
    )
    positions_as_of = _require_observation_timestamp(
        positions_observation.as_of,
        "positions_observation.as_of",
        now_utc,
        config.health_window_s,
        config.future_skew_tolerance_s,
    )
    _require_observation_timestamp(
        orders_observation.as_of,
        "orders_observation.as_of",
        now_utc,
        config.health_window_s,
        config.future_skew_tolerance_s,
    )
    batch_as_of = _require_observation_timestamp(
        batch.as_of,
        "ledger_batch.as_of",
        now_utc,
        config.health_window_s,
        config.future_skew_tolerance_s,
    )
    position_accounting_cut = positions_as_of
    if positions_observation.as_of_cut is not None:
        position_accounting_cut = _require_observation_timestamp(
            positions_observation.as_of_cut,
            "positions_observation.as_of_cut",
            now_utc,
            config.health_window_s,
            config.future_skew_tolerance_s,
        )
        if position_accounting_cut > positions_as_of:
            raise ReconciliationValidationError(
                "positions_observation.as_of_cut cannot be after its observation"
            )
        if position_accounting_cut != batch_as_of:
            raise ReconciliationValidationError(
                "positions_observation.as_of_cut must equal ledger_batch.as_of"
            )
    elif positions_as_of > batch_as_of:
        raise ReconciliationValidationError(
            "position observation is newer than the ledger completeness watermark"
        )
    if abs(batch_as_of - position_accounting_cut) > timedelta(
        seconds=_accounting_cut_max_skew_s(config)
    ):
        raise ReconciliationValidationError(
            "position and ledger observations exceed the accounting-cut skew"
        )
    for value, name in (
        (snapshot.balance, "snapshot.balance"),
        (snapshot.equity, "snapshot.equity"),
        (snapshot.margin_used, "snapshot.margin_used"),
        (snapshot.margin_ratio, "snapshot.margin_ratio"),
    ):
        _require_input_decimal(value, name)
    if snapshot.balance <= 0 or snapshot.equity <= 0:
        raise ReconciliationValidationError(
            "snapshot balance and equity must be positive"
        )
    if snapshot.margin_used < 0:
        raise ReconciliationValidationError("snapshot.margin_used must be non-negative")
    if snapshot.margin_ratio < 0:
        raise ReconciliationValidationError("snapshot.margin_ratio must be non-negative")

    strategy_ids = {strategy.id for strategy in strategies}
    for strategy in strategies:
        if strategy.account_scope != config.account_scope:
            raise ReconciliationValidationError(
                f"strategy {strategy.id} account_scope does not match configuration"
            )

    position_keys: set[tuple[str, str, str]] = set()
    for position in positions_observation.positions:
        if not isinstance(position, VenuePosition):
            raise ReconciliationValidationError("venue position has an invalid type")
        if position.strategy_id is None or position.strategy_id not in strategy_ids:
            raise ReconciliationValidationError(
                "venue position has missing or foreign strategy_id"
            )
        if position.account_scope != config.account_scope:
            raise ReconciliationValidationError(
                "venue position account_scope does not match configuration"
            )
        if position.quote_currency != config.quote_currency:
            raise ReconciliationValidationError(
                "venue position quote_currency does not match configuration"
            )
        if not position.symbol or position.symbol.strip() != position.symbol:
            raise ReconciliationValidationError("venue position symbol is invalid")
        if position.side not in {"long", "short"}:
            raise ReconciliationValidationError(
                "venue position side must be long or short"
            )
        for decimal_value, name in (
            (position.size, "position.size"),
            (position.entry_price, "position.entry_price"),
            (position.unrealized_pnl, "position.unrealized_pnl"),
        ):
            _require_input_decimal(decimal_value, name)
        if position.size <= 0 or position.entry_price < 0:
            raise ReconciliationValidationError("venue position size/price is invalid")
        key = (position.strategy_id, position.symbol, position.side)
        if key in position_keys:
            raise ReconciliationValidationError(
                f"duplicate venue position key: {key!r}"
            )
        position_keys.add(key)

    order_keys: set[tuple[str, str, str]] = set()
    for order in orders_observation.orders:
        if not isinstance(order, VenueOrder):
            raise ReconciliationValidationError("venue order has an invalid type")
        if order.strategy_id is None or order.strategy_id not in strategy_ids:
            raise ReconciliationValidationError(
                "venue order has missing or foreign strategy_id"
            )
        if order.account_scope != config.account_scope:
            raise ReconciliationValidationError(
                "venue order account_scope does not match configuration"
            )
        if order.quote_currency != config.quote_currency:
            raise ReconciliationValidationError(
                "venue order quote_currency does not match configuration"
            )
        for text_value, name in (
            (order.symbol, "order.symbol"),
            (order.order_id, "order.order_id"),
            (order.side, "order.side"),
            (order.status, "order.status"),
        ):
            if not text_value or text_value.strip() != text_value:
                raise ReconciliationValidationError(f"{name} is invalid")
        _require_input_decimal(order.size, "order.size")
        _require_input_decimal(order.price, "order.price")
        if order.size <= 0 or order.price < 0:
            raise ReconciliationValidationError("venue order size/price is invalid")
        key = (order.strategy_id, order.symbol, order.order_id)
        if key in order_keys:
            raise ReconciliationValidationError(
                f"duplicate venue order key: {key!r}"
            )
        order_keys.add(key)
    return min(position_accounting_cut, batch_as_of)
