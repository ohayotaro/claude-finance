"""Tests for risk aggregator accounting."""

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

def test_compute_group_metrics() -> None:
    positions = [
        VenuePosition(
            strategy_id="a",
            symbol="BTCUSDT",
            side="long",
            size=Decimal("1"),
            entry_price=Decimal("60000"),
            unrealized_pnl=Decimal("0"),
            account_scope="binance-main",
            quote_currency="USD",
        ),
        VenuePosition(
            strategy_id="b",
            symbol="ETHUSDT",
            side="short",
            size=Decimal("10"),
            entry_price=Decimal("3000"),
            unrealized_pnl=Decimal("0"),
            account_scope="binance-main",
            quote_currency="USD",
        ),
    ]
    net, gross, count = compute_group_metrics(positions)
    assert net == Decimal("60000") - Decimal("30000")
    assert gross == Decimal("90000")
    assert count == 2


def test_determine_signals_soft_cap() -> None:
    state = AggregatorState(risk_group="g")
    state.last_snapshot = _snapshot(balance=Decimal("10000"))
    state.group_daily_pnl = Decimal("-350")  # -3.5% -> soft cap
    config = _default_config()
    determine_signals(state, config)
    assert state.soft_cap is True
    assert state.hard_cap is False


def test_determine_signals_hard_cap() -> None:
    state = AggregatorState(risk_group="g")
    state.last_snapshot = _snapshot(balance=Decimal("10000"))
    state.group_daily_pnl = Decimal("-600")  # -6% -> hard cap
    config = _default_config()
    determine_signals(state, config)
    assert state.soft_cap is True
    assert state.hard_cap is True


def test_hard_cap_boundary_is_exact_without_ambient_rounding() -> None:
    state = AggregatorState(risk_group="g")
    state.last_snapshot = _snapshot(balance=Decimal("100"))
    state.group_daily_pnl = Decimal("-4.9999999999999999999999999999")

    with localcontext() as ambient_context:
        ambient_context.prec = 10
        determine_signals(state, _default_config())

    assert state.soft_cap is True
    assert state.hard_cap is False


def test_determine_signals_margin_emergency() -> None:
    state = AggregatorState(risk_group="g")
    state.last_snapshot = _snapshot(balance=Decimal("10000"), margin_ratio=Decimal("0.98"))
    state.group_daily_pnl = Decimal("0")
    config = _default_config()
    determine_signals(state, config)
    assert state.margin_emergency is True


def test_log_unrealized_telemetry_overwrites_without_affecting_caps(
    tmp_path: Path,
) -> None:
    """Log levels remain useful telemetry but never affect enforcement PnL."""
    config = _default_config()
    sid = "binance.swap.x.btc.5m.v1"
    entry = _make_entry(sid)
    log_dir = tmp_path / "logs" / "strategies" / sid
    log_dir.mkdir(parents=True)
    log_file = log_dir / "bot.jsonl"
    today = datetime.now(UTC).date().isoformat()
    lines = [
        json.dumps({
            "event": "position_update", "strategy_id": sid,
            "symbol": "BTCUSDT", "unrealized_pnl": 100, "ts": f"{today}T01:00:00Z",
        }),
        json.dumps({
            "event": "position_update", "strategy_id": sid,
            "symbol": "BTCUSDT", "unrealized_pnl": 120, "ts": f"{today}T01:01:00Z",
        }),
    ]
    log_file.write_text("\n".join(lines) + "\n")

    now = datetime.now(UTC)
    client = StubVenueClient(
        snapshot=_snapshot(timestamp=now),
        positions=(
            VenuePosition(
                strategy_id=sid,
                symbol="BTCUSDT",
                side="long",
                size=Decimal("1"),
                entry_price=Decimal("100"),
                unrealized_pnl=Decimal("0"),
                account_scope="binance-main",
                quote_currency="USD",
            ),
        ),
        ledger_batches=(_ledger_batch(now),),
    )
    state = AggregatorState(risk_group=config.risk_group)
    log_statuses: dict[str, StrategyLogStatus] = {}
    state = reconcile_once(
        client, config, [entry], state, log_statuses, tmp_path,
    )
    assert state.group_daily_pnl == Decimal("0")
    assert state.latest_unrealized[(sid, "BTCUSDT")] == Decimal("120")


