"""Tests for risk aggregator persistence."""

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
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
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

def test_checkpoint_save_load_roundtrip(tmp_path: Path) -> None:
    """Persist authoritative cached values and control state with a ledger binding."""
    ckpt_path = tmp_path / "checkpoint.json"
    ledger = FillLedger(tmp_path / "ledger.sqlite3", "binance-main", "USD")

    cut = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    ledger_as_of = cut + timedelta(hours=1)
    realized_fill = VenueFill(
        account_scope="binance-main",
        strategy_id="strat-a",
        symbol="BTCUSDT",
        order_id="order-realized",
        fill_id="fill-realized",
        occurred_at=cut,
        side="sell",
        quantity=Decimal("1"),
        execution_price=Decimal("100"),
        gross_realized_pnl=Decimal("123.45"),
        commission=Decimal("0"),
        fees=Decimal("0"),
        quote_currency="USD",
    )
    pending_fill = replace(
        realized_fill,
        order_id="order-pending",
        fill_id="fill-pending",
        occurred_at=cut + timedelta(minutes=30),
        gross_realized_pnl=Decimal("7.89"),
    )
    ledger.ingest_batch(
        _ledger_batch(
            ledger_as_of,
            fills=(realized_fill, pending_fill),
        ),
        {"strat-a"},
    )

    # Build state with ledger-consistent meaningful values.
    state1 = AggregatorState(risk_group="crypto-main")
    state1.current_utc_date = date(2026, 6, 11)
    state1.daily_realized_pnl = Decimal("123.45")
    state1.pending_daily_realized_pnl = Decimal("7.89")
    state1.group_daily_pnl = Decimal("123.45")
    state1.latest_unrealized[("strat-a", "BTCUSDT")] = Decimal("50")
    state1.latest_unrealized[("strat-b", "ETHUSDT")] = Decimal("-20")
    state1.start_of_day_equity = Decimal("10000")
    state1.high_water_mark = Decimal("10500")
    state1.consecutive_failures = 2
    state1.fail_closed = True
    state1.positions_as_of_ts = cut
    state1.ledger_as_of_ts = ledger_as_of
    state1.checkpoint_ledger_cursor = ledger.binding.cursor
    state1.checkpoint_ledger_generation = ledger.binding.generation

    log_statuses1: dict[str, StrategyLogStatus] = {
        "strat-a": StrategyLogStatus(strategy_id="strat-a", log_offset=4096),
        "strat-b": StrategyLogStatus(strategy_id="strat-b", log_offset=8192),
    }
    save_checkpoint(ckpt_path, state1, log_statuses1, ledger=ledger)
    assert ckpt_path.exists()

    # Load into fresh state.
    state2 = AggregatorState(risk_group="crypto-main")
    log_statuses2: dict[str, StrategyLogStatus] = {}
    loaded = load_checkpoint(
        ckpt_path,
        state2,
        log_statuses2,
        ledger=ledger,
        config=_default_config(),
    )

    assert loaded is True
    assert state2.current_utc_date == date(2026, 6, 11)
    assert state2.daily_realized_pnl == Decimal("123.45")
    assert state2.pending_daily_realized_pnl == Decimal("7.89")
    assert state2.latest_unrealized[("strat-a", "BTCUSDT")] == Decimal("50")
    assert state2.latest_unrealized[("strat-b", "ETHUSDT")] == Decimal("-20")
    assert state2.start_of_day_equity == Decimal("10000")
    assert state2.high_water_mark == Decimal("10500")
    assert state2.consecutive_failures == 2
    assert state2.fail_closed is True
    assert log_statuses2["strat-a"].log_offset == 4096
    assert log_statuses2["strat-b"].log_offset == 8192


