"""Risk-state serialization, publication, and consumer validation."""

from __future__ import annotations

import contextlib
import json
import logging
import math
import os
import tempfile
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from src.risk.accounting import AggregatorState, _validate_persisted_state_decimals
from src.risk.config import AggregatorConfig, _state_file
from src.risk.observations import _accounting_cut_max_skew_s, _parse_aware_timestamp

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger("aggregator")
STATE_SCHEMA_VERSION = 2
_EXPECTED_ENFORCEMENT_SOURCES: dict[str, str] = {
    "group_daily_pnl": "ledger",
    "daily_realized_pnl": "ledger",
    "daily_unrealized_pnl": "venue",
    "group_net_exposure": "venue",
    "group_gross_exposure": "venue",
    "drawdown_sod_pct": "venue",
    "drawdown_hwm_pct": "venue",
    "margin_used": "venue",
    "margin_ratio": "venue",
    "open_position_count": "venue",
    "open_order_count": "venue",
}

def _is_healthy(
    state: AggregatorState,
    config: AggregatorConfig,
    *,
    now_utc: datetime | None = None,
) -> bool:
    if (
        state.fail_closed
        or state.last_success_ts is None
        or state.last_snapshot is None
        or not state.drawdown_baseline_verified
    ):
        return False
    observation_time = now_utc or datetime.now(UTC)
    if observation_time.tzinfo is None or observation_time.utcoffset() is None:
        return False
    raw_future_skew = config.future_skew_tolerance_s
    if (
        isinstance(raw_future_skew, bool)
        or not isinstance(raw_future_skew, (int, float))
        or not math.isfinite(float(raw_future_skew))
        or not 0 <= float(raw_future_skew) <= 5
    ):
        return False
    future_skew = timedelta(seconds=float(raw_future_skew))
    required_times = (
        state.last_success_ts,
        state.venue_as_of_ts,
        state.positions_as_of_ts,
        state.orders_as_of_ts,
        state.ledger_as_of_ts,
    )
    for timestamp in required_times:
        if timestamp is None:
            return False
        age = observation_time.astimezone(UTC) - timestamp.astimezone(UTC)
        if age < -future_skew or age > timedelta(seconds=config.health_window_s):
            return False
    return True


def _metric_metadata(
    source: str,
    as_of: datetime | None,
    now_utc: datetime,
    *,
    component_sources: dict[str, str] | None = None,
) -> dict[str, Any]:
    if as_of is None:
        metadata: dict[str, Any] = {
            "source": "none",
            "as_of_ts": None,
            "age_seconds": None,
        }
    else:
        normalized = as_of.astimezone(UTC)
        metadata = {
            "source": source,
            "as_of_ts": normalized.isoformat(),
            "age_seconds": (now_utc - normalized).total_seconds(),
        }
    if component_sources is not None:
        metadata["component_sources"] = component_sources
    return metadata


def _state_metric_metadata(
    state: AggregatorState, now_utc: datetime
) -> dict[str, dict[str, Any]]:
    position_metrics = (
        "group_net_exposure",
        "group_gross_exposure",
        "open_position_count",
    )
    account_metrics = (
        "drawdown_sod_pct",
        "drawdown_hwm_pct",
        "margin_used",
        "margin_ratio",
    )
    metadata = {
        metric: _metric_metadata("venue", state.venue_as_of_ts, now_utc)
        for metric in account_metrics
    }
    metadata.update(
        {
            metric: _metric_metadata("venue", state.positions_as_of_ts, now_utc)
            for metric in position_metrics
        }
    )
    metadata["open_order_count"] = _metric_metadata(
        "venue", state.orders_as_of_ts, now_utc
    )
    group_as_of: datetime | None = None
    if state.ledger_as_of_ts is not None and state.positions_as_of_ts is not None:
        group_as_of = min(state.ledger_as_of_ts, state.positions_as_of_ts)
    metadata["daily_realized_pnl"] = _metric_metadata(
        "ledger", group_as_of, now_utc
    )
    metadata["daily_unrealized_pnl"] = _metric_metadata(
        "venue", state.positions_as_of_ts, now_utc
    )
    metadata["pending_daily_realized_pnl"] = _metric_metadata(
        "ledger", state.ledger_as_of_ts, now_utc
    )
    metadata["group_daily_pnl"] = _metric_metadata(
        "ledger",
        group_as_of,
        now_utc,
        component_sources={"realized": "ledger", "unrealized": "venue"},
    )
    metadata["log_unrealized_telemetry"] = _metric_metadata(
        "log", state.log_as_of_ts, now_utc
    )
    return metadata


