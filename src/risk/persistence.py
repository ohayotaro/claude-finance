"""Checkpoint persistence, ledger binding, and writer locking."""

from __future__ import annotations

import contextlib
import copy
import errno
import json
import logging
import os
import sys
import tempfile
from dataclasses import fields as dataclass_fields
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from src.risk.accounting import (
    AggregatorState,
    _invalidate_cached_enforcement_provenance,
    _require_derived_decimal,
    _validate_persisted_state_decimals,
    determine_signals,
)
from src.risk.ledger import FillLedger, decimal_arithmetic_context
from src.risk.observations import (
    LOG_FINGERPRINT_BYTES,
    StrategyLogStatus,
    VenueAccountSnapshot,
    _parse_aware_timestamp,
    _require_input_decimal,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path
    from typing import Any

    from src.risk.config import AggregatorConfig

if sys.platform == "win32":
    import msvcrt as _msvcrt_backend
    _fcntl_backend: Any | None = None
else:
    import fcntl as _fcntl_backend
    _msvcrt_backend: Any | None = None

logger = logging.getLogger("aggregator")
CHECKPOINT_SCHEMA_VERSION = 3
_SCHEMA_V3_CHECKPOINT_FIELDS = frozenset("schema_version risk_group account_scope quote_currency ledger_cursor ledger_generation drawdown_baseline_verified last_success_ts last_snapshot group_net_exposure group_gross_exposure group_daily_pnl open_position_count open_order_count daily_realized_pnl pending_daily_realized_pnl daily_unrealized_pnl drawdown_sod_pct drawdown_hwm_pct venue_as_of_ts positions_as_of_ts orders_as_of_ts ledger_as_of_ts log_as_of_ts current_utc_date log_unrealized_telemetry start_of_day_equity high_water_mark consecutive_failures fail_closed soft_cap hard_cap margin_emergency residual_strategy_ids log_statuses".split())  # noqa: E501, SIM905

def save_checkpoint(
    path: Path,
    state: AggregatorState,
    log_statuses: dict[str, StrategyLogStatus],
    *,
    ledger: FillLedger,
) -> bool:
    """Atomically persist aggregator state for crash recovery."""
    if not state.checkpoint_save_allowed:
        logger.critical(
            "checkpoint save skipped because cached state is not bound to the "
            "latest committed ledger generation"
        )
        _invalidate_cached_enforcement_provenance(state)
        return False
    try:
        current_binding = ledger.binding
    except Exception:
        _invalidate_cached_enforcement_provenance(state)
        raise
    recorded_cursor = state.checkpoint_ledger_cursor
    recorded_generation = state.checkpoint_ledger_generation
    if (
        recorded_generation is None
        and recorded_cursor is None
        and state.last_success_ts is None
        and current_binding.generation == 0
        and current_binding.cursor is None
    ):
        recorded_generation = 0
    if (
        recorded_generation is None
        or recorded_cursor != current_binding.cursor
        or recorded_generation != current_binding.generation
    ):
        logger.critical(
            "checkpoint save skipped because ledger binding changed: "
            "recorded_cursor=%r recorded_generation=%r "
            "current_cursor=%r current_generation=%r",
            recorded_cursor,
            recorded_generation,
            current_binding.cursor,
            current_binding.generation,
        )
        _invalidate_cached_enforcement_provenance(state)
        return False
    snapshot = _validate_persisted_state_decimals(state)
    payload: dict[str, Any] = {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "risk_group": state.risk_group,
        "account_scope": ledger.account_scope,
        "quote_currency": ledger.quote_currency,
        "ledger_cursor": recorded_cursor,
        "ledger_generation": recorded_generation,
        "drawdown_baseline_verified": state.drawdown_baseline_verified,
        "last_success_ts": (
            state.last_success_ts.isoformat()
            if state.last_success_ts is not None else None
        ),
        "last_snapshot": (
            {
                "account_scope": snapshot.account_scope,
                "balance": str(snapshot.balance),
                "equity": str(snapshot.equity),
                "margin_used": str(snapshot.margin_used),
                "margin_ratio": str(snapshot.margin_ratio),
                "timestamp": snapshot.timestamp.isoformat(),
                "quote_currency": snapshot.quote_currency,
            }
            if snapshot is not None else None
        ),
        "group_net_exposure": str(state.group_net_exposure),
        "group_gross_exposure": str(state.group_gross_exposure),
        "group_daily_pnl": str(state.group_daily_pnl),
        "open_position_count": state.open_position_count,
        "open_order_count": state.open_order_count,
        "daily_realized_pnl": str(state.daily_realized_pnl),
        "pending_daily_realized_pnl": str(state.pending_daily_realized_pnl),
        "daily_unrealized_pnl": str(state.daily_unrealized_pnl),
        "drawdown_sod_pct": str(state.drawdown_sod_pct),
        "drawdown_hwm_pct": str(state.drawdown_hwm_pct),
        "venue_as_of_ts": (
            state.venue_as_of_ts.isoformat()
            if state.venue_as_of_ts is not None else None
        ),
        "positions_as_of_ts": (
            state.positions_as_of_ts.isoformat()
            if state.positions_as_of_ts is not None else None
        ),
        "orders_as_of_ts": (
            state.orders_as_of_ts.isoformat()
            if state.orders_as_of_ts is not None else None
        ),
        "ledger_as_of_ts": (
            state.ledger_as_of_ts.isoformat()
            if state.ledger_as_of_ts is not None else None
        ),
        "log_as_of_ts": (
            state.log_as_of_ts.isoformat()
            if state.log_as_of_ts is not None else None
        ),
        "current_utc_date": (
            state.current_utc_date.isoformat()
            if state.current_utc_date is not None else None
        ),
        "log_unrealized_telemetry": {
            f"{sid}\x00{sym}": str(val)
            for (sid, sym), val in state.latest_unrealized.items()
        },
        "start_of_day_equity": (
            str(state.start_of_day_equity)
            if state.start_of_day_equity is not None else None
        ),
        "high_water_mark": (
            str(state.high_water_mark)
            if state.high_water_mark is not None else None
        ),
        "consecutive_failures": state.consecutive_failures,
        "fail_closed": state.fail_closed,
        "soft_cap": state.soft_cap,
        "hard_cap": state.hard_cap,
        "margin_emergency": state.margin_emergency,
        "residual_strategy_ids": sorted(state.residual_strategy_ids),
        "log_statuses": {
            sid: {
                "log_offset": status.log_offset,
                "file_device": status.file_device,
                "file_inode": status.file_inode,
                "prefix_length": status.prefix_length,
                "prefix_fingerprint": status.prefix_fingerprint,
                "boundary_start": status.boundary_start,
                "boundary_fingerprint": status.boundary_fingerprint,
                "quarantined": status.quarantined,
            }
            for sid, status in log_statuses.items()
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, sort_keys=True).encode("utf-8")
    with tempfile.NamedTemporaryFile(
        mode="wb",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as tmp:
        tmp_name = tmp.name
        try:
            tmp.write(data)
            tmp.flush()
            os.fsync(tmp.fileno())
        except Exception:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(tmp_name)
            raise
    try:
        os.replace(tmp_name, path)
    except Exception:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_name)
        raise
    return True


def _checkpoint_decimal(raw: Any, field_name: str) -> Decimal:
    try:
        value = Decimal(str(raw))
    except (ArithmeticError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a decimal") from exc
    _require_derived_decimal(value, field_name)
    return value


def _checkpoint_input_decimal(raw: Any, field_name: str) -> Decimal:
    try:
        value = Decimal(str(raw))
    except (ArithmeticError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a decimal") from exc
    _require_input_decimal(value, field_name)
    return value


def _checkpoint_timestamp(raw: Any, field_name: str) -> datetime | None:
    if raw is None:
        return None
    return _parse_aware_timestamp(raw, field_name)


def _checkpoint_snapshot(raw: Any) -> VenueAccountSnapshot | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise TypeError("last_snapshot must be an object")
    account_scope = raw["account_scope"]
    quote_currency = raw["quote_currency"]
    if not isinstance(account_scope, str) or not account_scope:
        raise ValueError("last_snapshot.account_scope is invalid")
    if not isinstance(quote_currency, str) or not quote_currency:
        raise ValueError("last_snapshot.quote_currency is invalid")
    snapshot = VenueAccountSnapshot(
        account_scope=account_scope,
        balance=_checkpoint_input_decimal(raw["balance"], "last_snapshot.balance"),
        equity=_checkpoint_input_decimal(raw["equity"], "last_snapshot.equity"),
        margin_used=_checkpoint_input_decimal(
            raw["margin_used"], "last_snapshot.margin_used"
        ),
        margin_ratio=_checkpoint_input_decimal(
            raw["margin_ratio"], "last_snapshot.margin_ratio"
        ),
        timestamp=_parse_aware_timestamp(
            raw["timestamp"], "last_snapshot.timestamp"
        ),
        quote_currency=quote_currency,
    )
    if snapshot.balance <= 0 or snapshot.equity <= 0:
        raise ValueError("last_snapshot balance and equity must be positive")
    if snapshot.margin_used < 0 or snapshot.margin_ratio < 0:
        raise ValueError("last_snapshot margin values must be non-negative")
    for value, field_name in (
        (snapshot.balance, "last_snapshot.balance"),
        (snapshot.equity, "last_snapshot.equity"),
        (snapshot.margin_used, "last_snapshot.margin_used"),
        (snapshot.margin_ratio, "last_snapshot.margin_ratio"),
    ):
        _require_input_decimal(value, field_name)
    return snapshot


def _validate_schema_v3_checkpoint_shape(raw: dict[str, Any]) -> None:
    """Require the current checkpoint schema without coercion or defaults."""
    missing = sorted(_SCHEMA_V3_CHECKPOINT_FIELDS.difference(raw))
    if missing:
        raise ValueError(f"schema-v3 checkpoint is missing fields: {missing!r}")
    if type(raw["schema_version"]) is not int:
        raise TypeError("schema_version must be an integer")
    for field_name in ("risk_group", "account_scope", "quote_currency"):
        value = raw[field_name]
        if not isinstance(value, str) or not value or value.strip() != value:
            raise ValueError(f"{field_name} must be a non-empty string")
    for field_name in (
        "group_net_exposure",
        "group_gross_exposure",
        "group_daily_pnl",
        "daily_realized_pnl",
        "pending_daily_realized_pnl",
        "daily_unrealized_pnl",
        "drawdown_sod_pct",
        "drawdown_hwm_pct",
    ):
        if not isinstance(raw[field_name], str):
            raise TypeError(f"{field_name} must be a decimal string")
    for field_name in ("start_of_day_equity", "high_water_mark"):
        value = raw[field_name]
        if value is not None and not isinstance(value, str):
            raise TypeError(f"{field_name} must be a decimal string or null")
    for field_name in (
        "last_success_ts",
        "venue_as_of_ts",
        "positions_as_of_ts",
        "orders_as_of_ts",
        "ledger_as_of_ts",
        "log_as_of_ts",
        "current_utc_date",
    ):
        value = raw[field_name]
        if value is not None and not isinstance(value, str):
            raise TypeError(f"{field_name} must be a string or null")
    for field_name in (
        "drawdown_baseline_verified",
        "fail_closed",
        "soft_cap",
        "hard_cap",
        "margin_emergency",
    ):
        if type(raw[field_name]) is not bool:
            raise TypeError(f"{field_name} must be a boolean")
    for field_name in (
        "ledger_generation",
        "open_position_count",
        "open_order_count",
        "consecutive_failures",
    ):
        value = raw[field_name]
        if type(value) is not int or value < 0:
            raise ValueError(f"{field_name} must be a non-negative integer")
    ledger_cursor = raw["ledger_cursor"]
    if ledger_cursor is not None and (
        not isinstance(ledger_cursor, str)
        or not ledger_cursor
        or ledger_cursor.strip() != ledger_cursor
    ):
        raise TypeError("ledger_cursor must be a non-empty string or null")
    if (raw["ledger_generation"] == 0) != (ledger_cursor is None):
        raise ValueError("ledger cursor and generation are inconsistent")

    snapshot = raw["last_snapshot"]
    if snapshot is not None:
        if not isinstance(snapshot, dict):
            raise TypeError("last_snapshot must be an object or null")
        snapshot_fields = {
            "account_scope",
            "balance",
            "equity",
            "margin_used",
            "margin_ratio",
            "timestamp",
            "quote_currency",
        }
        if snapshot_fields.difference(snapshot):
            raise ValueError("last_snapshot is missing required fields")
        for field_name in ("account_scope", "timestamp", "quote_currency"):
            if not isinstance(snapshot[field_name], str) or not snapshot[field_name]:
                raise TypeError(f"last_snapshot.{field_name} must be a string")
        for field_name in ("balance", "equity", "margin_used", "margin_ratio"):
            if not isinstance(snapshot[field_name], str):
                raise TypeError(
                    f"last_snapshot.{field_name} must be a decimal string"
                )

    residual_ids = raw["residual_strategy_ids"]
    if (
        not isinstance(residual_ids, list)
        or not all(isinstance(value, str) and value for value in residual_ids)
        or len(set(residual_ids)) != len(residual_ids)
    ):
        raise TypeError("residual_strategy_ids must be unique non-empty strings")
    telemetry = raw["log_unrealized_telemetry"]
    if not isinstance(telemetry, dict) or not all(
        isinstance(key, str)
        and len(key.split("\x00", 1)) == 2
        and all(key.split("\x00", 1))
        and isinstance(value, str)
        for key, value in telemetry.items()
    ):
        raise TypeError("log_unrealized_telemetry must map strings to decimal strings")
    raw_statuses = raw["log_statuses"]
    if not isinstance(raw_statuses, dict):
        raise TypeError("log_statuses must be an object")
    required_status_fields = {
        "log_offset",
        "file_device",
        "file_inode",
        "prefix_length",
        "prefix_fingerprint",
        "boundary_start",
        "boundary_fingerprint",
        "quarantined",
    }
    for strategy_id, status in raw_statuses.items():
        if not isinstance(strategy_id, str) or not strategy_id:
            raise TypeError("log status strategy_id must be a non-empty string")
        if not isinstance(status, dict) or required_status_fields.difference(status):
            raise TypeError("log status must contain every schema-v3 field")
        for field_name in ("log_offset", "prefix_length", "boundary_start"):
            if type(status[field_name]) is not int:
                raise TypeError(f"log status {field_name} must be an integer")
        for field_name in ("file_device", "file_inode"):
            value = status[field_name]
            if value is not None and type(value) is not int:
                raise TypeError(f"log status {field_name} must be an integer or null")
        for field_name in ("prefix_fingerprint", "boundary_fingerprint"):
            value = status[field_name]
            if value is not None and not isinstance(value, str):
                raise TypeError(f"log status {field_name} must be a string or null")
        if type(status["quarantined"]) is not bool:
            raise TypeError("log status quarantined must be a boolean")


@decimal_arithmetic_context()
def load_checkpoint(
    path: Path,
    state: AggregatorState,
    log_statuses: dict[str, StrategyLogStatus],
    *,
    ledger: FillLedger,
    config: AggregatorConfig,
) -> bool:
    """Restore v1-v3 state with isolated exact checkpoint validation."""
    if not path.exists():
        return False
    try:
        raw = json.loads(path.read_text("utf-8"))
    except (ValueError, OSError) as exc:
        logger.warning("corrupt or unreadable checkpoint, starting fresh: %s", exc)
        return False
    if not isinstance(raw, dict):
        logger.warning("checkpoint root must be an object")
        return False
    version_value = raw.get("schema_version")
    if version_value is None:
        version = 1
    elif type(version_value) is not int:
        logger.warning("checkpoint schema_version must be an integer")
        return False
    else:
        version = version_value
    if version not in {1, 2, CHECKPOINT_SCHEMA_VERSION}:
        logger.warning("unsupported checkpoint schema version: %r", version)
        return False
    target_state = state
    target_log_statuses = log_statuses
    state = AggregatorState(risk_group=target_state.risk_group)
    log_statuses = {}
    try:
        if version == CHECKPOINT_SCHEMA_VERSION:
            _validate_schema_v3_checkpoint_shape(raw)
        saved_date_str = raw.get("current_utc_date")
        if saved_date_str is not None:
            state.current_utc_date = date.fromisoformat(saved_date_str)
        if version == CHECKPOINT_SCHEMA_VERSION:
            if raw.get("risk_group") != state.risk_group:
                raise ValueError("checkpoint risk_group does not match runtime")
            if raw.get("account_scope") != ledger.account_scope:
                raise ValueError("checkpoint account_scope does not match ledger")
            if raw.get("quote_currency") != ledger.quote_currency:
                raise ValueError("checkpoint quote_currency does not match ledger")
            state.last_success_ts = _checkpoint_timestamp(
                raw["last_success_ts"], "last_success_ts"
            )
            state.last_snapshot = _checkpoint_snapshot(raw["last_snapshot"])
            state.group_net_exposure = _checkpoint_decimal(
                raw["group_net_exposure"], "group_net_exposure"
            )
            state.group_gross_exposure = _checkpoint_decimal(
                raw["group_gross_exposure"], "group_gross_exposure"
            )
            state.group_daily_pnl = _checkpoint_decimal(
                raw["group_daily_pnl"], "group_daily_pnl"
            )
            state.daily_realized_pnl = _checkpoint_decimal(
                raw["daily_realized_pnl"], "daily_realized_pnl"
            )
            state.pending_daily_realized_pnl = _checkpoint_decimal(
                raw["pending_daily_realized_pnl"],
                "pending_daily_realized_pnl",
            )
            state.daily_unrealized_pnl = _checkpoint_decimal(
                raw["daily_unrealized_pnl"], "daily_unrealized_pnl"
            )
            state.drawdown_sod_pct = _checkpoint_decimal(
                raw["drawdown_sod_pct"], "drawdown_sod_pct"
            )
            state.drawdown_hwm_pct = _checkpoint_decimal(
                raw["drawdown_hwm_pct"], "drawdown_hwm_pct"
            )
            for count_name in ("open_position_count", "open_order_count"):
                count = raw[count_name]
                if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                    raise ValueError(f"{count_name} must be a non-negative integer")
                setattr(state, count_name, count)
            state.venue_as_of_ts = _checkpoint_timestamp(
                raw["venue_as_of_ts"], "venue_as_of_ts"
            )
            state.positions_as_of_ts = _checkpoint_timestamp(
                raw["positions_as_of_ts"], "positions_as_of_ts"
            )
            state.orders_as_of_ts = _checkpoint_timestamp(
                raw["orders_as_of_ts"], "orders_as_of_ts"
            )
            state.ledger_as_of_ts = _checkpoint_timestamp(
                raw["ledger_as_of_ts"], "ledger_as_of_ts"
            )
            state.log_as_of_ts = _checkpoint_timestamp(
                raw["log_as_of_ts"], "log_as_of_ts"
            )
        else:
            state.last_success_ts = None
            state.last_snapshot = None
            state.group_net_exposure = Decimal("0")
            state.group_gross_exposure = Decimal("0")
            state.group_daily_pnl = Decimal("0")
            state.daily_realized_pnl = Decimal("0")
            state.pending_daily_realized_pnl = Decimal("0")
            state.daily_unrealized_pnl = Decimal("0")
            state.open_position_count = 0
            state.open_order_count = 0
            state.drawdown_sod_pct = Decimal("0")
            state.drawdown_hwm_pct = Decimal("0")
            state.venue_as_of_ts = None
            state.positions_as_of_ts = None
            state.orders_as_of_ts = None
            state.ledger_as_of_ts = None
            state.log_as_of_ts = None
        state.latest_unrealized = {}
        sod = (
            raw["start_of_day_equity"]
            if version == CHECKPOINT_SCHEMA_VERSION
            else raw.get("start_of_day_equity")
        )
        state.start_of_day_equity = (
            _checkpoint_decimal(sod, "start_of_day_equity")
            if sod is not None
            else None
        )
        hwm = (
            raw["high_water_mark"]
            if version == CHECKPOINT_SCHEMA_VERSION
            else raw.get("high_water_mark")
        )
        state.high_water_mark = (
            _checkpoint_decimal(hwm, "high_water_mark")
            if hwm is not None
            else None
        )
        for baseline_name, baseline in (
            ("start_of_day_equity", state.start_of_day_equity),
            ("high_water_mark", state.high_water_mark),
        ):
            if baseline is not None:
                _require_derived_decimal(baseline, baseline_name)
                if baseline <= 0:
                    raise ValueError(f"{baseline_name} must be finite and positive")
        if version == CHECKPOINT_SCHEMA_VERSION:
            state.consecutive_failures = raw["consecutive_failures"]
            state.fail_closed = raw["fail_closed"]
            state.soft_cap = raw["soft_cap"]
            state.hard_cap = raw["hard_cap"]
            state.margin_emergency = raw["margin_emergency"]
        else:
            state.consecutive_failures = int(raw.get("consecutive_failures", 0))
            state.fail_closed = bool(raw.get("fail_closed", False))
            state.soft_cap = bool(raw.get("soft_cap", False))
            state.hard_cap = bool(raw.get("hard_cap", False))
            state.margin_emergency = bool(raw.get("margin_emergency", False))
        if state.consecutive_failures < 0:
            raise ValueError("consecutive_failures must be non-negative")
        if version == CHECKPOINT_SCHEMA_VERSION:
            if state.hard_cap and not state.soft_cap:
                raise ValueError("hard_cap requires soft_cap")
            if raw["drawdown_baseline_verified"] is True and (
                state.start_of_day_equity is None or state.high_water_mark is None
            ):
                raise ValueError(
                    "verified drawdown baselines require start-of-day equity and HWM"
                )
            if state.group_gross_exposure < 0:
                raise ValueError("group_gross_exposure must be non-negative")
            if state.group_net_exposure.copy_abs() > state.group_gross_exposure:
                raise ValueError("net exposure cannot exceed gross exposure")
            with decimal_arithmetic_context():
                expected_group_daily_pnl = (
                    state.daily_realized_pnl + state.daily_unrealized_pnl
                )
            _require_derived_decimal(
                expected_group_daily_pnl,
                "expected_group_daily_pnl",
            )
            if state.group_daily_pnl != expected_group_daily_pnl:
                raise ValueError("group_daily_pnl components are inconsistent")
            if state.last_snapshot is not None and (
                state.last_snapshot.account_scope != ledger.account_scope
                or state.last_snapshot.quote_currency != ledger.quote_currency
            ):
                raise ValueError("last_snapshot does not match the ledger scope")
        residual_ids = (
            raw["residual_strategy_ids"]
            if version == CHECKPOINT_SCHEMA_VERSION
            else raw.get("residual_strategy_ids", [])
        )
        if not isinstance(residual_ids, list) or not all(
            isinstance(strategy_id, str) and strategy_id
            for strategy_id in residual_ids
        ):
            raise TypeError("residual_strategy_ids must be a list of strings")
        state.residual_strategy_ids = set(residual_ids)
        if version == 1:
            raw_offsets = raw.get("log_offsets", {})
            if not isinstance(raw_offsets, dict):
                raise TypeError("log_offsets must be an object")
            for strategy_id in raw_offsets:
                sid = str(strategy_id)
                log_statuses[sid] = StrategyLogStatus(strategy_id=sid, log_offset=0)
        else:
            raw_telemetry = (
                raw["log_unrealized_telemetry"]
                if version == CHECKPOINT_SCHEMA_VERSION
                else raw.get("log_unrealized_telemetry", {})
            )
            if not isinstance(raw_telemetry, dict):
                raise TypeError("log_unrealized_telemetry must be an object")
            for key_str, val_str in raw_telemetry.items():
                parts = key_str.split("\x00", 1)
                if len(parts) == 2:
                    telemetry = _checkpoint_input_decimal(
                        val_str,
                        "log unrealized telemetry",
                    )
                    state.latest_unrealized[(parts[0], parts[1])] = telemetry
            raw_statuses = (
                raw["log_statuses"]
                if version == CHECKPOINT_SCHEMA_VERSION
                else raw.get("log_statuses", {})
            )
            if not isinstance(raw_statuses, dict):
                raise TypeError("log_statuses must be an object")
            for sid_value, status_value in raw_statuses.items():
                if not isinstance(status_value, dict):
                    raise TypeError("log status must be an object")
                sid = sid_value
                if version == CHECKPOINT_SCHEMA_VERSION:
                    log_offset = status_value["log_offset"]
                    prefix_length = status_value["prefix_length"]
                    boundary_start = status_value["boundary_start"]
                    quarantined = status_value["quarantined"]
                else:
                    log_offset = int(status_value.get("log_offset", 0))
                    prefix_length = int(status_value.get("prefix_length", 0))
                    boundary_start = int(status_value.get("boundary_start", 0))
                    quarantined = bool(status_value.get("quarantined", False))
                file_device = status_value.get("file_device")
                file_inode = status_value.get("file_inode")
                prefix_fingerprint = status_value.get("prefix_fingerprint")
                boundary_fingerprint = status_value.get("boundary_fingerprint")
                if version != CHECKPOINT_SCHEMA_VERSION:
                    file_device = (
                        int(file_device) if file_device is not None else None
                    )
                    file_inode = int(file_inode) if file_inode is not None else None
                    prefix_fingerprint = (
                        str(prefix_fingerprint)
                        if prefix_fingerprint is not None
                        else None
                    )
                    boundary_fingerprint = (
                        str(boundary_fingerprint)
                        if boundary_fingerprint is not None
                        else None
                    )
                if (
                    log_offset < 0
                    or not 0 <= prefix_length <= LOG_FINGERPRINT_BYTES
                    or not 0 <= boundary_start <= log_offset
                ):
                    raise ValueError("log status offsets or fingerprint length are invalid")
                log_statuses[sid] = StrategyLogStatus(
                    strategy_id=sid,
                    log_offset=log_offset,
                    quarantined=quarantined,
                    file_device=file_device,
                    file_inode=file_inode,
                    prefix_length=prefix_length,
                    prefix_fingerprint=prefix_fingerprint,
                    boundary_start=boundary_start,
                    boundary_fingerprint=boundary_fingerprint,
                )
        if version == CHECKPOINT_SCHEMA_VERSION:
            ledger_generation = raw["ledger_generation"]
            ledger_cursor = raw["ledger_cursor"]
            if (
                isinstance(ledger_generation, bool)
                or not isinstance(ledger_generation, int)
                or ledger_generation < 0
            ):
                raise ValueError("ledger_generation must be a non-negative integer")
            if ledger_cursor is not None and not isinstance(ledger_cursor, str):
                raise TypeError("ledger_cursor must be a string or null")
            state.checkpoint_ledger_cursor = ledger_cursor
            state.checkpoint_ledger_generation = ledger_generation
            ledger_binding = ledger.binding
            binding_matches = (
                ledger_binding.cursor == ledger_cursor
                and ledger_binding.generation == ledger_generation
            )
            persisted_cap_flags = (state.soft_cap, state.hard_cap, state.margin_emergency)
            signal_check = copy.copy(state)
            determine_signals(signal_check, config)
            expected_cap_flags = (
                signal_check.soft_cap, signal_check.hard_cap, signal_check.margin_emergency
            )
            if persisted_cap_flags != expected_cap_flags:
                raise ValueError(
                    "checkpoint cap flags are inconsistent with cached PnL, "
                    "snapshot, and current configuration"
                )
            # Ledger binding validation proves generation zero has no records.
            if state.current_utc_date is None and (
                not binding_matches
                or ledger_binding.generation != 0
                or ledger_binding.cursor is not None
                or any((
                    state.daily_realized_pnl, state.pending_daily_realized_pnl,
                    state.daily_unrealized_pnl, state.group_daily_pnl,
                ))
                or any(persisted_cap_flags)
            ):
                raise ValueError("checkpoint without a persisted day must be bootstrap state")
            if binding_matches:
                if state.ledger_as_of_ts != ledger_binding.as_of:
                    raise ValueError(
                        "checkpoint ledger timestamp does not match ledger metadata"
                    )
                if state.current_utc_date is not None:
                    if (
                        state.positions_as_of_ts is None
                        or state.ledger_as_of_ts is None
                    ):
                        raise ValueError(
                            "checkpoint persisted day requires position and ledger cuts"
                        )
                    enforcement_cut = min(state.positions_as_of_ts, state.ledger_as_of_ts)
                    realized = ledger.realized_pnl_for_day(
                        state.current_utc_date,
                        through=enforcement_cut,
                    )
                    full_day = ledger.realized_pnl_for_day(state.current_utc_date)
                    with decimal_arithmetic_context():
                        pending = full_day - realized
                    _require_derived_decimal(realized, "recomputed_daily_realized_pnl")
                    _require_derived_decimal(pending, "recomputed_pending_daily_realized_pnl")
                    if realized != state.daily_realized_pnl:
                        raise ValueError(
                            "checkpoint realized PnL does not match bound ledger"
                        )
                    if pending != state.pending_daily_realized_pnl:
                        raise ValueError(
                            "checkpoint pending PnL does not match bound ledger"
                        )
                if ledger.binding != ledger_binding:
                    raise ValueError(
                        "ledger metadata changed during checkpoint verification"
                    )
            state.drawdown_baseline_verified = (
                raw["drawdown_baseline_verified"] is True and binding_matches
            )
            state.checkpoint_save_allowed = binding_matches
            if not binding_matches:
                state.fail_closed = True
                logger.critical(
                    "checkpoint ledger binding mismatch; drawdown baseline is unverified"
                )
        else:
            state.checkpoint_ledger_cursor = None
            state.checkpoint_ledger_generation = None
            state.drawdown_baseline_verified = False
            state.fail_closed = True
            state.checkpoint_save_allowed = False
    except Exception as exc:
        logger.warning("checkpoint parse error, starting fresh: %s", exc)
        return False
    for state_field in dataclass_fields(AggregatorState):
        value = copy.deepcopy(getattr(state, state_field.name))
        setattr(target_state, state_field.name, value)
    target_log_statuses.clear()
    target_log_statuses.update(log_statuses)
    logger.info(
        "checkpoint loaded: schema=%s date=%s hwm=%s log_statuses=%d",
        version,
        state.current_utc_date,
        state.high_water_mark,
        len(log_statuses),
    )
    return True


class AggregatorWriterLockError(RuntimeError):
    pass


def _acquire_writer_lock(lock_file: Any, lock_path: Path) -> None:
    try:
        if sys.platform == "win32":
            if _msvcrt_backend is None:
                raise AggregatorWriterLockError(
                    "Windows aggregator writer lock backend is unavailable"
                )
            lock_file.seek(0, os.SEEK_END)
            if lock_file.tell() == 0:
                lock_file.write(b"\x00")
                lock_file.flush()
            lock_file.seek(0)
            _msvcrt_backend.locking(
                lock_file.fileno(),
                _msvcrt_backend.LK_NBLCK,
                1,
            )
        else:
            if _fcntl_backend is None:
                raise AggregatorWriterLockError(
                    "POSIX aggregator writer lock backend is unavailable"
                )
            _fcntl_backend.flock(
                lock_file.fileno(),
                _fcntl_backend.LOCK_EX | _fcntl_backend.LOCK_NB,
            )
    except AggregatorWriterLockError:
        raise
    except OSError as exc:
        contention_errnos = {
            errno.EACCES,
            errno.EAGAIN,
            getattr(errno, "EDEADLK", -1),
        }
        if exc.errno in contention_errnos:
            raise AggregatorWriterLockError(
                "another aggregator instance already holds the risk-group lock"
            ) from exc
        raise AggregatorWriterLockError(
            f"cannot acquire aggregator writer lock {lock_path}: {exc}"
        ) from exc


def _release_writer_lock(lock_file: Any, lock_path: Path) -> None:
    try:
        if sys.platform == "win32":
            if _msvcrt_backend is None:
                raise AggregatorWriterLockError(
                    "Windows aggregator writer lock backend is unavailable"
                )
            lock_file.seek(0)
            _msvcrt_backend.locking(
                lock_file.fileno(),
                _msvcrt_backend.LK_UNLCK,
                1,
            )
        else:
            if _fcntl_backend is None:
                raise AggregatorWriterLockError(
                    "POSIX aggregator writer lock backend is unavailable"
                )
            _fcntl_backend.flock(lock_file.fileno(), _fcntl_backend.LOCK_UN)
    except AggregatorWriterLockError:
        raise
    except OSError as exc:
        raise AggregatorWriterLockError(
            f"cannot release aggregator writer lock {lock_path}: {exc}"
        ) from exc


@contextlib.contextmanager
def _exclusive_ledger_directory_lock(ledger_path: Path) -> Iterator[None]:
    ledger_directory = ledger_path.parent
    lock_path = ledger_directory / ".writer.lock"
    try:
        ledger_directory.mkdir(parents=True, exist_ok=True)
        lock_file = lock_path.open("a+b")
    except OSError as exc:
        raise AggregatorWriterLockError(
            f"cannot open aggregator writer lock {lock_path}: {exc}"
        ) from exc

    with lock_file:
        _acquire_writer_lock(lock_file, lock_path)
        try:
            yield
        finally:
            _release_writer_lock(lock_file, lock_path)
