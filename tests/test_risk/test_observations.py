"""Tests for risk aggregator observations."""

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

def test_load_group_strategies_filters() -> None:
    doc = RegistryDocument(
        schema_version=1,
        defaults=RegistryDefaults(),
        accounts=[],
        strategies=[
            _make_entry("a.swap.x.a.5m.v1", risk_group="crypto-main"),
            _make_entry("b.swap.x.b.5m.v1", risk_group="fx-main"),  # wrong group
            _make_entry(
                "c.swap.x.c.5m.v1",
                risk_group="crypto-main",
                state=StrategyState.DRAFT,  # not active
            ),
            _make_entry(
                "d.swap.x.d.5m.v1",
                risk_group="crypto-main",
                enabled=False,  # disabled
            ),
            _make_entry("e.swap.x.e.5m.v1", risk_group="crypto-main"),
            _make_entry(
                "f.swap.x.f.5m.v1",
                risk_group="crypto-main",
                state=StrategyState.DEPRECATED,
                enabled=False,
            ),
            _make_entry(
                "g.swap.x.g.5m.v1",
                risk_group="crypto-main",
                state=StrategyState.RETIRED,
                enabled=False,
            ),
        ],
    )
    result = load_group_strategies(doc, "crypto-main")
    ids = sorted(s.id for s in result)
    assert ids == [
        "a.swap.x.a.5m.v1",
        "d.swap.x.d.5m.v1",
        "e.swap.x.e.5m.v1",
        "f.swap.x.f.5m.v1",
        "g.swap.x.g.5m.v1",
    ]


def test_log_delta_well_formed(tmp_path: Path) -> None:
    log = tmp_path / "bot.jsonl"
    lines = [
        {"event": "bot_started", "strategy_id": "x", "ts": _TS},
        {"event": "position_update", "strategy_id": "x", "ts": _TS, "unrealized_pnl": 12.5},
    ]
    log.write_text("\n".join(json.dumps(le) for le in lines) + "\n")
    status = StrategyLogStatus(strategy_id="x")
    result = read_strategy_log_delta(log, status, quarantine_threshold=100)
    assert len(result.events) == 2
    assert result.malformed_count == 0
    assert result.new_offset > 0
    # Second call returns nothing new.
    status.log_offset = result.new_offset
    result2 = read_strategy_log_delta(log, status, quarantine_threshold=100)
    assert result2.events == []


def test_log_delta_skips_malformed(tmp_path: Path) -> None:
    log = tmp_path / "bot.jsonl"
    log.write_text(
        json.dumps({"event": "bot_started", "strategy_id": "x", "ts": _TS}) + "\n"
        + "this is not json\n"
        + '{"event": "order_placed"}\n'  # missing strategy_id + ts
        + json.dumps({"event": "order_filled", "strategy_id": "x", "ts": _TS}) + "\n"
    )
    status = StrategyLogStatus(strategy_id="x")
    result = read_strategy_log_delta(log, status, quarantine_threshold=100)
    assert len(result.events) == 2
    assert result.malformed_count == 2
    assert not status.quarantined