def test_log_realized_pnl_never_contributes_across_cycles(tmp_path: Path) -> None:
    """Replayed position_closed telemetry cannot enter enforcement accounting."""
    config = _default_config()
    sid = "binance.swap.x.btc.5m.v1"
    entry = _make_entry(sid)
    log_dir = tmp_path / "logs" / "strategies" / sid
    log_dir.mkdir(parents=True)
    log_file = log_dir / "bot.jsonl"
    today = datetime.now(UTC).date().isoformat()

    # Cycle 1: one position_closed with pnl=50.
    log_file.write_text(
        json.dumps({
            "event": "position_closed", "strategy_id": sid,
            "symbol": "BTCUSDT", "pnl": 50, "ts": f"{today}T02:00:00Z",
        }) + "\n"
    )
    now = datetime.now(UTC)
    client = StubVenueClient(snapshot=_snapshot(timestamp=now))
    state = AggregatorState(risk_group=config.risk_group)
    log_statuses: dict[str, StrategyLogStatus] = {}
    state = reconcile_once(client, config, [entry], state, log_statuses, tmp_path)
    assert state.daily_realized_pnl == Decimal("0")

    # Cycle 2: append another position_closed with pnl=30.
    with log_file.open("a") as fh:
        fh.write(
            json.dumps({
                "event": "position_closed", "strategy_id": sid,
                "symbol": "BTCUSDT", "pnl": 30, "ts": f"{today}T02:05:00Z",
            }) + "\n"
        )
    state = reconcile_once(client, config, [entry], state, log_statuses, tmp_path)
    assert state.daily_realized_pnl == Decimal("0")
    assert state.group_daily_pnl == Decimal("0")


def test_utc_day_boundary_resets_and_hwm_survives(tmp_path: Path) -> None:
    """On UTC day change: counters reset, SoD re-anchors, HWM survives."""
    config = _default_config()
    day1 = datetime(2026, 6, 10, 23, 0, 0, tzinfo=UTC)
    day2 = datetime(2026, 6, 11, 1, 0, 0, tzinfo=UTC)

    snap_d1 = VenueAccountSnapshot(
        account_scope="binance-main", balance=Decimal("10000"), equity=Decimal("10500"),
        margin_used=Decimal("0"), margin_ratio=Decimal("0"), timestamp=day1,
        quote_currency="USD",
    )
    snap_d2 = VenueAccountSnapshot(
        account_scope="binance-main", balance=Decimal("10000"), equity=Decimal("10200"),
        margin_used=Decimal("0"), margin_ratio=Decimal("0"), timestamp=day2,
        quote_currency="USD",
    )

    class DayClient:
        def __init__(self) -> None:
            self.snap = snap_d1

        def fetch_account_snapshot(self, account_scope: str) -> VenueAccountSnapshot:
            return self.snap

        def fetch_group_positions(
            self, strategy_ids: Sequence[str]
        ) -> VenuePositionsObservation:
            return VenuePositionsObservation(
                positions=(), as_of=self.snap.timestamp, complete=True
            )

        def fetch_open_orders(
            self, strategy_ids: Sequence[str]
        ) -> VenueOrdersObservation:
            return VenueOrdersObservation(
                orders=(), as_of=self.snap.timestamp, complete=True
            )

        def fetch_ledger_batch(
            self,
            account_scope: str,
            strategy_ids: Sequence[str],
            cursor: str | None,
        ) -> VenueLedgerBatch:
            return _ledger_batch(self.snap.timestamp, cursor=cursor or "cursor-day")

    client = DayClient()
    state = AggregatorState(risk_group=config.risk_group)
    log_statuses: dict[str, StrategyLogStatus] = {}

    # A stale in-memory accumulator is replaced by the ledger query.
    state.daily_realized_pnl = Decimal("50")
    state.current_utc_date = day1.date()

    # Day 1 cycle.
    state = reconcile_once(
        client,
        config,
        [],
        state,
        log_statuses,
        tmp_path,
        now_utc=day1,
        clock=lambda: day1,
    )
    assert state.start_of_day_equity == Decimal("10500")
    assert state.high_water_mark == Decimal("10500")
    assert state.daily_realized_pnl == Decimal("0")

    # Day 2 cycle -- day boundary.
    client.snap = snap_d2
    state = reconcile_once(
        client,
        config,
        [],
        state,
        log_statuses,
        tmp_path,
        now_utc=day2,
        clock=lambda: day2,
    )
    assert state.current_utc_date == day2.date()
    # Realized PnL reset.
    assert state.daily_realized_pnl == Decimal("0")
    # SoD equity re-anchored.
    assert state.start_of_day_equity == Decimal("10200")
    # HWM survives from day 1.
    assert state.high_water_mark == Decimal("10500")
    # Drawdown from HWM.
    assert state.drawdown_hwm_pct == Decimal("-2.86")