def validate_state_metric_metadata(
    payload: dict[str, Any],
    *,
    max_age_s: float,
    now: datetime | None = None,
) -> None:
    """Reject stale or non-authoritative state using the consumer's clock.

    Stored ``age_seconds`` values are checked for structural validity only.
    Freshness is always recomputed from ``as_of_ts`` and ``published_at``.
    """
    if payload.get("schema_version") != STATE_SCHEMA_VERSION:
        raise ValueError("unsupported or missing state schema_version")
    if isinstance(max_age_s, bool) or not math.isfinite(max_age_s) or max_age_s < 0:
        raise ValueError("max_age_s must be non-negative")
    requested_time = now or datetime.now(UTC)
    if requested_time.tzinfo is None or requested_time.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    observation_time = requested_time.astimezone(UTC)
    config_payload = payload.get("config")
    if not isinstance(config_payload, dict):
        raise ValueError("config must be an object")
    raw_future_skew = config_payload.get("future_skew_tolerance_s")
    if (
        isinstance(raw_future_skew, bool)
        or not isinstance(raw_future_skew, (int, float))
        or not math.isfinite(float(raw_future_skew))
        or not 0 <= float(raw_future_skew) <= 5
    ):
        raise ValueError("future_skew_tolerance_s is missing or malformed")
    future_skew = timedelta(seconds=float(raw_future_skew))
    published_at = _parse_aware_timestamp(payload.get("published_at"), "published_at")
    published_age = observation_time - published_at
    if published_age < -future_skew:
        raise ValueError("published_at cannot be in the future")
    if published_age > timedelta(seconds=max_age_s):
        raise ValueError("published_at is stale")
    all_metadata = payload.get("metric_metadata")
    if not isinstance(all_metadata, dict):
        raise ValueError("metric_metadata must be an object")
    for metric, expected_source in _EXPECTED_ENFORCEMENT_SOURCES.items():
        metadata = all_metadata.get(metric)
        if not isinstance(metadata, dict):
            raise ValueError(f"{metric} metadata is missing or malformed")
        source = metadata.get("source")
        if source != expected_source:
            raise ValueError(
                f"{metric} source must be {expected_source}, got {source!r}"
            )
        age = metadata.get("age_seconds")
        if isinstance(age, bool) or not isinstance(age, (int, float)):
            raise ValueError(f"{metric} age_seconds is missing or malformed")
        if not math.isfinite(float(age)):
            raise ValueError(f"{metric} age_seconds must be finite")
        if float(age) < -float(raw_future_skew):
            raise ValueError(f"{metric} age_seconds exceeds future-skew tolerance")
        parsed = _parse_aware_timestamp(
            metadata.get("as_of_ts"), f"{metric} as_of_ts"
        )
        recomputed_age = observation_time - parsed
        if recomputed_age < -future_skew:
            raise ValueError(f"{metric} as_of_ts cannot be in the future")
        if recomputed_age > timedelta(seconds=max_age_s):
            raise ValueError(f"{metric} metadata is stale")
        if parsed - published_at > future_skew:
            raise ValueError(f"{metric} as_of_ts cannot be after published_at")
    group_components = all_metadata["group_daily_pnl"].get("component_sources")
    if group_components != {"realized": "ledger", "unrealized": "venue"}:
        raise ValueError("group_daily_pnl component_sources are not authoritative")