def test_malformed_log_warning_includes_offset(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    log = tmp_path / "bot.jsonl"
    prefix = (
        json.dumps({"event": "bot_started", "strategy_id": "x", "ts": _TS})
        + "\n"
    ).encode()
    log.write_bytes(prefix + b'{"strategy_id":"x",broken}\n')
    caplog.set_level(logging.WARNING, logger="aggregator")

    result = read_strategy_log_delta(
        log,
        StrategyLogStatus(strategy_id="x"),
        quarantine_threshold=100,
    )

    assert result.malformed_count == 1
    assert any(
        "strategy_id=x" in record.getMessage()
        and f"offset={len(prefix)}" in record.getMessage()
        for record in caplog.records
    )


def test_log_delta_partial_line_held_back(tmp_path: Path) -> None:
    """A line without trailing newline must be re-read on next call."""
    log = tmp_path / "bot.jsonl"
    log.write_text(
        json.dumps({"event": "bot_started", "strategy_id": "x", "ts": _TS}) + "\n"
        + '{"event": "incomp'  # no newline
    )
    status = StrategyLogStatus(strategy_id="x")
    result = read_strategy_log_delta(log, status, quarantine_threshold=100)
    assert len(result.events) == 1
    status.log_offset = result.new_offset
    # Now complete the partial line.
    with log.open("a") as fh:
        fh.write('lete", "strategy_id": "x", "ts": "2026-05-14T00:00:00Z"}\n')
    result2 = read_strategy_log_delta(log, status, quarantine_threshold=100)
    assert len(result2.events) == 1
    assert result2.events[0]["event"] == "incomplete"


def test_log_delta_quarantine_at_threshold(tmp_path: Path) -> None:
    log = tmp_path / "bot.jsonl"
    # 101 malformed lines in one batch -> quarantine triggers.
    log.write_text("\n".join(["garbage"] * 101) + "\n")
    status = StrategyLogStatus(strategy_id="x")
    result = read_strategy_log_delta(log, status, quarantine_threshold=100)
    assert result.malformed_count == 101
    assert status.quarantined


def test_log_delta_quarantine_prunes_old_timestamps(tmp_path: Path) -> None:
    log = tmp_path / "bot.jsonl"
    log.write_text("\n".join(["garbage"] * 60) + "\n")
    status = StrategyLogStatus(strategy_id="x")
    # First batch at time t=0.
    r1 = read_strategy_log_delta(log, status, quarantine_threshold=100, now=0.0)
    status.log_offset = r1.new_offset
    assert len(status.malformed_timestamps) == 60
    # Append more garbage; call with now=120 (2 minutes later) -> old entries pruned.
    with log.open("a") as fh:
        fh.write("\n".join(["garbage"] * 30) + "\n")
    r2 = read_strategy_log_delta(log, status, quarantine_threshold=100, now=120.0)
    status.log_offset = r2.new_offset
    # Old t=0 entries are pruned; only the 30 new t=120 entries remain.
    assert len(status.malformed_timestamps) == 30
    assert not status.quarantined


def test_log_delta_missing_ts_is_malformed(tmp_path: Path) -> None:
    """Events missing 'ts' field are rejected as malformed (MEDIUM-E)."""
    log = tmp_path / "bot.jsonl"
    log.write_text(
        # Has event + strategy_id but no ts -> malformed.
        '{"event": "bot_started", "strategy_id": "x"}\n'
        # Has all three -> valid.
        + json.dumps({"event": "bot_started", "strategy_id": "x", "ts": _TS}) + "\n"
    )
    status = StrategyLogStatus(strategy_id="x")
    result = read_strategy_log_delta(log, status, quarantine_threshold=100)
    assert len(result.events) == 1
    assert result.malformed_count == 1


def test_log_delta_chunked_read(tmp_path: Path) -> None:
    """Bounded reads process only up to max_bytes per cycle (MEDIUM-G)."""
    log = tmp_path / "bot.jsonl"
    line = json.dumps({"event": "tick", "strategy_id": "x", "ts": _TS})
    # Each line is ~70 bytes. Write 200 lines (~14KB).
    log.write_text("\n".join([line] * 200) + "\n")
    status = StrategyLogStatus(strategy_id="x")
    # Read with a small max_bytes to force chunking.
    r1 = read_strategy_log_delta(
        log, status, quarantine_threshold=100, max_bytes=1024,
    )
    status.log_offset = r1.new_offset
    assert 0 < len(r1.events) < 200
    # Second read picks up more.
    r2 = read_strategy_log_delta(
        log, status, quarantine_threshold=100, max_bytes=1024,
    )
    status.log_offset = r2.new_offset
    assert len(r2.events) > 0
    total = len(r1.events) + len(r2.events)
    assert total < 200  # still not all -- multiple cycles needed


def test_null_venue_client_protocol_compatible() -> None:
    # Ensures NullVenueClient satisfies the VenueClient Protocol shape.
    client: NullVenueClient = NullVenueClient()
    snapshot = client.fetch_account_snapshot("anything")
    assert snapshot.account_scope == "anything"
    positions = client.fetch_group_positions(["x"])
    orders = client.fetch_open_orders(["x"])
    assert positions.positions == ()
    assert positions.complete is False
    assert positions.authoritative is False
    assert orders.orders == ()
    assert orders.complete is False
    assert orders.authoritative is False
    batch = client.fetch_ledger_batch("anything", ["x"], None)
    assert batch.complete is False
    assert batch.authoritative is False


def test_load_venue_client_valid_class() -> None:
    """Loading a valid VenueClient from a dotted-path spec succeeds."""
    # NullVenueClient itself is a valid target for the loader.
    spec = "src.risk.aggregator:NullVenueClient"
    client = load_venue_client(spec)
    # Must satisfy the protocol.
    snapshot = client.fetch_account_snapshot("test")
    assert snapshot.account_scope == "test"
    assert client.fetch_group_positions([]).positions == ()
    assert client.fetch_open_orders([]).orders == ()


def test_load_venue_client_missing_module() -> None:
    """Spec with module in allowed prefix but non-existent raises import error."""
    with pytest.raises(VenueClientLoadError, match="failed to import module"):
        load_venue_client("src.risk.totally_bogus_module:SomeClass")


def test_load_venue_client_missing_class() -> None:
    """Explicit spec where the module exists but the class does not."""
    with pytest.raises(VenueClientLoadError, match="not found in module"):
        load_venue_client("src.risk.aggregator:NonExistentClassName")


def test_load_venue_client_class_not_protocol_compliant() -> None:
    """Explicit spec where the class lacks required VenueClient methods.

    Uses a non-compliant class within an allowed module prefix.
    """
    with pytest.raises(VenueClientLoadError, match="does not satisfy VenueClient protocol"):
        load_venue_client("src.risk.aggregator:ConfigError")


def test_load_venue_client_bad_spec_format() -> None:
    """Spec without colon separator is rejected."""
    with pytest.raises(VenueClientLoadError, match="must be 'module:ClassName'"):
        load_venue_client("src.risk.aggregator.NullVenueClient")


def test_load_venue_client_allowlist_blocks_outside_prefix() -> None:
    """Spec with module outside allowed prefixes is rejected (HIGH-D)."""
    with pytest.raises(VenueClientLoadError, match="not in the allowed prefix list"):
        load_venue_client("builtins:int")
    with pytest.raises(VenueClientLoadError, match="not in the allowed prefix list"):
        load_venue_client("totally.bogus.module:SomeClass")


def test_load_venue_client_allowlist_monkeypatched(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the allowlist is expanded via monkeypatch, wider imports succeed."""
    monkeypatch.setattr(
        observations_module,
        "VENUE_CLIENT_ALLOWED_PREFIXES",
        ("src.risk.", "builtin"),
    )
    # "builtins" starts with "builtin" so it passes the prefix check.
    # int() has none of the protocol methods -> protocol error, not prefix error.
    with pytest.raises(VenueClientLoadError, match="does not satisfy VenueClient protocol"):
        load_venue_client("builtins:int")


def test_resolve_venue_client_spec_cli_wins() -> None:
    """CLI argument takes precedence over config."""
    result = resolve_venue_client_spec(
        cli_arg="cli.mod:Cls",
        config_block={"venue_client": "config.mod:Cls"},
    )
    assert result == "cli.mod:Cls"


def test_resolve_venue_client_spec_config_fallback() -> None:
    """Config block is used when CLI arg is None."""
    result = resolve_venue_client_spec(
        cli_arg=None,
        config_block={"venue_client": "config.mod:Cls"},
    )
    assert result == "config.mod:Cls"


def test_resolve_venue_client_spec_none_when_unconfigured() -> None:
    """Returns None when neither CLI nor config provides a spec."""
    assert resolve_venue_client_spec(None, None) is None
    assert resolve_venue_client_spec(None, {}) is None
    assert resolve_venue_client_spec(None, {"other_key": "val"}) is None


def test_log_inode_change_restarts_from_zero(tmp_path: Path) -> None:
    log_path = tmp_path / "bot.jsonl"
    first = {"event": "first", "strategy_id": "x", "ts": _TS}
    second = {"event": "second", "strategy_id": "x", "ts": _TS}
    log_path.write_text(json.dumps(first) + "\n")
    status = StrategyLogStatus(strategy_id="x")
    result = read_strategy_log_delta(log_path, status, quarantine_threshold=100)
    status.log_offset = result.new_offset

    replacement = tmp_path / "replacement.jsonl"
    replacement.write_text(json.dumps(second) + "\n")
    os.replace(replacement, log_path)
    result = read_strategy_log_delta(log_path, status, quarantine_threshold=100)

    assert [event["event"] for event in result.events] == ["second"]


def test_log_truncation_beyond_offset_restarts_from_zero(tmp_path: Path) -> None:
    log_path = tmp_path / "bot.jsonl"
    first = {"event": "first-event-with-long-name", "strategy_id": "x", "ts": _TS}
    second = {"event": "new", "strategy_id": "x", "ts": _TS}
    log_path.write_text(json.dumps(first) + "\n")
    status = StrategyLogStatus(strategy_id="x")
    result = read_strategy_log_delta(log_path, status, quarantine_threshold=100)
    status.log_offset = result.new_offset
    log_path.write_text(json.dumps(second) + "\n")

    result = read_strategy_log_delta(log_path, status, quarantine_threshold=100)

    assert [event["event"] for event in result.events] == ["new"]


def test_quote_currency_mismatch_fails_closed(tmp_path: Path) -> None:
    now = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    client = StubVenueClient(
        snapshot=_snapshot(timestamp=now, quote_currency="EUR"),
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
    assert state.consecutive_failures == 1
    assert state.fail_closed is True
    assert data["healthy"] is False
    assert data["metric_metadata"]["margin_ratio"]["source"] == "none"


@pytest.mark.parametrize(
    "case",
    [
        "snapshot_balance",
        "snapshot_equity",
        "snapshot_margin_used",
        "snapshot_margin_ratio",
        "position_size",
        "position_price",
        "position_pnl",
        "order_size",
        "order_price",
        "fill_quantity",
        "fill_price",
        "fill_pnl",
        "fill_commission",
        "fill_fees",
        "cash_delta",
        "cash_realized_pnl",
    ],
)
def test_extreme_finite_decimal_is_rejected_before_commit(
    tmp_path: Path,
    case: str,
) -> None:
    sid = "binance.swap.x.btcusdt.5m.v1"
    now = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    extreme = Decimal("1e100")
    snapshot = _snapshot(timestamp=now)
    positions: tuple[VenuePosition, ...] = ()
    orders: tuple[VenueOrder, ...] = ()
    batch = _ledger_batch(now)

    if case.startswith("snapshot_"):
        field_name = case.removeprefix("snapshot_")
        snapshot = replace(snapshot, **{field_name: extreme})
    elif case.startswith("position_"):
        field_name = {
            "position_size": "size",
            "position_price": "entry_price",
            "position_pnl": "unrealized_pnl",
        }[case]
        positions = (
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
        )
        positions = (replace(positions[0], **{field_name: extreme}),)
    elif case.startswith("order_"):
        field_name = {"order_size": "size", "order_price": "price"}[case]
        orders = (
            VenueOrder(
                order_id="order-1",
                strategy_id=sid,
                symbol="BTCUSDT",
                side="buy",
                size=Decimal("1"),
                price=Decimal("100"),
                status="open",
                account_scope="binance-main",
                quote_currency="USD",
            ),
        )
        orders = (replace(orders[0], **{field_name: extreme}),)
    elif case.startswith("fill_"):
        field_name = {
            "fill_quantity": "quantity",
            "fill_price": "execution_price",
            "fill_pnl": "gross_realized_pnl",
            "fill_commission": "commission",
            "fill_fees": "fees",
        }[case]
        fill = VenueFill(
            account_scope="binance-main",
            strategy_id=sid,
            symbol="BTCUSDT",
            order_id="order-1",
            fill_id="fill-1",
            occurred_at=now,
            side="buy",
            quantity=Decimal("1"),
            execution_price=Decimal("100"),
            gross_realized_pnl=Decimal("0"),
            commission=Decimal("0"),
            fees=Decimal("0"),
            quote_currency="USD",
        )
        batch = replace(batch, fills=(replace(fill, **{field_name: extreme}),))
    else:
        field_name = {
            "cash_delta": "cash_delta",
            "cash_realized_pnl": "realized_pnl_delta",
        }[case]
        cash_event = VenueCashEvent(
            account_scope="binance-main",
            event_id="cash-1",
            strategy_id=sid,
            symbol="BTCUSDT",
            occurred_at=now,
            kind="funding",
            cash_delta=Decimal("0"),
            realized_pnl_delta=Decimal("0"),
            quote_currency="USD",
        )
        batch = replace(
            batch,
            cash_events=(replace(cash_event, **{field_name: extreme}),),
        )

    state = AggregatorState(risk_group="crypto-main")
    ledger = FillLedger(tmp_path / "ledger.sqlite3", "binance-main", "USD")
    reconcile_once(
        StubVenueClient(
            snapshot=snapshot,
            positions=positions,
            orders=orders,
            ledger_batches=(batch,),
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

    assert state.fail_closed is True
    assert state.consecutive_failures == 1
    assert ledger.generation == 0


def test_stale_snapshot_preserves_caps_and_fail_closed(tmp_path: Path) -> None:
    observed_at = datetime(2026, 9, 5, 11, 57, tzinfo=UTC)
    now = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    state = AggregatorState(risk_group="crypto-main")
    state.fail_closed = True
    state.soft_cap = True
    state.hard_cap = True
    state.margin_emergency = True
    state.group_daily_pnl = Decimal("-600")
    state.residual_strategy_ids = {"residual"}
    client = StubVenueClient(
        snapshot=_snapshot(timestamp=observed_at),
        ledger_batches=(_ledger_batch(observed_at),),
    )

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

    assert state.consecutive_failures == 1
    assert state.fail_closed is True
    assert state.soft_cap is True
    assert state.hard_cap is True
    assert state.margin_emergency is True
    assert state.group_daily_pnl == Decimal("-600")
    assert state.residual_strategy_ids == {"residual"}

    ledger_stale_state = AggregatorState(risk_group="crypto-main")
    ledger_stale_state.fail_closed = True
    ledger_stale_state.soft_cap = True
    ledger_stale_state.group_daily_pnl = Decimal("-350")
    ledger_stale_state.residual_strategy_ids = {"ledger-residual"}
    reconcile_once(
        StubVenueClient(
            snapshot=_snapshot(timestamp=now),
            ledger_batches=(_ledger_batch(observed_at),),
        ),
        _default_config(),
        [],
        ledger_stale_state,
        {},
        tmp_path,
        now_utc=now,
        clock=lambda: now,
        ledger=FillLedger(
            tmp_path / "ledger-stale.sqlite3", "binance-main", "USD"
        ),
    )
    assert ledger_stale_state.consecutive_failures == 1
    assert ledger_stale_state.fail_closed is True
    assert ledger_stale_state.soft_cap is True
    assert ledger_stale_state.group_daily_pnl == Decimal("-350")
    assert ledger_stale_state.residual_strategy_ids == {"ledger-residual"}


def test_observation_freshness_uses_post_fetch_clock(tmp_path: Path) -> None:
    cycle_start = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    observed_during_fetch = cycle_start + timedelta(seconds=2)
    fetch_completed_at = cycle_start + timedelta(seconds=3)
    client = StubVenueClient(
        snapshot=_snapshot(timestamp=observed_during_fetch),
        ledger_batches=(
            _ledger_batch(fetch_completed_at + timedelta(seconds=1)),
        ),
    )
    venue_io_completed = False

    original_fetch_ledger_batch = client.fetch_ledger_batch

    def completing_fetch(
        account_scope: str,
        strategy_ids: Sequence[str],
        cursor: str | None,
    ) -> VenueLedgerBatch:
        nonlocal venue_io_completed
        batch = original_fetch_ledger_batch(account_scope, strategy_ids, cursor)
        venue_io_completed = True
        return batch

    client.fetch_ledger_batch = completing_fetch  # type: ignore[method-assign]
    clock_reads = 0

    def post_fetch_clock() -> datetime:
        nonlocal clock_reads
        assert venue_io_completed is True
        clock_reads += 1
        return fetch_completed_at

    state = AggregatorState(risk_group="crypto-main")
    reconcile_once(
        client,
        replace(
            _default_config(),
            future_skew_tolerance_s=2.0,
            accounting_cut_max_skew_s=2.0,
        ),
        [],
        state,
        {},
        tmp_path,
        now_utc=cycle_start,
        clock=post_fetch_clock,
        ledger=FillLedger(tmp_path / "ledger.sqlite3", "binance-main", "USD"),
    )

    assert clock_reads == 1
    assert state.consecutive_failures == 0
    assert state.fail_closed is False
    assert state.last_success_ts == fetch_completed_at


def test_observation_that_ages_out_during_fetch_is_rejected(tmp_path: Path) -> None:
    cycle_start = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    observed_at = cycle_start - timedelta(seconds=119)
    fetch_completed_at = cycle_start + timedelta(seconds=2)
    sid = "binance.swap.x.btcusdt.5m.v1"
    state = AggregatorState(risk_group="crypto-main")
    state.soft_cap = True
    state.hard_cap = True
    state.margin_emergency = True
    state.group_daily_pnl = Decimal("-600")
    state.residual_strategy_ids = {sid}
    ledger = FillLedger(tmp_path / "ledger.sqlite3", "binance-main", "USD")

    reconcile_once(
        StubVenueClient(
            snapshot=_snapshot(timestamp=observed_at),
            ledger_batches=(_ledger_batch(observed_at),),
        ),
        _default_config(),
        [_make_entry(sid, enabled=False)],
        state,
        {},
        tmp_path,
        now_utc=cycle_start,
        clock=lambda: fetch_completed_at,
        ledger=ledger,
    )

    assert state.consecutive_failures == 1
    assert state.fail_closed is True
    assert state.soft_cap is True
    assert state.hard_cap is True
    assert state.margin_emergency is True
    assert state.group_daily_pnl == Decimal("-600")
    assert state.residual_strategy_ids == {sid}
    assert ledger.generation == 0


def test_incomplete_position_observation_cannot_clear_residual(
    tmp_path: Path,
) -> None:
    sid = "binance.swap.x.btcusdt.5m.v1"
    entry = _make_entry(sid, enabled=False)
    now = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    state = AggregatorState(risk_group="crypto-main")
    state.residual_strategy_ids = {sid}
    state.group_gross_exposure = Decimal("100")

    class IncompleteClient(StubVenueClient):
        def fetch_group_positions(
            self, strategy_ids: Sequence[str]
        ) -> VenuePositionsObservation:
            return VenuePositionsObservation(positions=(), as_of=now, complete=False)

        def fetch_open_orders(
            self, strategy_ids: Sequence[str]
        ) -> VenueOrdersObservation:
            return VenueOrdersObservation(orders=(), as_of=now, complete=True)

    client = IncompleteClient(
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
        ledger=FillLedger(tmp_path / "ledger.sqlite3", "binance-main", "USD"),
    )

    assert state.consecutive_failures == 1
    assert state.fail_closed is True
    assert state.residual_strategy_ids == {sid}
    assert state.group_gross_exposure == Decimal("100")

    class IncompleteOrdersClient(StubVenueClient):
        def fetch_group_positions(
            self, strategy_ids: Sequence[str]
        ) -> VenuePositionsObservation:
            return VenuePositionsObservation(positions=(), as_of=now, complete=True)

        def fetch_open_orders(
            self, strategy_ids: Sequence[str]
        ) -> VenueOrdersObservation:
            return VenueOrdersObservation(orders=(), as_of=now, complete=False)

    order_state = AggregatorState(risk_group="crypto-main")
    order_state.residual_strategy_ids = {sid}
    order_state.open_order_count = 1
    reconcile_once(
        IncompleteOrdersClient(
            snapshot=_snapshot(timestamp=now),
            ledger_batches=(_ledger_batch(now),),
        ),
        _default_config(),
        [entry],
        order_state,
        {},
        tmp_path,
        now_utc=now,
        clock=lambda: now,
        ledger=FillLedger(
            tmp_path / "orders-ledger.sqlite3", "binance-main", "USD"
        ),
    )
    assert order_state.consecutive_failures == 1
    assert order_state.fail_closed is True
    assert order_state.residual_strategy_ids == {sid}
    assert order_state.open_order_count == 1

    class StalePositionsClient(IncompleteOrdersClient):
        def fetch_group_positions(
            self, strategy_ids: Sequence[str]
        ) -> VenuePositionsObservation:
            return VenuePositionsObservation(
                positions=(),
                as_of=now - timedelta(seconds=121),
                complete=True,
            )

        def fetch_open_orders(
            self, strategy_ids: Sequence[str]
        ) -> VenueOrdersObservation:
            return VenueOrdersObservation(orders=(), as_of=now, complete=True)

    stale_state = AggregatorState(risk_group="crypto-main")
    stale_state.residual_strategy_ids = {sid}
    reconcile_once(
        StalePositionsClient(
            snapshot=_snapshot(timestamp=now),
            ledger_batches=(_ledger_batch(now),),
        ),
        _default_config(),
        [entry],
        stale_state,
        {},
        tmp_path,
        now_utc=now,
        clock=lambda: now,
        ledger=FillLedger(
            tmp_path / "stale-positions-ledger.sqlite3", "binance-main", "USD"
        ),
    )
    assert stale_state.fail_closed is True
    assert stale_state.residual_strategy_ids == {sid}


def test_invalid_utf8_log_line_is_malformed_not_fatal(tmp_path: Path) -> None:
    sid = "binance.swap.x.btcusdt.5m.v1"
    entry = _make_entry(sid)
    log_path = tmp_path / entry.log_path / "bot.jsonl"
    log_path.parent.mkdir(parents=True)
    log_path.write_bytes(b"\x80\n")
    now = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    state = AggregatorState(risk_group="crypto-main")
    statuses: dict[str, StrategyLogStatus] = {}

    reconcile_once(
        StubVenueClient(
            snapshot=_snapshot(timestamp=now),
            ledger_batches=(_ledger_batch(now),),
        ),
        _default_config(),
        [entry],
        state,
        statuses,
        tmp_path,
        now_utc=now,
        clock=lambda: now,
        ledger=FillLedger(tmp_path / "ledger.sqlite3", "binance-main", "USD"),
    )

    assert state.consecutive_failures == 0
    assert len(statuses[sid].malformed_timestamps) == 1
    assert statuses[sid].log_offset == 2


def test_default_clock_path_rejects_observation_that_ages_out_during_fetch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cycle_start = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    observed_at = cycle_start - timedelta(seconds=119)
    fetch_completed_at = cycle_start + timedelta(seconds=2)
    sid = "binance.swap.x.btcusdt.5m.v1"
    state = AggregatorState(risk_group="crypto-main")
    state.soft_cap = True
    state.hard_cap = True
    state.margin_emergency = True
    state.group_daily_pnl = Decimal("-600")
    state.residual_strategy_ids = {sid}
    ledger = FillLedger(tmp_path / "ledger.sqlite3", "binance-main", "USD")

    monkeypatch.setattr(
        "src.risk.aggregator._utc_now",
        lambda: fetch_completed_at,
        raising=False,
    )
    reconcile_once(
        StubVenueClient(
            snapshot=_snapshot(timestamp=observed_at),
            ledger_batches=(_ledger_batch(observed_at),),
        ),
        _default_config(),
        [_make_entry(sid, enabled=False)],
        state,
        {},
        tmp_path,
        now_utc=cycle_start,
        ledger=ledger,
    )

    assert state.consecutive_failures == 1
    assert state.fail_closed is True
    assert state.soft_cap is True
    assert state.hard_cap is True
    assert state.margin_emergency is True
    assert state.group_daily_pnl == Decimal("-600")
    assert state.residual_strategy_ids == {sid}
    assert ledger.generation == 0


def test_generator_position_observation_is_materialized_once(tmp_path: Path) -> None:
    sid = "binance.swap.x.btcusdt.5m.v1"
    now = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    position = VenuePosition(
        strategy_id=sid,
        symbol="BTCUSDT",
        side="long",
        size=Decimal("2"),
        entry_price=Decimal("100"),
        unrealized_pnl=Decimal("-25"),
        account_scope="binance-main",
        quote_currency="USD",
    )
    order = VenueOrder(
        order_id="open-1",
        strategy_id=sid,
        symbol="BTCUSDT",
        side="sell",
        size=Decimal("1"),
        price=Decimal("110"),
        status="open",
        account_scope="binance-main",
        quote_currency="USD",
    )

    class GeneratorObservationClient(StubVenueClient):
        def fetch_group_positions(
            self, strategy_ids: Sequence[str]
        ) -> VenuePositionsObservation:
            observation = super().fetch_group_positions(strategy_ids)
            return replace(
                observation,
                positions=(item for item in (position,)),
            )  # type: ignore[arg-type]

        def fetch_open_orders(
            self, strategy_ids: Sequence[str]
        ) -> VenueOrdersObservation:
            observation = super().fetch_open_orders(strategy_ids)
            return replace(
                observation,
                orders=(item for item in (order,)),
            )  # type: ignore[arg-type]

    state = AggregatorState(risk_group="crypto-main")
    ledger = FillLedger(tmp_path / "ledger.sqlite3", "binance-main", "USD")
    reconcile_once(
        GeneratorObservationClient(
            snapshot=_snapshot(timestamp=now),
            positions=(position,),
            orders=(order,),
            ledger_batches=(_ledger_batch(now),),
        ),
        _default_config(),
        [_make_entry(sid, enabled=False)],
        state,
        {},
        tmp_path,
        now_utc=now,
        clock=lambda: now,
        ledger=ledger,
    )

    assert state.group_net_exposure == Decimal("200")
    assert state.group_gross_exposure == Decimal("200")
    assert state.daily_unrealized_pnl == Decimal("-25")
    assert state.open_position_count == 1
    assert state.open_order_count == 1
    assert state.residual_strategy_ids == {sid}


@pytest.mark.parametrize("observation_kind", ["positions", "orders", "ledger"])
@pytest.mark.parametrize("flag_name", ["complete", "authoritative"])
@pytest.mark.parametrize("invalid_value", ["false", 1, None])
def test_non_boolean_completeness_flag_fails_closed(
    tmp_path: Path,
    observation_kind: str,
    flag_name: str,
    invalid_value: object,
) -> None:
    now = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    ledger = FillLedger(tmp_path / "ledger.sqlite3", "binance-main", "USD")
    state = AggregatorState(risk_group="crypto-main")
    state.residual_strategy_ids = {"residual"}

    class InvalidFlagClient(StubVenueClient):
        def fetch_group_positions(
            self, strategy_ids: Sequence[str]
        ) -> VenuePositionsObservation:
            observation = super().fetch_group_positions(strategy_ids)
            if observation_kind == "positions":
                return replace(observation, **{flag_name: invalid_value})
            return observation

        def fetch_open_orders(
            self, strategy_ids: Sequence[str]
        ) -> VenueOrdersObservation:
            observation = super().fetch_open_orders(strategy_ids)
            if observation_kind == "orders":
                return replace(observation, **{flag_name: invalid_value})
            return observation

        def fetch_ledger_batch(
            self,
            account_scope: str,
            strategy_ids: Sequence[str],
            cursor: str | None,
        ) -> VenueLedgerBatch:
            batch = super().fetch_ledger_batch(account_scope, strategy_ids, cursor)
            if observation_kind == "ledger":
                return replace(batch, **{flag_name: invalid_value})
            return batch

    reconcile_once(
        InvalidFlagClient(snapshot=_snapshot(timestamp=now)),
        _default_config(),
        [],
        state,
        {},
        tmp_path,
        now_utc=now,
        clock=lambda: now,
        ledger=ledger,
    )

    assert state.consecutive_failures == 1
    assert state.fail_closed is True
    assert state.residual_strategy_ids == {"residual"}
    assert ledger.generation == 0


def test_position_cut_older_than_ledger_skew_fails_cycle(tmp_path: Path) -> None:
    sid = "binance.swap.x.btcusdt.5m.v1"
    position_cut = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    ledger_cut = position_cut + timedelta(milliseconds=51)
    state = AggregatorState(risk_group="crypto-main")
    state.soft_cap = True
    state.residual_strategy_ids = {sid}
    ledger = FillLedger(tmp_path / "ledger.sqlite3", "binance-main", "USD")

    reconcile_once(
        StubVenueClient(
            snapshot=_snapshot(timestamp=position_cut),
            ledger_batches=(_ledger_batch(ledger_cut),),
        ),
        _default_config(),
        [_make_entry(sid, enabled=False)],
        state,
        {},
        tmp_path,
        now_utc=ledger_cut,
        clock=lambda: ledger_cut,
        ledger=ledger,
    )

    assert state.fail_closed is True
    assert state.soft_cap is True
    assert state.residual_strategy_ids == {sid}
    assert ledger.generation == 0


def test_position_cut_newer_than_ledger_watermark_fails_cycle(
    tmp_path: Path,
) -> None:
    sid = "binance.swap.x.btcusdt.5m.v1"
    ledger_cut = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    position_cut = ledger_cut + timedelta(minutes=1)
    state = AggregatorState(risk_group="crypto-main")
    state.group_daily_pnl = Decimal("-600")
    state.soft_cap = True
    state.hard_cap = True
    state.residual_strategy_ids = {sid}
    ledger = FillLedger(tmp_path / "ledger.sqlite3", "binance-main", "USD")

    reconcile_once(
        StubVenueClient(
            snapshot=_snapshot(timestamp=position_cut),
            ledger_batches=(_ledger_batch(ledger_cut),),
        ),
        replace(_default_config(), accounting_cut_max_skew_s=30.0),
        [_make_entry(sid, enabled=False)],
        state,
        {},
        tmp_path,
        now_utc=position_cut,
        clock=lambda: position_cut,
        ledger=ledger,
    )

    assert state.fail_closed is True
    assert state.group_daily_pnl == Decimal("-600")
    assert state.soft_cap is True
    assert state.hard_cap is True
    assert state.residual_strategy_ids == {sid}
    assert ledger.generation == 0


def test_position_newer_than_ledger_watermark_with_intervening_close_fails_closed(
    tmp_path: Path,
) -> None:
    sid = "binance.swap.x.btcusdt.5m.v1"
    ledger_cut = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    intervening_close_at = ledger_cut + timedelta(seconds=20)
    position_observed_at = ledger_cut + timedelta(seconds=30)
    intervening_realized_loss = Decimal("-600")
    assert ledger_cut < intervening_close_at < position_observed_at

    state = AggregatorState(risk_group="crypto-main")
    state.group_daily_pnl = intervening_realized_loss
    state.soft_cap = True
    state.hard_cap = True
    state.residual_strategy_ids = {sid}
    ledger = FillLedger(tmp_path / "ledger.sqlite3", "binance-main", "USD")

    # The ledger is complete only through 12:00, so the 12:00:20 realized
    # loss is not available yet. The later flat position view cannot safely
    # replace the cached enforcement state without a position view at 12:00.
    reconcile_once(
        StubVenueClient(
            snapshot=_snapshot(timestamp=position_observed_at),
            positions=(),
            ledger_batches=(_ledger_batch(ledger_cut),),
        ),
        replace(_default_config(), accounting_cut_max_skew_s=60.0),
        [_make_entry(sid, enabled=False)],
        state,
        {},
        tmp_path,
        now_utc=position_observed_at,
        clock=lambda: position_observed_at,
        ledger=ledger,
    )

    assert state.fail_closed is True
    assert state.group_daily_pnl == intervening_realized_loss
    assert state.soft_cap is True
    assert state.hard_cap is True
    assert state.residual_strategy_ids == {sid}
    assert ledger.generation == 0


def test_adapter_supplied_positions_as_of_cut_are_accepted(tmp_path: Path) -> None:
    sid = "binance.swap.x.btcusdt.5m.v1"
    ledger_cut = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    position_observed_at = ledger_cut + timedelta(seconds=30)
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
        unrealized_pnl=Decimal("-25"),
        account_scope="binance-main",
        quote_currency="USD",
    )
    state = AggregatorState(risk_group="crypto-main")
    ledger = FillLedger(tmp_path / "ledger.sqlite3", "binance-main", "USD")

    reconcile_once(
        StubVenueClient(
            snapshot=_snapshot(timestamp=position_observed_at),
            positions=(position,),
            ledger_batches=(_ledger_batch(ledger_cut, fills=(fill,)),),
            positions_as_of_cut=ledger_cut,
        ),
        replace(_default_config(), accounting_cut_max_skew_s=60.0),
        [_make_entry(sid)],
        state,
        {},
        tmp_path,
        now_utc=position_observed_at,
        clock=lambda: position_observed_at,
        ledger=ledger,
    )

    assert state.fail_closed is False
    assert state.daily_realized_pnl == Decimal("-50")
    assert state.daily_unrealized_pnl == Decimal("-25")
    assert state.group_daily_pnl == Decimal("-75")
    assert ledger.generation == 1

    payload = state_to_dict(state, _default_config(), now_utc=position_observed_at)
    assert (
        payload["metric_metadata"]["daily_realized_pnl"]["as_of_ts"]
        == ledger_cut.isoformat()
    )
    assert (
        payload["metric_metadata"]["daily_unrealized_pnl"]["as_of_ts"]
        == position_observed_at.isoformat()
    )
    assert (
        payload["metric_metadata"]["group_daily_pnl"]["as_of_ts"]
        == ledger_cut.isoformat()
    )
