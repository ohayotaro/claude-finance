"""Tests for risk aggregator publication."""

from __future__ import annotations

# Test modules intentionally share a compatibility-heavy import surface while
# assertions move unchanged to their owning modules.
# ruff: noqa: F401, TC001, TC002, TC003
import json
import logging
import os
import signal
import threading
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, localcontext
from pathlib import Path

import pytest

import src.risk.accounting as accounting_module
import src.risk.aggregator as aggregator_module
import src.risk.observations as observations_module
import src.risk.persistence as persistence_module
from src.orchestrator.registry import (
    ExitCode,
    RegistryDefaults,
    RegistryDocument,
    Runtime,
    StrategyEntry,
    StrategyState,
    atomic_replace,
    dump_registry,
)
from src.risk.accounting import AggregatorState, compute_group_metrics, determine_signals
from src.risk.aggregator import main, reconcile_once, run_forever
from src.risk.config import (
    AggregatorConfig,
    _checkpoint_file,
    _ledger_file,
    _state_file,
    load_aggregator_config,
)
from src.risk.ledger import FillLedger, LedgerError, VenueCashEvent, VenueFill, VenueLedgerBatch
from src.risk.observations import (
    NullVenueClient,
    StrategyLogStatus,
    VenueAccountSnapshot,
    VenueClientLoadError,
    VenueOrder,
    VenueOrdersObservation,
    VenuePosition,
    VenuePositionsObservation,
    load_group_strategies,
    load_venue_client,
    read_strategy_log_delta,
    resolve_venue_client_spec,
)
from src.risk.persistence import _exclusive_ledger_directory_lock, load_checkpoint, save_checkpoint
from src.risk.publication import publish_state, state_to_dict, validate_state_metric_metadata
from tests.test_risk._aggregator_support import (
    StubVenueClient,
    _default_config,
    _ledger_batch,
    _make_entry,
    _snapshot,
    _write_registry,
    _write_risk_group_config,
)

_TS = "2026-05-14T00:00:00Z"

def test_drawdown_published_in_state_dict() -> None:
    """state_to_dict includes drawdown_sod_pct and drawdown_hwm_pct."""
    config = _default_config()
    state = AggregatorState(risk_group=config.risk_group)
    state.last_success_ts = datetime.now(UTC)
    state.drawdown_sod_pct = Decimal("-2.5")
    state.drawdown_hwm_pct = Decimal("-4.0")
    state.start_of_day_equity = Decimal("10000")
    state.high_water_mark = Decimal("10500")
    d = state_to_dict(state, config)
    assert d["drawdown_sod_pct"] == "-2.5"
    assert d["drawdown_hwm_pct"] == "-4.0"
    assert d["start_of_day_equity"] == "10000"
    assert d["high_water_mark"] == "10500"


def test_publish_state_writes_valid_json(tmp_path: Path) -> None:
    config = _default_config()
    state = AggregatorState(risk_group=config.risk_group)
    observed_at = datetime.now(UTC)
    state.last_success_ts = observed_at
    state.last_snapshot = _snapshot(timestamp=observed_at)
    state.venue_as_of_ts = observed_at
    state.positions_as_of_ts = observed_at
    state.orders_as_of_ts = observed_at
    state.ledger_as_of_ts = observed_at
    state.drawdown_baseline_verified = True
    state.group_daily_pnl = Decimal("12.5")
    out = tmp_path / "state.json"
    publish_state(out, state, config)
    assert out.exists()
    # No leftover temp file in the same directory.
    siblings = [p for p in out.parent.iterdir() if p.is_file() and p.name != out.name]
    assert siblings == []
    data = json.loads(out.read_text())
    assert data["risk_group"] == config.risk_group
    assert data["healthy"] is True
    assert data["fail_closed"] is False
    assert data["group_daily_pnl"] == "12.5"


def test_state_to_dict_healthy_window() -> None:
    config = _default_config()
    state = AggregatorState(risk_group=config.risk_group)
    state.last_success_ts = datetime.now(UTC) - timedelta(seconds=999)
    assert state_to_dict(state, config)["healthy"] is False


def test_state_to_dict_unhealthy_when_fail_closed() -> None:
    config = _default_config()
    state = AggregatorState(risk_group=config.risk_group)
    state.last_success_ts = datetime.now(UTC)
    state.fail_closed = True
    assert state_to_dict(state, config)["healthy"] is False