def state_to_dict(
    state: AggregatorState,
    config: AggregatorConfig,
    *,
    now_utc: datetime | None = None,
) -> dict[str, Any]:
    requested_time = now_utc or datetime.now(UTC)
    if requested_time.tzinfo is None or requested_time.utcoffset() is None:
        raise ValueError("now_utc must be timezone-aware")
    observation_time = requested_time.astimezone(UTC)
    snapshot = _validate_persisted_state_decimals(state)
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "published_at": observation_time.isoformat(),
        "risk_group": state.risk_group,
        "healthy": _is_healthy(state, config, now_utc=observation_time),
        "fail_closed": state.fail_closed,
        "soft_cap": state.soft_cap,
        "hard_cap": state.hard_cap,
        "margin_emergency": state.margin_emergency,
        "last_success_ts": (
            state.last_success_ts.isoformat() if state.last_success_ts else None
        ),
        "consecutive_failures": state.consecutive_failures,
        "group_net_exposure": str(state.group_net_exposure),
        "group_gross_exposure": str(state.group_gross_exposure),
        "group_daily_pnl": str(state.group_daily_pnl),
        "daily_realized_pnl": str(state.daily_realized_pnl),
        "pending_daily_realized_pnl": str(state.pending_daily_realized_pnl),
        "daily_unrealized_pnl": str(state.daily_unrealized_pnl),
        "open_position_count": state.open_position_count,
        "open_order_count": state.open_order_count,
        "margin_used": str(snapshot.margin_used) if snapshot is not None else None,
        "margin_ratio": str(snapshot.margin_ratio) if snapshot is not None else None,
        "drawdown_sod_pct": str(state.drawdown_sod_pct),
        "drawdown_hwm_pct": str(state.drawdown_hwm_pct),
        "start_of_day_equity": (
            str(state.start_of_day_equity) if state.start_of_day_equity is not None else None
        ),
        "high_water_mark": (
            str(state.high_water_mark) if state.high_water_mark is not None else None
        ),
        "current_utc_date": (
            state.current_utc_date.isoformat() if state.current_utc_date is not None else None
        ),
        "quarantined_strategies": sorted(state.quarantined_strategies),
        "residual_strategy_ids": sorted(state.residual_strategy_ids),
        "log_unrealized_telemetry": {
            f"{strategy_id}\x00{symbol}": str(value)
            for (strategy_id, symbol), value in sorted(state.latest_unrealized.items())
        },
        "metric_metadata": _state_metric_metadata(state, observation_time),
        "config": {
            "account_scope": config.account_scope,
            "quote_currency": config.quote_currency,
            "soft_cap_daily_loss_pct": config.soft_cap_daily_loss_pct,
            "hard_cap_daily_loss_pct": config.hard_cap_daily_loss_pct,
            "margin_emergency_threshold": config.margin_emergency_threshold,
            "health_window_s": config.health_window_s,
            "future_skew_tolerance_s": config.future_skew_tolerance_s,
            "accounting_cut_max_skew_s": _accounting_cut_max_skew_s(config),
        },
    }


def publish_state(
    path: Path,
    state: AggregatorState,
    config: AggregatorConfig,
    *,
    now_utc: datetime | None = None,
) -> None:
    """Atomic JSON write."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        state_to_dict(state, config, now_utc=now_utc), sort_keys=True
    ).encode("utf-8")
    with tempfile.NamedTemporaryFile(
        mode="wb",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as tmp:
        tmp_name = tmp.name
        try:
            tmp.write(payload)
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


def _publish_startup_fail_closed_state(
    project_root: Path,
    config: AggregatorConfig,
) -> None:
    """Replace any prior healthy state when startup authority is refused."""
    state = AggregatorState(risk_group=config.risk_group)
    state.fail_closed = True
    try:
        publish_state(_state_file(project_root, config.risk_group), state, config)
    except Exception as exc:
        logger.critical("failed to publish startup fail-closed state: %s", exc)