def test_venue_zero_unrealized_overrides_log_telemetry(tmp_path: Path) -> None:
    sid = "binance.swap.x.btcusdt.5m.v1"
    entry = _make_entry(sid)
    log_dir = tmp_path / entry.log_path
    log_dir.mkdir(parents=True)
    now = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    (log_dir / "bot.jsonl").write_text(
        json.dumps(
            {
                "event": "position_update",
                "strategy_id": sid,
                "symbol": "BTCUSDT",
                "unrealized_pnl": "999.25",
                "ts": now.isoformat(),
            }
        )
        + "\n"
    )
    position = VenuePosition(
        strategy_id=sid,
        symbol="BTCUSDT",
        side="long",
        size=Decimal("1"),
        entry_price=Decimal("100"),
        unrealized_pnl=Decimal("0"),
        account_scope="binance-main",
        quote_currency="USD",
    )
    client = StubVenueClient(
        snapshot=_snapshot(timestamp=now),
        positions=(position,),
        ledger_batches=(_ledger_batch(now),),
    )
    state = AggregatorState(risk_group="crypto-main")
    ledger = FillLedger(
        tmp_path / "data/aggregator/crypto-main/ledger.sqlite3",
        "binance-main",
        "USD",
    )

    reconcile_once(
        client,
        _default_config(),
        [entry],
        state,
        {},
        tmp_path,
        now_utc=now,
        clock=lambda: now,
        ledger=ledger,
    )

    assert state.latest_unrealized[(sid, "BTCUSDT")] == Decimal("999.25")
    assert state.daily_unrealized_pnl == Decimal("0")
    assert state.group_daily_pnl == Decimal("0")


def test_venue_omission_prunes_log_unrealized_from_caps(tmp_path: Path) -> None:
    sid = "binance.swap.x.btcusdt.5m.v1"
    entry = _make_entry(sid)
    now = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    state = AggregatorState(risk_group="crypto-main")
    state.latest_unrealized[(sid, "BTCUSDT")] = Decimal("-900")
    ledger = FillLedger(tmp_path / "ledger.sqlite3", "binance-main", "USD")
    client = StubVenueClient(
        snapshot=_snapshot(timestamp=now),
        ledger_batches=(_ledger_batch(now),),
    )

    reconcile_once(
        client,
        _default_config(),
        [entry],
        state,
        {},
        tmp_path,
        now_utc=now,
        clock=lambda: now,
        ledger=ledger,
    )

    assert state.latest_unrealized == {}
    assert state.daily_unrealized_pnl == Decimal("0")
    assert state.group_daily_pnl == Decimal("0")
    assert state.soft_cap is False


def test_disabled_strategy_residual_position_counts_until_flat(
    tmp_path: Path,
) -> None:
    disabled = _make_entry("binance.swap.x.btcusdt.5m.v1", enabled=False)
    strategies = load_group_strategies(
        RegistryDocument(
            schema_version=1,
            defaults=RegistryDefaults(),
            accounts=[],
            strategies=[disabled],
        ),
        "crypto-main",
    )
    assert {strategy.id for strategy in strategies} == {disabled.id}
    now = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    position = VenuePosition(
        strategy_id=disabled.id,
        symbol="BTCUSDT",
        side="long",
        size=Decimal("2"),
        entry_price=Decimal("1000"),
        unrealized_pnl=Decimal("-400"),
        account_scope="binance-main",
        quote_currency="USD",
    )
    client = StubVenueClient(
        snapshot=_snapshot(timestamp=now),
        positions=(position,),
        ledger_batches=(_ledger_batch(now), _ledger_batch(now, cursor="cursor-2")),
    )
    state = AggregatorState(risk_group="crypto-main")
    ledger = FillLedger(tmp_path / "ledger.sqlite3", "binance-main", "USD")

    reconcile_once(
        client,
        _default_config(),
        strategies,
        state,
        {},
        tmp_path,
        now_utc=now,
        clock=lambda: now,
        ledger=ledger,
    )
    assert state.residual_strategy_ids == {disabled.id}
    assert state.group_gross_exposure == Decimal("2000")
    assert state.daily_unrealized_pnl == Decimal("-400")
    assert state.group_daily_pnl == Decimal("-400")
    assert state.open_position_count == 1
    assert state.open_order_count == 0
    assert state.soft_cap is True

    client._positions = ()
    client._orders = ()
    reconcile_once(
        client,
        _default_config(),
        strategies,
        state,
        {},
        tmp_path,
        now_utc=now,
        clock=lambda: now,
        ledger=ledger,
    )
    assert state.residual_strategy_ids == set()
    assert state.group_gross_exposure == Decimal("0")
    assert state.open_position_count == 0
    assert state.open_order_count == 0