def test_state_schema_v2_publishes_required_metric_metadata(tmp_path: Path) -> None:
    now = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    client = StubVenueClient(
        snapshot=_snapshot(
            balance=Decimal("10000"),
            margin_ratio=Decimal("0.25"),
            timestamp=now,
        ),
        ledger_batches=(_ledger_batch(now),),
    )
    state = AggregatorState(risk_group="crypto-main")
    ledger = FillLedger(tmp_path / "ledger.sqlite3", "binance-main", "USD")
    reconcile_once(
        client,
        _default_config(),
        [],
        state,
        {},
        tmp_path,
        now_utc=now,
        clock=lambda: now,
        ledger=ledger,
    )

    data = state_to_dict(state, _default_config(), now_utc=now + timedelta(seconds=5))

    assert data["schema_version"] == 2
    assert data["published_at"] == (now + timedelta(seconds=5)).isoformat()
    expected_sources = {
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
    for metric, source in expected_sources.items():
        assert data["metric_metadata"][metric]["source"] == source
        assert data["metric_metadata"][metric]["age_seconds"] == 5.0
    assert data["metric_metadata"]["group_daily_pnl"]["component_sources"] == {
        "realized": "ledger",
        "unrealized": "venue",
    }
    validate_state_metric_metadata(
        data, max_age_s=10, now=now + timedelta(seconds=5)
    )


def test_metric_consumer_rejects_log_source_and_stale_age(tmp_path: Path) -> None:
    now = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    client = StubVenueClient(
        snapshot=_snapshot(timestamp=now),
        ledger_batches=(_ledger_batch(now),),
    )
    state = AggregatorState(risk_group="crypto-main")
    reconcile_once(
        client,
        _default_config(),
        [],
        state,
        {},
        tmp_path,
        now_utc=now,
        clock=lambda: now,
        ledger=FillLedger(tmp_path / "ledger.sqlite3", "binance-main", "USD"),
    )
    data = state_to_dict(state, _default_config(), now_utc=now)
    data["metric_metadata"]["group_daily_pnl"]["source"] = "log"
    with pytest.raises(ValueError, match="group_daily_pnl.*source"):
        validate_state_metric_metadata(data, max_age_s=10, now=now)

    data = state_to_dict(state, _default_config(), now_utc=now)
    data["metric_metadata"]["margin_ratio"]["as_of_ts"] = (
        now - timedelta(seconds=11)
    ).isoformat()
    with pytest.raises(ValueError, match="margin_ratio.*stale"):
        validate_state_metric_metadata(data, max_age_s=10, now=now)


def test_null_venue_publishes_none_sources_and_is_unhealthy(tmp_path: Path) -> None:
    state = AggregatorState(risk_group="crypto-main")
    reconcile_once(
        NullVenueClient(),
        _default_config(),
        [],
        state,
        {},
        tmp_path,
        ledger=FillLedger(tmp_path / "ledger.sqlite3", "binance-main", "USD"),
    )
    data = state_to_dict(state, _default_config())
    assert data["healthy"] is False
    assert data["metric_metadata"]["group_daily_pnl"]["source"] == "none"
    assert data["metric_metadata"]["group_daily_pnl"]["age_seconds"] is None


def test_metric_consumer_recomputes_age_from_as_of_ts(tmp_path: Path) -> None:
    now = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    client = StubVenueClient(
        snapshot=_snapshot(timestamp=now),
        ledger_batches=(_ledger_batch(now),),
    )
    state = AggregatorState(risk_group="crypto-main")
    reconcile_once(
        client,
        _default_config(),
        [],
        state,
        {},
        tmp_path,
        now_utc=now,
        clock=lambda: now,
        ledger=FillLedger(tmp_path / "ledger.sqlite3", "binance-main", "USD"),
    )
    data = state_to_dict(state, _default_config(), now_utc=now)

    # Stored ages are informational and cannot keep an old observation fresh.
    for metadata in data["metric_metadata"].values():
        if metadata["source"] in {"venue", "ledger"}:
            metadata["age_seconds"] = 0.0
    with pytest.raises(ValueError, match="stale"):
        validate_state_metric_metadata(
            data,
            max_age_s=10,
            now=now + timedelta(seconds=11),
        )

    # Even internally fresh-looking metric timestamps cannot rescue an old file.
    republished = state_to_dict(
        state,
        _default_config(),
        now_utc=now + timedelta(seconds=5),
    )
    for metadata in republished["metric_metadata"].values():
        if metadata["source"] in {"venue", "ledger"}:
            metadata["as_of_ts"] = (now + timedelta(seconds=19)).isoformat()
            metadata["age_seconds"] = 0.0
    with pytest.raises(ValueError, match="published_at.*stale"):
        validate_state_metric_metadata(
            republished,
            max_age_s=10,
            now=now + timedelta(seconds=20),
        )


def test_position_metrics_carry_their_own_observation_age(tmp_path: Path) -> None:
    now = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    position_as_of = now - timedelta(seconds=10)
    order_as_of = now - timedelta(seconds=20)

    class IndependentlyTimedClient(StubVenueClient):
        def fetch_group_positions(
            self, strategy_ids: Sequence[str]
        ) -> VenuePositionsObservation:
            return VenuePositionsObservation(
                positions=(), as_of=position_as_of, complete=True
            )

        def fetch_open_orders(
            self, strategy_ids: Sequence[str]
        ) -> VenueOrdersObservation:
            return VenueOrdersObservation(orders=(), as_of=order_as_of, complete=True)

    client = IndependentlyTimedClient(
        snapshot=_snapshot(timestamp=now),
        ledger_batches=(_ledger_batch(now),),
    )
    config = replace(_default_config(), accounting_cut_max_skew_s=10.0)
    state = AggregatorState(risk_group="crypto-main")
    reconcile_once(
        client,
        config,
        [],
        state,
        {},
        tmp_path,
        now_utc=now,
        clock=lambda: now,
        ledger=FillLedger(tmp_path / "ledger.sqlite3", "binance-main", "USD"),
    )

    data = state_to_dict(state, config, now_utc=now)
    assert data["metric_metadata"]["group_gross_exposure"]["age_seconds"] == 10.0
    assert data["metric_metadata"]["daily_unrealized_pnl"]["age_seconds"] == 10.0
    assert data["metric_metadata"]["open_position_count"]["age_seconds"] == 10.0
    assert data["metric_metadata"]["open_order_count"]["age_seconds"] == 20.0
    assert data["metric_metadata"]["margin_ratio"]["age_seconds"] == 0.0


def test_checkpoint_binding_mismatch_publishes_unhealthy_state(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    ledger = FillLedger(tmp_path / "ledger.sqlite3", "binance-main", "USD")
    state = AggregatorState(risk_group="crypto-main")
    reconcile_once(
        StubVenueClient(
            snapshot=_snapshot(timestamp=now),
            ledger_batches=(_ledger_batch(now, cursor="cursor-1"),),
        ),
        _default_config(),
        [],
        state,
        {},
        tmp_path,
        now_utc=now,
        clock=lambda: now,
        ledger=ledger,
    )
    checkpoint_path = tmp_path / "checkpoint.json"
    assert save_checkpoint(checkpoint_path, state, {}, ledger=ledger) is True
    assert state_to_dict(state, _default_config(), now_utc=now)["healthy"] is True

    ledger.ingest_batch(
        _ledger_batch(now + timedelta(seconds=1), cursor="cursor-2"), set()
    )
    assert save_checkpoint(checkpoint_path, state, {}, ledger=ledger) is False

    payload = state_to_dict(state, _default_config(), now_utc=now)
    assert state.fail_closed is True
    assert state.checkpoint_save_allowed is False
    assert payload["healthy"] is False
    assert payload["metric_metadata"]["group_daily_pnl"]["source"] == "none"
    assert payload["metric_metadata"]["group_gross_exposure"]["source"] == "none"


def test_allowed_future_skew_publishes_healthy_and_validates(tmp_path: Path) -> None:
    now = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    observed_at = now + timedelta(seconds=1)
    config = replace(_default_config(), future_skew_tolerance_s=2.0)
    state = AggregatorState(risk_group=config.risk_group)

    reconcile_once(
        StubVenueClient(
            snapshot=_snapshot(timestamp=observed_at),
            ledger_batches=(_ledger_batch(observed_at),),
        ),
        config,
        [],
        state,
        {},
        tmp_path,
        now_utc=now,
        clock=lambda: now,
        ledger=FillLedger(tmp_path / "ledger.sqlite3", "binance-main", "USD"),
    )

    payload = state_to_dict(state, config, now_utc=now)
    assert payload["config"]["future_skew_tolerance_s"] == 2.0
    assert payload["healthy"] is True
    assert payload["metric_metadata"]["group_daily_pnl"]["age_seconds"] == -1.0
    validate_state_metric_metadata(payload, max_age_s=10.0, now=now)