@pytest.mark.parametrize("damage", ["realized", "pending", "ledger_timestamp"])
def test_checkpoint_pnl_inconsistent_with_ledger_is_rejected(
    tmp_path: Path,
    damage: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    checkpoint_path = tmp_path / "checkpoint.json"
    ledger = FillLedger(tmp_path / "ledger.sqlite3", "binance-main", "USD")
    cut = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
    later = cut + timedelta(minutes=30)
    first = VenueFill(
        account_scope="binance-main",
        strategy_id="strat-a",
        symbol="BTCUSDT",
        order_id="order-1",
        fill_id="fill-1",
        occurred_at=cut,
        side="sell",
        quantity=Decimal("1"),
        execution_price=Decimal("100"),
        gross_realized_pnl=Decimal("10"),
        commission=Decimal("0"),
        fees=Decimal("0"),
        quote_currency="USD",
    )
    second = replace(
        first,
        order_id="order-2",
        fill_id="fill-2",
        occurred_at=later,
        gross_realized_pnl=Decimal("2"),
    )
    ledger.ingest_batch(
        _ledger_batch(later, fills=(first, second)),
        {"strat-a"},
    )
    state = AggregatorState(risk_group="crypto-main")
    state.current_utc_date = cut.date()
    state.daily_realized_pnl = Decimal("10")
    state.pending_daily_realized_pnl = Decimal("2")
    state.group_daily_pnl = Decimal("10")
    state.positions_as_of_ts = cut
    state.ledger_as_of_ts = later
    state.checkpoint_ledger_cursor = ledger.binding.cursor
    state.checkpoint_ledger_generation = ledger.binding.generation
    assert save_checkpoint(checkpoint_path, state, {}, ledger=ledger) is True

    pristine = AggregatorState(risk_group="crypto-main")
    assert load_checkpoint(
        checkpoint_path, pristine, {}, ledger=ledger, config=_default_config(),
    ) is True
    assert pristine.current_utc_date == cut.date()
    assert pristine.daily_realized_pnl == Decimal("10")
    assert pristine.pending_daily_realized_pnl == Decimal("2")
    assert pristine.group_daily_pnl == Decimal("10")
    assert pristine.ledger_as_of_ts == later

    payload = json.loads(checkpoint_path.read_text())
    if damage == "realized":
        payload["daily_realized_pnl"] = "11"
        payload["group_daily_pnl"] = "11"
        reason = "checkpoint realized PnL does not match bound ledger"
    elif damage == "pending":
        payload["pending_daily_realized_pnl"] = "3"
        reason = "checkpoint pending PnL does not match bound ledger"
    else:
        payload["ledger_as_of_ts"] = (later - timedelta(seconds=1)).isoformat()
        reason = "checkpoint ledger timestamp does not match ledger metadata"
    checkpoint_path.write_text(json.dumps(payload))

    caplog.clear()
    restored = AggregatorState(risk_group="crypto-main")
    assert load_checkpoint(
        checkpoint_path,
        restored,
        {},
        ledger=ledger,
        config=_default_config(),
    ) is False
    assert caplog.messages == [f"checkpoint parse error, starting fresh: {reason}"]


@pytest.mark.parametrize("flag", ["soft_cap", "hard_cap", "margin_emergency"])
def test_checkpoint_cap_flags_inconsistent_with_pnl_are_rejected(
    tmp_path: Path,
    flag: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    checkpoint_path = tmp_path / "checkpoint.json"
    ledger = FillLedger(tmp_path / "ledger.sqlite3", "binance-main", "USD")
    cut = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
    # A soft-only loss keeps soft_cap=False from tripping the independent
    # hard_cap-implies-soft_cap invariant before semantic cap validation.
    loss = Decimal("-400") if flag == "soft_cap" else Decimal("-600")
    fill = VenueFill(
        account_scope="binance-main",
        strategy_id="strat-a",
        symbol="BTCUSDT",
        order_id="loss-order",
        fill_id="loss-fill",
        occurred_at=cut,
        side="sell",
        quantity=Decimal("1"),
        execution_price=Decimal("100"),
        gross_realized_pnl=loss,
        commission=Decimal("0"),
        fees=Decimal("0"),
        quote_currency="USD",
    )
    ledger.ingest_batch(_ledger_batch(cut, fills=(fill,)), {"strat-a"})
    state = AggregatorState(risk_group="crypto-main")
    state.current_utc_date = cut.date()
    state.last_snapshot = _snapshot(
        balance=Decimal("10000"),
        margin_ratio=Decimal("0.98"),
        timestamp=cut,
    )
    state.daily_realized_pnl = loss
    state.group_daily_pnl = loss
    state.soft_cap = True
    state.hard_cap = flag != "soft_cap"
    state.margin_emergency = True
    state.positions_as_of_ts = cut
    state.ledger_as_of_ts = cut
    state.checkpoint_ledger_cursor = ledger.binding.cursor
    state.checkpoint_ledger_generation = ledger.binding.generation
    assert save_checkpoint(checkpoint_path, state, {}, ledger=ledger) is True

    pristine = AggregatorState(risk_group="crypto-main")
    assert load_checkpoint(
        checkpoint_path, pristine, {}, ledger=ledger, config=_default_config(),
    ) is True
    assert pristine.current_utc_date == cut.date()
    assert pristine.daily_realized_pnl == loss
    assert pristine.pending_daily_realized_pnl == Decimal("0")
    assert pristine.group_daily_pnl == loss
    assert pristine.soft_cap is True
    assert pristine.hard_cap is (flag != "soft_cap")
    assert pristine.margin_emergency is True

    payload = json.loads(checkpoint_path.read_text())
    original = payload.copy()
    payload[flag] = False
    assert {key for key in payload if payload[key] != original[key]} == {flag}
    checkpoint_path.write_text(json.dumps(payload))

    caplog.clear()
    assert load_checkpoint(
        checkpoint_path,
        AggregatorState(risk_group="crypto-main"),
        {},
        ledger=ledger,
        config=_default_config(),
    ) is False
    assert caplog.messages == [
        "checkpoint parse error, starting fresh: checkpoint cap flags are "
        "inconsistent with cached PnL, snapshot, and current configuration"
    ]


def test_null_day_checkpoint_with_reconciled_ledger_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Clearing a reconciled loss must refuse startup before the first venue miss."""
    config = _default_config()
    entry = _make_entry()
    registry_path = _write_registry(tmp_path, [entry])
    now = datetime.now(UTC)
    ledger = FillLedger(
        _ledger_file(tmp_path, config.risk_group),
        config.account_scope,
        config.quote_currency,
    )
    loss = VenueFill(
        account_scope=config.account_scope,
        strategy_id=entry.id,
        symbol=entry.symbol,
        order_id="loss-order",
        fill_id="loss-fill",
        occurred_at=now,
        side="sell",
        quantity=Decimal("1"),
        execution_price=Decimal("100"),
        gross_realized_pnl=Decimal("-600"),
        commission=Decimal("0"),
        fees=Decimal("0"),
        quote_currency=config.quote_currency,
    )
    state = AggregatorState(risk_group=config.risk_group)
    reconcile_once(
        StubVenueClient(
            snapshot=_snapshot(equity=Decimal("9400"), timestamp=now),
            ledger_batches=(_ledger_batch(now, fills=(loss,)),),
        ),
        config, [entry], state, {}, tmp_path,
        now_utc=now, clock=lambda: now, ledger=ledger,
    )
    checkpoint_path = _checkpoint_file(tmp_path, config.risk_group)
    assert save_checkpoint(checkpoint_path, state, {}, ledger=ledger) is True
    restored = AggregatorState(risk_group=config.risk_group)
    assert load_checkpoint(
        checkpoint_path, restored, {}, ledger=ledger, config=config,
    ) is True
    assert restored.daily_realized_pnl == Decimal("-600")
    assert restored.soft_cap is True
    assert restored.hard_cap is True
    state_path = _state_file(tmp_path, config.risk_group)
    publish_state(state_path, restored, config)
    assert json.loads(state_path.read_text())["healthy"] is True

    payload = json.loads(checkpoint_path.read_text())
    payload.update(
        current_utc_date=None,
        daily_realized_pnl="0",
        pending_daily_realized_pnl="0",
        daily_unrealized_pnl="0",
        group_daily_pnl="0",
        soft_cap=False,
        hard_cap=False,
        margin_emergency=False,
    )
    damaged_checkpoint = json.dumps(payload)
    checkpoint_path.write_text(damaged_checkpoint)
    publications: list[tuple[bool, bool]] = []

    def capture_publication(
        path: Path, state: AggregatorState, config: AggregatorConfig,
    ) -> None:
        publish_state(path, state, config)
        published = json.loads(path.read_text())
        publications.append((published["healthy"], published["fail_closed"]))

    monkeypatch.setattr(aggregator_module, "publish_state", capture_publication)
    failing_client = StubVenueClient(snapshot=_snapshot(timestamp=now), raise_count=1)
    result = run_forever(
        config, registry_path, tmp_path, failing_client, max_iterations=1,
    )

    # Inspect every publication so the shutdown's fail-closed write cannot mask
    # a healthy, cap-free state emitted after accepting the damaged checkpoint.
    assert publications == [(False, True)]
    assert result == int(ExitCode.INVARIANT_VIOLATION)
    assert failing_client.call_count == 0
    published = json.loads(state_path.read_text())
    assert published["healthy"] is False
    assert published["fail_closed"] is True
    assert published["metric_metadata"]["group_daily_pnl"]["source"] == "none"
    assert ledger.realized_pnl_for_day(now.date()) == Decimal("-600")
    assert checkpoint_path.read_text() == damaged_checkpoint


@pytest.mark.parametrize("case", [
    "bootstrap", "failed_bootstrap", "empty_reconciled", "fill_row", "cash_row",
    "ledger_ahead", "checkpoint_ahead", "realized", "pending", "unrealized",
    "soft_cap", "hard_cap", "margin_emergency",
])
def test_null_day_checkpoint_is_accepted_only_for_bootstrap(
    tmp_path: Path,
    case: str,
) -> None:
    """Only an initial binding with zero cached PnL and no caps can omit its day."""
    config = _default_config()
    now = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
    ledger = FillLedger(tmp_path / "ledger.sqlite3", "binance-main", "USD")
    state = AggregatorState(risk_group=config.risk_group)
    batch = _ledger_batch(now)
    if case == "fill_row":
        batch = replace(batch, fills=(VenueFill(
            account_scope=config.account_scope,
            strategy_id="strat-a",
            symbol="BTCUSDT",
            order_id="zero-pnl-order",
            fill_id="zero-pnl-fill",
            occurred_at=now - timedelta(days=1),
            side="buy",
            quantity=Decimal("1"),
            execution_price=Decimal("100"),
            gross_realized_pnl=Decimal("0"),
            commission=Decimal("0"),
            fees=Decimal("0"),
            quote_currency=config.quote_currency,
        ),))
    elif case == "cash_row":
        batch = replace(batch, cash_events=(VenueCashEvent(
            account_scope=config.account_scope,
            event_id="deposit",
            strategy_id=None,
            symbol=None,
            occurred_at=now - timedelta(days=1),
            kind="deposit",
            cash_delta=Decimal("100"),
            realized_pnl_delta=Decimal("0"),
            quote_currency=config.quote_currency,
        ),))
    if case in {"empty_reconciled", "fill_row", "cash_row"}:
        ledger.ingest_batch(batch, {"strat-a"})
        state.checkpoint_ledger_generation = ledger.binding.generation
        state.checkpoint_ledger_cursor = ledger.binding.cursor
        state.ledger_as_of_ts = ledger.binding.as_of
    elif case == "failed_bootstrap":
        state.fail_closed = True
        state.consecutive_failures = 1
    elif case in {"realized", "pending", "unrealized"}:
        field = {
            "realized": "daily_realized_pnl",
            "pending": "pending_daily_realized_pnl",
            "unrealized": "daily_unrealized_pnl",
        }[case]
        setattr(state, field, Decimal("1"))
        if case != "pending":
            state.group_daily_pnl = Decimal("1")
    elif case in {"soft_cap", "hard_cap", "margin_emergency"}:
        if case == "margin_emergency":
            state.last_snapshot = _snapshot(margin_ratio=Decimal("0.98"), timestamp=now)
        else:
            state.last_snapshot = _snapshot(timestamp=now)
            state.daily_unrealized_pnl = Decimal("-400" if case == "soft_cap" else "-600")
            state.group_daily_pnl = state.daily_unrealized_pnl
        determine_signals(state, config)
        assert getattr(state, case) is True
    checkpoint_path = tmp_path / "checkpoint.json"
    assert save_checkpoint(checkpoint_path, state, {}, ledger=ledger) is True
    if case == "ledger_ahead":
        ledger.ingest_batch(batch, set())
    elif case == "checkpoint_ahead":
        payload = json.loads(checkpoint_path.read_text())
        payload.update(ledger_generation=1, ledger_cursor="cursor-1")
        checkpoint_path.write_text(json.dumps(payload))

    target = AggregatorState(risk_group=config.risk_group, fail_closed=True)
    before = replace(target)
    statuses = {"sentinel": StrategyLogStatus(strategy_id="sentinel", log_offset=7)}
    before_statuses = statuses.copy()
    loaded = load_checkpoint(checkpoint_path, target, statuses, ledger=ledger, config=config)
    assert loaded is (case in {"bootstrap", "failed_bootstrap"})
    if loaded:
        assert target.current_utc_date is None
        assert target.checkpoint_ledger_generation == 0
        assert target.checkpoint_ledger_cursor is None
        assert target.daily_realized_pnl == target.pending_daily_realized_pnl == Decimal("0")
        assert target.daily_unrealized_pnl == target.group_daily_pnl == Decimal("0")
        assert (target.soft_cap, target.hard_cap, target.margin_emergency) == (False, False, False)
        assert state_to_dict(target, config, now_utc=now)["healthy"] is False
    else:
        assert target == before
        assert statuses == before_statuses


def test_checkpoint_missing_starts_fresh(tmp_path: Path) -> None:
    """Missing checkpoint file returns False and leaves state untouched."""
    ckpt_path = tmp_path / "nonexistent.json"
    state = AggregatorState(risk_group="g")
    log_statuses: dict[str, StrategyLogStatus] = {}
    ledger = FillLedger(tmp_path / "ledger.sqlite3", "a", "USD")
    assert load_checkpoint(
        ckpt_path,
        state,
        log_statuses,
        ledger=ledger,
        config=_default_config("g"),
    ) is False
    assert state.daily_realized_pnl == Decimal("0")


def test_checkpoint_corrupt_starts_fresh(tmp_path: Path) -> None:
    """Corrupt checkpoint file returns False with a WARNING."""
    ckpt_path = tmp_path / "checkpoint.json"
    ckpt_path.write_text("not json at all")
    state = AggregatorState(risk_group="g")
    log_statuses: dict[str, StrategyLogStatus] = {}
    ledger = FillLedger(tmp_path / "ledger.sqlite3", "a", "USD")
    assert load_checkpoint(
        ckpt_path,
        state,
        log_statuses,
        ledger=ledger,
        config=_default_config("g"),
    ) is False


def test_v1_checkpoint_does_not_restore_log_derived_pnl(tmp_path: Path) -> None:
    checkpoint = tmp_path / "checkpoint.json"
    checkpoint.write_text(
        json.dumps(
            {
                "current_utc_date": "2026-09-05",
                "daily_realized_pnl": "1234",
                "latest_unrealized": {"x\\u0000BTCUSDT": "567"},
                "start_of_day_equity": "10000",
                "high_water_mark": "11000",
                "consecutive_failures": 2,
                "fail_closed": True,
                "log_offsets": {"x": 900},
            }
        )
    )
    state = AggregatorState(risk_group="crypto-main")
    statuses: dict[str, StrategyLogStatus] = {}
    ledger = FillLedger(tmp_path / "ledger.sqlite3", "binance-main", "USD")

    assert load_checkpoint(
        checkpoint,
        state,
        statuses,
        ledger=ledger,
        config=_default_config(),
    ) is True
    assert state.current_utc_date == date(2026, 9, 5)
    assert state.daily_realized_pnl == Decimal("0")
    assert state.latest_unrealized == {}
    assert state.start_of_day_equity == Decimal("10000")
    assert state.high_water_mark == Decimal("11000")
    assert statuses["x"].log_offset == 0


@pytest.mark.parametrize(
    "damage",
    ["missing_financial_field", "string_boolean", "cap_invariant"],
)
def test_malformed_schema_v3_checkpoint_is_rejected(
    tmp_path: Path,
    damage: str,
) -> None:
    checkpoint_path = tmp_path / "checkpoint.json"
    ledger = FillLedger(tmp_path / "ledger.sqlite3", "binance-main", "USD")
    original = AggregatorState(risk_group="crypto-main")
    assert save_checkpoint(checkpoint_path, original, {}, ledger=ledger) is True
    payload = json.loads(checkpoint_path.read_text())
    if damage == "missing_financial_field":
        del payload["group_daily_pnl"]
    elif damage == "string_boolean":
        payload["fail_closed"] = "false"
    else:
        payload["soft_cap"] = False
        payload["hard_cap"] = True
    checkpoint_path.write_text(json.dumps(payload))

    restored = AggregatorState(risk_group="crypto-main")

    assert load_checkpoint(
        checkpoint_path,
        restored,
        {},
        ledger=ledger,
        config=_default_config(),
    ) is False
    assert restored.drawdown_baseline_verified is False
    assert restored.last_success_ts is None


def test_crash_between_ledger_commit_and_checkpoint_fails_closed_without_lowering_hwm(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    ledger = FillLedger(tmp_path / "ledger.sqlite3", "binance-main", "USD")
    ledger.ingest_batch(_ledger_batch(now, cursor="cursor-1"), set())
    original = AggregatorState(risk_group="crypto-main")
    original.current_utc_date = now.date()
    original.high_water_mark = Decimal("12000")
    original.start_of_day_equity = Decimal("11000")
    original.positions_as_of_ts = now
    original.ledger_as_of_ts = now
    original.checkpoint_ledger_cursor = ledger.binding.cursor
    original.checkpoint_ledger_generation = ledger.binding.generation
    save_checkpoint(tmp_path / "checkpoint.json", original, {}, ledger=ledger)

    # This commit survives, while the checkpoint write is assumed to have crashed.
    ledger.ingest_batch(
        _ledger_batch(now + timedelta(seconds=1), cursor="cursor-2"), set()
    )
    restored = AggregatorState(risk_group="crypto-main")
    assert load_checkpoint(
        tmp_path / "checkpoint.json",
        restored,
        {},
        ledger=ledger,
        config=_default_config(),
    ) is True
    assert restored.fail_closed is True
    assert restored.drawdown_baseline_verified is False
    assert restored.high_water_mark == Decimal("12000")

    client = StubVenueClient(
        snapshot=_snapshot(equity=Decimal("11500"), timestamp=now + timedelta(seconds=2)),
        ledger_batches=(
            _ledger_batch(now + timedelta(seconds=2), cursor="cursor-3"),
        ),
    )
    reconcile_once(
        client,
        _default_config(),
        [],
        restored,
        {},
        tmp_path,
        now_utc=now + timedelta(seconds=2),
        clock=lambda: now + timedelta(seconds=2),
        ledger=ledger,
    )
    assert restored.drawdown_baseline_verified is True
    assert restored.fail_closed is False
    assert restored.high_water_mark == Decimal("12000")


def test_restart_then_venue_failure_retains_cached_state(tmp_path: Path) -> None:
    now = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    sid = "binance.swap.x.btcusdt.5m.v1"
    ledger = FillLedger(tmp_path / "ledger.sqlite3", "binance-main", "USD")
    loss_fill = VenueFill(
        account_scope="binance-main",
        strategy_id=sid,
        symbol="BTCUSDT",
        order_id="loss-order",
        fill_id="loss-fill",
        occurred_at=now,
        side="sell",
        quantity=Decimal("1"),
        execution_price=Decimal("100"),
        gross_realized_pnl=Decimal("-500"),
        commission=Decimal("0"),
        fees=Decimal("0"),
        quote_currency="USD",
    )
    ledger.ingest_batch(
        _ledger_batch(now, cursor="cursor-1", fills=(loss_fill,)),
        {sid},
    )
    original = AggregatorState(risk_group="crypto-main")
    original.current_utc_date = now.date()
    original.last_success_ts = now
    original.last_snapshot = _snapshot(
        balance=Decimal("10000"),
        equity=Decimal("9500"),
        margin_ratio=Decimal("0.5"),
        timestamp=now,
    )
    original.group_net_exposure = Decimal("-250")
    original.group_gross_exposure = Decimal("1250")
    original.group_daily_pnl = Decimal("-550")
    original.daily_realized_pnl = Decimal("-500")
    original.daily_unrealized_pnl = Decimal("-50")
    original.open_position_count = 2
    original.open_order_count = 3
    original.start_of_day_equity = Decimal("10000")
    original.high_water_mark = Decimal("11000")
    original.drawdown_sod_pct = Decimal("-5")
    original.drawdown_hwm_pct = Decimal("-13.63636363636363636363636364")
    original.soft_cap = True
    original.hard_cap = True
    original.venue_as_of_ts = now
    original.positions_as_of_ts = now
    original.orders_as_of_ts = now
    original.ledger_as_of_ts = now
    original.checkpoint_ledger_cursor = ledger.binding.cursor
    original.checkpoint_ledger_generation = ledger.binding.generation
    save_checkpoint(tmp_path / "checkpoint.json", original, {}, ledger=ledger)

    restored = AggregatorState(risk_group="crypto-main")
    assert load_checkpoint(
        tmp_path / "checkpoint.json",
        restored,
        {},
        ledger=ledger,
        config=_default_config(),
    ) is True
    client = StubVenueClient(snapshot=_snapshot(timestamp=now), raise_count=100)
    reconcile_once(
        client,
        _default_config(),
        [],
        restored,
        {},
        tmp_path,
        now_utc=now + timedelta(seconds=1),
        clock=lambda: now + timedelta(seconds=1),
        ledger=ledger,
    )

    assert restored.group_net_exposure == Decimal("-250")
    assert restored.group_gross_exposure == Decimal("1250")
    assert restored.group_daily_pnl == Decimal("-550")
    assert restored.daily_realized_pnl == Decimal("-500")
    assert restored.daily_unrealized_pnl == Decimal("-50")
    assert restored.open_position_count == 2
    assert restored.open_order_count == 3
    assert restored.last_snapshot is not None
    assert restored.last_snapshot.equity == Decimal("9500")
    assert restored.high_water_mark == Decimal("11000")
    assert restored.soft_cap is True
    assert restored.hard_cap is True
    assert restored.consecutive_failures == 1


def test_post_commit_ledger_read_failure_does_not_bind_checkpoint_to_new_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    ledger = FillLedger(tmp_path / "ledger.sqlite3", "binance-main", "USD")
    ledger.ingest_batch(_ledger_batch(now, cursor="cursor-1"), set())
    state = AggregatorState(risk_group="crypto-main")
    state.current_utc_date = now.date()
    state.high_water_mark = Decimal("12000")
    state.start_of_day_equity = Decimal("11000")
    state.drawdown_baseline_verified = True
    state.positions_as_of_ts = now
    state.ledger_as_of_ts = now
    state.checkpoint_ledger_cursor = ledger.binding.cursor
    state.checkpoint_ledger_generation = ledger.binding.generation
    checkpoint_path = tmp_path / "checkpoint.json"
    save_checkpoint(checkpoint_path, state, {}, ledger=ledger)
    original_checkpoint = checkpoint_path.read_bytes()

    def failed_daily_total(
        utc_day: date,
        *,
        through: datetime | None = None,
    ) -> Decimal:
        raise LedgerError(f"simulated total read failure for {utc_day}")

    monkeypatch.setattr(ledger, "realized_pnl_for_day", failed_daily_total)
    reconcile_once(
        StubVenueClient(
            snapshot=_snapshot(timestamp=now + timedelta(seconds=1)),
            ledger_batches=(
                _ledger_batch(now + timedelta(seconds=1), cursor="cursor-2"),
            ),
        ),
        _default_config(),
        [],
        state,
        {},
        tmp_path,
        now_utc=now + timedelta(seconds=1),
        clock=lambda: now + timedelta(seconds=1),
        ledger=ledger,
    )

    assert ledger.binding.generation == 2
    assert state.fail_closed is True
    save_checkpoint(checkpoint_path, state, {}, ledger=ledger)
    assert checkpoint_path.read_bytes() == original_checkpoint

    restored = AggregatorState(risk_group="crypto-main")
    assert load_checkpoint(
        checkpoint_path,
        restored,
        {},
        ledger=ledger,
        config=_default_config(),
    ) is True
    assert restored.fail_closed is True
    assert restored.drawdown_baseline_verified is False
    assert restored.high_water_mark == Decimal("12000")


def test_checkpoint_save_refuses_when_ledger_advanced_concurrently(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    now = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    ledger = FillLedger(tmp_path / "ledger.sqlite3", "binance-main", "USD")
    ledger.ingest_batch(_ledger_batch(now, cursor="cursor-1"), set())
    state = AggregatorState(risk_group="crypto-main")
    state.current_utc_date = now.date()
    state.high_water_mark = Decimal("12000")
    state.start_of_day_equity = Decimal("11000")
    state.drawdown_baseline_verified = True
    state.checkpoint_ledger_cursor = ledger.binding.cursor
    state.checkpoint_ledger_generation = ledger.binding.generation
    checkpoint_path = tmp_path / "checkpoint.json"
    save_checkpoint(checkpoint_path, state, {}, ledger=ledger)
    original_checkpoint = checkpoint_path.read_bytes()

    ledger.ingest_batch(
        _ledger_batch(now + timedelta(seconds=1), cursor="cursor-2"), set()
    )
    caplog.set_level(logging.CRITICAL, logger="aggregator")
    save_checkpoint(checkpoint_path, state, {}, ledger=ledger)

    assert checkpoint_path.read_bytes() == original_checkpoint
    assert state.checkpoint_ledger_cursor == "cursor-1"
    assert state.checkpoint_ledger_generation == 1
    assert any(
        "ledger binding changed" in record.getMessage() for record in caplog.records
    )


def test_second_aggregator_instance_for_same_group_is_refused(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    registry_path = _write_registry(tmp_path, [])
    config = _default_config()
    client = StubVenueClient(snapshot=_snapshot())
    ledger_dir = tmp_path / "data" / "aggregator" / config.risk_group
    ledger_dir.mkdir(parents=True)
    caplog.set_level(logging.CRITICAL, logger="aggregator")

    with _exclusive_ledger_directory_lock(ledger_dir / "ledger.sqlite3"):
        result = run_forever(
            config,
            registry_path,
            tmp_path,
            client,
            stop_event=threading.Event(),
            max_iterations=0,
        )

    assert result == int(ExitCode.INVARIANT_VIOLATION)
    assert client.call_count == 0
    assert any(
        "another aggregator instance" in record.getMessage()
        for record in caplog.records
    )


def test_writer_lock_backend_selected_per_platform(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class PosixBackend:
        LOCK_EX = 1
        LOCK_NB = 2
        LOCK_UN = 4

        def __init__(self) -> None:
            self.operations: list[int] = []

        def flock(self, file_descriptor: int, operation: int) -> None:
            assert file_descriptor >= 0
            self.operations.append(operation)

    class WindowsBackend:
        LK_NBLCK = 1
        LK_UNLCK = 2

        def __init__(self) -> None:
            self.operations: list[tuple[int, int]] = []

        def locking(self, file_descriptor: int, operation: int, size: int) -> None:
            assert file_descriptor >= 0
            self.operations.append((operation, size))

    posix_backend = PosixBackend()
    windows_backend = WindowsBackend()
    monkeypatch.setattr(
        persistence_module, "_fcntl_backend", posix_backend, raising=False
    )
    monkeypatch.setattr(
        persistence_module, "_msvcrt_backend", windows_backend, raising=False
    )

    monkeypatch.setattr(persistence_module.sys, "platform", "linux")
    with _exclusive_ledger_directory_lock(tmp_path / "posix" / "ledger.sqlite3"):
        pass
    assert posix_backend.operations == [3, 4]
    assert windows_backend.operations == []

    monkeypatch.setattr(persistence_module.sys, "platform", "win32")
    with _exclusive_ledger_directory_lock(tmp_path / "windows" / "ledger.sqlite3"):
        pass
    assert windows_backend.operations == [(1, 1), (2, 1)]


def test_exposure_from_boundary_inputs_round_trips_through_checkpoint(
    tmp_path: Path,
) -> None:
    sid = "binance.swap.x.btcusdt.5m.v1"
    now = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    position = VenuePosition(
        strategy_id=sid,
        symbol="BTCUSDT",
        side="long",
        size=Decimal("1e40"),
        entry_price=Decimal("1e40"),
        unrealized_pnl=Decimal("0"),
        account_scope="binance-main",
        quote_currency="USD",
    )
    ledger = FillLedger(tmp_path / "ledger.sqlite3", "binance-main", "USD")
    state = AggregatorState(risk_group="crypto-main")

    reconcile_once(
        StubVenueClient(
            snapshot=_snapshot(balance=Decimal("1e40"), timestamp=now),
            positions=(position,),
            ledger_batches=(_ledger_batch(now),),
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

    assert state.fail_closed is False
    assert state.group_net_exposure == Decimal("1e80")
    assert state.group_gross_exposure == Decimal("1e80")
    checkpoint_path = tmp_path / "checkpoint.json"
    assert save_checkpoint(checkpoint_path, state, {}, ledger=ledger) is True

    restored = AggregatorState(risk_group="crypto-main")
    assert load_checkpoint(
        checkpoint_path,
        restored,
        {},
        ledger=ledger,
        config=_default_config(),
    ) is True
    assert restored.group_net_exposure == Decimal("1e80")
    assert restored.group_gross_exposure == Decimal("1e80")


def _write_precise_exposure_checkpoint(
    tmp_path: Path,
    exposure: Decimal,
) -> tuple[Path, FillLedger]:
    sid = "binance.swap.x.btcusdt.5m.v1"
    now = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
    position = VenuePosition(
        strategy_id=sid,
        symbol="BTCUSDT",
        side="short" if exposure.is_signed() else "long",
        size=Decimal("1"),
        entry_price=exposure.copy_abs(),
        unrealized_pnl=Decimal("0"),
        account_scope="binance-main",
        quote_currency="USD",
    )
    ledger = FillLedger(tmp_path / "ledger.sqlite3", "binance-main", "USD")
    state = AggregatorState(risk_group="crypto-main")
    reconcile_once(
        StubVenueClient(
            snapshot=_snapshot(timestamp=now),
            positions=(position,),
            ledger_batches=(_ledger_batch(now),),
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
    assert state.fail_closed is False
    assert state.group_net_exposure == exposure
    assert state.group_gross_exposure == exposure.copy_abs()
    checkpoint_path = tmp_path / "checkpoint.json"
    assert save_checkpoint(checkpoint_path, state, {}, ledger=ledger) is True
    return checkpoint_path, ledger


@pytest.mark.parametrize("precision", [6, 28, 256])
@pytest.mark.parametrize("negative", [False, True], ids=["long", "short"])
def test_checkpoint_exposure_invariant_is_exact_at_high_precision(
    tmp_path: Path,
    precision: int,
    negative: bool,
) -> None:
    exposure = Decimal("1.2345678901234567890123456789")
    if negative:
        exposure = exposure.copy_negate()
    checkpoint_path, ledger = _write_precise_exposure_checkpoint(tmp_path, exposure)
    restored = AggregatorState(risk_group="crypto-main")

    with localcontext() as ambient:
        ambient.prec = precision
        ambient.rounding = ROUND_HALF_EVEN
        assert load_checkpoint(
            checkpoint_path, restored, {}, ledger=ledger, config=_default_config()
        ) is True
        assert ambient.prec == precision
        assert not any(ambient.flags.values())

    assert restored.group_net_exposure == exposure
    assert restored.group_gross_exposure == exposure.copy_abs()
    assert restored.drawdown_baseline_verified is True
    assert restored.fail_closed is False


@pytest.mark.parametrize("precision", [6, 28, 256])
@pytest.mark.parametrize("negative", [False, True], ids=["long", "short"])
def test_checkpoint_net_exceeding_gross_is_rejected_without_rounding(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    precision: int,
    negative: bool,
) -> None:
    exposure = Decimal("1.23456123456789012345678901231")
    if negative:
        exposure = exposure.copy_negate()
    checkpoint_path, ledger = _write_precise_exposure_checkpoint(tmp_path, exposure)
    raw = json.loads(checkpoint_path.read_text())
    raw["group_gross_exposure"] = "1.23456123456789012345678901230"
    checkpoint_path.write_text(json.dumps(raw))
    restored = AggregatorState(risk_group="crypto-main", fail_closed=True)
    expected = replace(restored)
    caplog.set_level(logging.WARNING, logger="aggregator")

    with localcontext() as ambient:
        ambient.prec = precision
        ambient.rounding = ROUND_HALF_EVEN
        assert load_checkpoint(
            checkpoint_path, restored, {}, ledger=ledger, config=_default_config()
        ) is False
        assert ambient.prec == precision
        assert not any(ambient.flags.values())

    assert restored == expected
    assert "net exposure cannot exceed gross exposure" in caplog.text


def test_ledger_error_during_checkpoint_load_publishes_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry_path = _write_registry(tmp_path, [])
    config = _default_config()
    ledger_path = tmp_path / "data" / "aggregator" / config.risk_group / "ledger.sqlite3"
    ledger = FillLedger(ledger_path, config.account_scope, config.quote_currency)
    checkpoint_path = _checkpoint_file(tmp_path, config.risk_group)
    assert save_checkpoint(
        checkpoint_path,
        AggregatorState(risk_group=config.risk_group),
        {},
        ledger=ledger,
    ) is True

    def fail_binding(_ledger: FillLedger) -> object:
        raise LedgerError("simulated startup metadata failure")

    monkeypatch.setattr(FillLedger, "binding", property(fail_binding))

    result = run_forever(
        config,
        registry_path,
        tmp_path,
        StubVenueClient(snapshot=_snapshot()),
        max_iterations=0,
    )

    assert result == int(ExitCode.INVARIANT_VIOLATION)
    state_path = tmp_path / "data" / "aggregator" / config.risk_group / "state.json"
    published = json.loads(state_path.read_text())
    assert published["fail_closed"] is True
    assert published["healthy"] is False