def test_deprecated_strategy_position_pnl_counts_toward_caps(
    tmp_path: Path,
) -> None:
    deprecated = _make_entry(
        "binance.swap.y.ethusdt.5m.v1",
        state=StrategyState.DEPRECATED,
        enabled=False,
    )
    now = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    position = VenuePosition(
        strategy_id=deprecated.id,
        symbol="ETHUSDT",
        side="short",
        size=Decimal("2"),
        entry_price=Decimal("1000"),
        unrealized_pnl=Decimal("-400"),
        account_scope="binance-main",
        quote_currency="USD",
    )
    client = StubVenueClient(
        snapshot=_snapshot(timestamp=now),
        positions=(position,),
        ledger_batches=(_ledger_batch(now), _ledger_batch(now, cursor="cursor-2")),
    )
    state = AggregatorState(risk_group="crypto-main")
    ledger = FillLedger(tmp_path / "ledger.sqlite3", "binance-main", "USD")

    reconcile_once(
        client,
        _default_config(),
        [deprecated],
        state,
        {},
        tmp_path,
        now_utc=now,
        clock=lambda: now,
        ledger=ledger,
    )

    assert state.residual_strategy_ids == {deprecated.id}
    assert state.group_net_exposure == Decimal("-2000")
    assert state.group_gross_exposure == Decimal("2000")
    assert state.daily_unrealized_pnl == Decimal("-400")
    assert state.group_daily_pnl == Decimal("-400")
    assert state.soft_cap is True

    client._positions = ()
    reconcile_once(
        client,
        _default_config(),
        [deprecated],
        state,
        {},
        tmp_path,
        now_utc=now,
        clock=lambda: now,
        ledger=ledger,
    )
    assert state.residual_strategy_ids == set()


def test_retired_strategy_residual_order_counts_until_flat(tmp_path: Path) -> None:
    retired = _make_entry(
        "binance.swap.z.solusdt.5m.v1",
        state=StrategyState.RETIRED,
        enabled=False,
    )
    now = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    order = VenueOrder(
        order_id="open-1",
        strategy_id=retired.id,
        symbol="SOLUSDT",
        side="buy",
        size=Decimal("3"),
        price=Decimal("200"),
        status="open",
        account_scope="binance-main",
        quote_currency="USD",
    )
    client = StubVenueClient(
        snapshot=_snapshot(timestamp=now),
        orders=(order,),
        ledger_batches=(_ledger_batch(now), _ledger_batch(now, cursor="cursor-2")),
    )
    state = AggregatorState(risk_group="crypto-main")
    ledger = FillLedger(tmp_path / "ledger.sqlite3", "binance-main", "USD")

    reconcile_once(
        client,
        _default_config(),
        [retired],
        state,
        {},
        tmp_path,
        now_utc=now,
        clock=lambda: now,
        ledger=ledger,
    )
    assert state.residual_strategy_ids == {retired.id}
    assert state.open_order_count == 1

    client._orders = ()
    reconcile_once(
        client,
        _default_config(),
        [retired],
        state,
        {},
        tmp_path,
        now_utc=now,
        clock=lambda: now,
        ledger=ledger,
    )
    assert state.residual_strategy_ids == set()
    assert state.open_order_count == 0


def test_failed_reconciliation_cannot_clear_residual_strategy(tmp_path: Path) -> None:
    entry = _make_entry("binance.swap.x.btcusdt.5m.v1", enabled=False)
    now = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    position = VenuePosition(
        strategy_id=entry.id,
        symbol="BTCUSDT",
        side="long",
        size=Decimal("1"),
        entry_price=Decimal("100"),
        unrealized_pnl=Decimal("-1"),
        account_scope="binance-main",
        quote_currency="USD",
    )
    client = StubVenueClient(
        snapshot=_snapshot(timestamp=now),
        positions=(position,),
        ledger_batches=(_ledger_batch(now),),
    )
    state = AggregatorState(risk_group="crypto-main")
    ledger = FillLedger(tmp_path / "ledger.sqlite3", "binance-main", "USD")
    reconcile_once(
        client,
        _default_config(),
        [entry],
        state,
        {},
        tmp_path,
        now_utc=now,
        clock=lambda: now,
        ledger=ledger,
    )
    assert state.residual_strategy_ids == {entry.id}

    client._raise_count = 100
    reconcile_once(
        client,
        _default_config(),
        [entry],
        state,
        {},
        tmp_path,
        now_utc=now,
        clock=lambda: now,
        ledger=ledger,
    )
    assert state.residual_strategy_ids == {entry.id}
    assert state.group_gross_exposure == Decimal("100")


def test_ledger_events_after_position_cut_do_not_double_count_unrealized(
    tmp_path: Path,
) -> None:
    sid = "binance.swap.x.btcusdt.5m.v1"
    position_cut = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    ledger_cut = position_cut + timedelta(minutes=1)
    pre_cut_loss = VenueFill(
        account_scope="binance-main",
        strategy_id=sid,
        symbol="ETHUSDT",
        order_id="loss-order",
        fill_id="loss-fill",
        occurred_at=position_cut - timedelta(seconds=1),
        side="sell",
        quantity=Decimal("1"),
        execution_price=Decimal("100"),
        gross_realized_pnl=Decimal("-150"),
        commission=Decimal("0"),
        fees=Decimal("0"),
        quote_currency="USD",
    )
    post_cut_close = replace(
        pre_cut_loss,
        symbol="BTCUSDT",
        order_id="close-order",
        fill_id="close-fill",
        occurred_at=ledger_cut,
        gross_realized_pnl=Decimal("100"),
    )
    position = VenuePosition(
        strategy_id=sid,
        symbol="BTCUSDT",
        side="long",
        size=Decimal("1"),
        entry_price=Decimal("1000"),
        unrealized_pnl=Decimal("100"),
        account_scope="binance-main",
        quote_currency="USD",
    )
    client = StubVenueClient(
        snapshot=_snapshot(timestamp=position_cut),
        positions=(position,),
        ledger_batches=(
            _ledger_batch(
                ledger_cut,
                fills=(pre_cut_loss, post_cut_close),
            ),
        ),
    )
    config = replace(_default_config(), accounting_cut_max_skew_s=60.0)
    state = AggregatorState(risk_group=config.risk_group)
    ledger = FillLedger(tmp_path / "ledger.sqlite3", "binance-main", "USD")

    reconcile_once(
        client,
        config,
        [_make_entry(sid)],
        state,
        {},
        tmp_path,
        now_utc=ledger_cut,
        clock=lambda: ledger_cut,
        ledger=ledger,
    )

    assert state.fail_closed is False
    assert state.daily_realized_pnl == Decimal("-150")
    assert state.pending_daily_realized_pnl == Decimal("100")
    assert state.daily_unrealized_pnl == Decimal("100")
    assert state.group_daily_pnl == Decimal("-50")
    assert ledger.realized_pnl_for_day(position_cut.date()) == Decimal("-50")
    payload = state_to_dict(state, config, now_utc=ledger_cut)
    assert payload["pending_daily_realized_pnl"] == "100"
    assert payload["metric_metadata"]["pending_daily_realized_pnl"]["source"] == "ledger"

    reconcile_once(
        StubVenueClient(
            snapshot=_snapshot(timestamp=ledger_cut),
            ledger_batches=(_ledger_batch(ledger_cut, cursor="cursor-2"),),
        ),
        config,
        [_make_entry(sid)],
        state,
        {},
        tmp_path,
        now_utc=ledger_cut,
        clock=lambda: ledger_cut,
        ledger=ledger,
    )

    assert state.daily_realized_pnl == Decimal("-50")
    assert state.pending_daily_realized_pnl == Decimal("0")
    assert state.daily_unrealized_pnl == Decimal("0")
    assert state.group_daily_pnl == Decimal("-50")


def test_enforcement_cut_is_min_of_position_and_ledger_cuts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sid = "binance.swap.x.btcusdt.5m.v1"
    ledger_cut = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    position_cut = ledger_cut + timedelta(seconds=30)
    fill = VenueFill(
        account_scope="binance-main",
        strategy_id=sid,
        symbol="BTCUSDT",
        order_id="loss-order",
        fill_id="loss-fill",
        occurred_at=ledger_cut,
        side="sell",
        quantity=Decimal("1"),
        execution_price=Decimal("100"),
        gross_realized_pnl=Decimal("-50"),
        commission=Decimal("0"),
        fees=Decimal("0"),
        quote_currency="USD",
    )
    position = VenuePosition(
        strategy_id=sid,
        symbol="BTCUSDT",
        side="long",
        size=Decimal("1"),
        entry_price=Decimal("1000"),
        unrealized_pnl=Decimal("10"),
        account_scope="binance-main",
        quote_currency="USD",
    )
    ledger = FillLedger(tmp_path / "ledger.sqlite3", "binance-main", "USD")
    original_total = ledger.realized_pnl_for_day
    requested_cuts: list[datetime | None] = []

    def tracked_total(
        utc_day: date,
        *,
        through: datetime | None = None,
    ) -> Decimal:
        requested_cuts.append(through)
        return original_total(utc_day, through=through)

    monkeypatch.setattr(ledger, "realized_pnl_for_day", tracked_total)
    config = replace(_default_config(), accounting_cut_max_skew_s=60.0)
    state = AggregatorState(risk_group=config.risk_group)

    reconcile_once(
        StubVenueClient(
            snapshot=_snapshot(timestamp=position_cut),
            positions=(position,),
            ledger_batches=(_ledger_batch(ledger_cut, fills=(fill,)),),
            positions_as_of_cut=ledger_cut,
        ),
        config,
        [_make_entry(sid)],
        state,
        {},
        tmp_path,
        now_utc=position_cut,
        clock=lambda: position_cut,
        ledger=ledger,
    )

    assert state.fail_closed is False
    assert requested_cuts == [ledger_cut, None]
    assert state.daily_realized_pnl == Decimal("-50")
    assert state.daily_unrealized_pnl == Decimal("10")
    assert state.group_daily_pnl == Decimal("-40")
    payload = state_to_dict(state, config, now_utc=position_cut)
    expected_cut = ledger_cut.isoformat()
    assert payload["metric_metadata"]["daily_realized_pnl"]["as_of_ts"] == expected_cut
    assert (
        payload["metric_metadata"]["daily_unrealized_pnl"]["as_of_ts"]
        == position_cut.isoformat()
    )
    assert payload["metric_metadata"]["group_daily_pnl"]["as_of_ts"] == expected_cut
    assert (
        payload["metric_metadata"]["group_gross_exposure"]["as_of_ts"]
        == position_cut.isoformat()
    )


def test_accounting_is_independent_of_global_decimal_context(tmp_path: Path) -> None:
    sid = "binance.swap.x.btcusdt.5m.v1"
    now = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    positions = (
        VenuePosition(
            strategy_id=sid,
            symbol="BTCUSDT",
            side="long",
            size=Decimal("123456.789"),
            entry_price=Decimal("10"),
            unrealized_pnl=Decimal("1000000.01"),
            account_scope="binance-main",
            quote_currency="USD",
        ),
        VenuePosition(
            strategy_id=sid,
            symbol="ETHUSDT",
            side="short",
            size=Decimal("1"),
            entry_price=Decimal("1"),
            unrealized_pnl=Decimal("-1000000.00"),
            account_scope="binance-main",
            quote_currency="USD",
        ),
    )

    def reconcile_with_precision(path: Path, precision: int) -> AggregatorState:
        state = AggregatorState(risk_group="crypto-main")
        ledger = FillLedger(path, "binance-main", "USD")
        with localcontext() as ambient_context:
            ambient_context.prec = precision
            reconcile_once(
                StubVenueClient(
                    snapshot=_snapshot(timestamp=now),
                    positions=positions,
                ),
                _default_config(),
                [_make_entry(sid)],
                state,
                {},
                tmp_path,
                now_utc=now,
                clock=lambda: now,
                ledger=ledger,
            )
        return state

    reference = reconcile_with_precision(tmp_path / "reference.sqlite3", 64)
    constrained = reconcile_with_precision(tmp_path / "constrained.sqlite3", 6)

    assert constrained.fail_closed is False
    assert constrained.group_net_exposure == Decimal("1234566.890")
    assert constrained.group_gross_exposure == Decimal("1234568.890")
    assert constrained.daily_unrealized_pnl == Decimal("0.01")
    assert constrained.group_daily_pnl == Decimal("0.01")
    assert (
        constrained.group_net_exposure,
        constrained.group_gross_exposure,
        constrained.daily_unrealized_pnl,
        constrained.group_daily_pnl,
    ) == (
        reference.group_net_exposure,
        reference.group_gross_exposure,
        reference.daily_unrealized_pnl,
        reference.group_daily_pnl,
    )
