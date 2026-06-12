"""Tests for src.risk.aggregator."""

from __future__ import annotations

import json
import threading
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from src.orchestrator.registry import (
    RegistryDefaults,
    RegistryDocument,
    Runtime,
    StrategyEntry,
    StrategyState,
    atomic_replace,
    dump_registry,
)
from src.risk.aggregator import (
    AggregatorConfig,
    AggregatorState,
    NullVenueClient,
    StrategyLogStatus,
    VenueAccountSnapshot,
    VenueClientLoadError,
    VenueOrder,
    VenuePosition,
    _checkpoint_file,
    compute_group_metrics,
    determine_signals,
    load_aggregator_config,
    load_checkpoint,
    load_group_strategies,
    load_venue_client,
    publish_state,
    read_strategy_log_delta,
    reconcile_once,
    resolve_venue_client_spec,
    run_forever,
    save_checkpoint,
    state_to_dict,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_entry(
    sid: str = "binance.swap.mr.btcusdt.5m.v1",
    *,
    risk_group: str = "crypto-main",
    state: StrategyState = StrategyState.LIVE,
    enabled: bool = True,
) -> StrategyEntry:
    now = datetime.now(UTC).replace(microsecond=0)
    return StrategyEntry(
        id=sid,
        family_id="mr",
        logic_version="1.0.0",
        runtime=Runtime.PYTHON,
        venue="binance",
        market="swap",
        symbol="BTCUSDT",
        timeframe="5m",
        account_scope="binance-main",
        risk_group=risk_group,
        state=state,
        enabled=enabled,
        config_path=f"config/strategies/{sid}.toml",
        state_path=f"state/strategies/{sid}",
        log_path=f"logs/strategies/{sid}",
        db_path=f"state/strategies/{sid}/state.db",
        magic_number=0,
        magic_salt=0,
        created_at=now,
        updated_at=now,
    )


def _default_config(risk_group: str = "crypto-main") -> AggregatorConfig:
    return AggregatorConfig(
        risk_group=risk_group,
        poll_interval_s=0.05,
        soft_cap_daily_loss_pct=3.0,
        hard_cap_daily_loss_pct=5.0,
        margin_emergency_threshold=0.95,
        fail_closed_after_consecutive_failures=5,
        malformed_log_quarantine_per_minute=100,
        health_window_s=120.0,
    )


# ---------------------------------------------------------------------------
# load_group_strategies
# ---------------------------------------------------------------------------


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
        ],
    )
    result = load_group_strategies(doc, "crypto-main")
    ids = sorted(s.id for s in result)
    assert ids == ["a.swap.x.a.5m.v1", "e.swap.x.e.5m.v1"]


# ---------------------------------------------------------------------------
# read_strategy_log_delta
# ---------------------------------------------------------------------------

_TS = "2026-05-14T00:00:00Z"


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


# ---------------------------------------------------------------------------
# Pure metric / signal helpers
# ---------------------------------------------------------------------------


def test_compute_group_metrics() -> None:
    positions = [
        VenuePosition(
            strategy_id="a",
            symbol="BTCUSDT",
            side="long",
            size=Decimal("1"),
            entry_price=Decimal("60000"),
            unrealized_pnl=Decimal("0"),
        ),
        VenuePosition(
            strategy_id="b",
            symbol="ETHUSDT",
            side="short",
            size=Decimal("10"),
            entry_price=Decimal("3000"),
            unrealized_pnl=Decimal("0"),
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


def test_determine_signals_margin_emergency() -> None:
    state = AggregatorState(risk_group="g")
    state.last_snapshot = _snapshot(balance=Decimal("10000"), margin_ratio=Decimal("0.98"))
    state.group_daily_pnl = Decimal("0")
    config = _default_config()
    determine_signals(state, config)
    assert state.margin_emergency is True


def _snapshot(
    balance: Decimal = Decimal("10000"),
    margin_ratio: Decimal = Decimal("0"),
    equity: Decimal | None = None,
) -> VenueAccountSnapshot:
    eq = equity if equity is not None else balance
    return VenueAccountSnapshot(
        account_scope="acc",
        balance=balance,
        equity=eq,
        margin_used=balance * margin_ratio,
        margin_ratio=margin_ratio,
        timestamp=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# Stub VenueClient (matches the Protocol)
# ---------------------------------------------------------------------------


class StubVenueClient:
    def __init__(
        self,
        snapshot: VenueAccountSnapshot,
        positions: Sequence[VenuePosition] = (),
        orders: Sequence[VenueOrder] = (),
        raise_count: int = 0,
    ) -> None:
        self._snapshot = snapshot
        self._positions = positions
        self._orders = orders
        self._raise_count = raise_count
        self.call_count = 0

    def fetch_account_snapshot(self, account_scope: str) -> VenueAccountSnapshot:
        self.call_count += 1
        if self.call_count <= self._raise_count:
            raise RuntimeError(f"simulated venue failure {self.call_count}")
        return self._snapshot

    def fetch_group_positions(
        self, strategy_ids: Sequence[str]
    ) -> Sequence[VenuePosition]:
        return self._positions

    def fetch_open_orders(self, strategy_ids: Sequence[str]) -> Sequence[VenueOrder]:
        return self._orders


# ---------------------------------------------------------------------------
# reconcile_once
# ---------------------------------------------------------------------------


def test_reconcile_increments_failures(tmp_path: Path) -> None:
    config = _default_config()
    client = StubVenueClient(snapshot=_snapshot(), raise_count=100)
    state = AggregatorState(risk_group=config.risk_group)
    log_statuses: dict[str, StrategyLogStatus] = {}
    for i in range(1, 5):
        state = reconcile_once(client, config, [], state, log_statuses, tmp_path)
        assert state.consecutive_failures == i
        assert state.fail_closed is False
    state = reconcile_once(client, config, [], state, log_statuses, tmp_path)
    assert state.consecutive_failures == 5
    assert state.fail_closed is True


def test_reconcile_happy_path_resets_failures(tmp_path: Path) -> None:
    config = _default_config()
    client = StubVenueClient(snapshot=_snapshot(), raise_count=2)
    state = AggregatorState(risk_group=config.risk_group)
    log_statuses: dict[str, StrategyLogStatus] = {}
    # Two failures.
    reconcile_once(client, config, [], state, log_statuses, tmp_path)
    reconcile_once(client, config, [], state, log_statuses, tmp_path)
    assert state.consecutive_failures == 2
    # Third succeeds -> reset.
    reconcile_once(client, config, [], state, log_statuses, tmp_path)
    assert state.consecutive_failures == 0
    assert state.fail_closed is False
    assert state.last_success_ts is not None


# ---------------------------------------------------------------------------
# CRITICAL-A: Daily PnL accounting
# ---------------------------------------------------------------------------


def test_unrealized_pnl_no_double_count(tmp_path: Path) -> None:
    """Repeated position_update for the same (strategy, symbol) overwrites,
    not sums. 100 then 120 -> group unrealized = 120."""
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

    # Use NullVenueClient so venue provides no positions -> log-derived unrealized used.
    client = NullVenueClient()
    state = AggregatorState(risk_group=config.risk_group)
    log_statuses: dict[str, StrategyLogStatus] = {}
    state = reconcile_once(
        client, config, [entry], state, log_statuses, tmp_path,
    )
    # Unrealized is 120 (latest), not 220 (sum).
    assert state.group_daily_pnl == Decimal("120")
    assert state.latest_unrealized[(sid, "BTCUSDT")] == Decimal("120")


def test_realized_pnl_accumulates_across_cycles(tmp_path: Path) -> None:
    """Realized PnL from position_closed accumulates across cycles within a day.
    50 in cycle 1 + 30 in cycle 2 = 80."""
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
    client = NullVenueClient()
    state = AggregatorState(risk_group=config.risk_group)
    log_statuses: dict[str, StrategyLogStatus] = {}
    state = reconcile_once(client, config, [entry], state, log_statuses, tmp_path)
    assert state.daily_realized_pnl == Decimal("50")

    # Cycle 2: append another position_closed with pnl=30.
    with log_file.open("a") as fh:
        fh.write(
            json.dumps({
                "event": "position_closed", "strategy_id": sid,
                "symbol": "BTCUSDT", "pnl": 30, "ts": f"{today}T02:05:00Z",
            }) + "\n"
        )
    state = reconcile_once(client, config, [entry], state, log_statuses, tmp_path)
    assert state.daily_realized_pnl == Decimal("80")
    assert state.group_daily_pnl == Decimal("80")


# ---------------------------------------------------------------------------
# CRITICAL-C: Drawdown tracking + UTC day boundary
# ---------------------------------------------------------------------------


def test_utc_day_boundary_resets_and_hwm_survives(tmp_path: Path) -> None:
    """On UTC day change: counters reset, SoD re-anchors, HWM survives."""
    config = _default_config()
    day1 = datetime(2026, 6, 10, 23, 0, 0, tzinfo=UTC)
    day2 = datetime(2026, 6, 11, 1, 0, 0, tzinfo=UTC)

    snap_d1 = VenueAccountSnapshot(
        account_scope="acc", balance=Decimal("10000"), equity=Decimal("10500"),
        margin_used=Decimal("0"), margin_ratio=Decimal("0"), timestamp=day1,
    )
    snap_d2 = VenueAccountSnapshot(
        account_scope="acc", balance=Decimal("10000"), equity=Decimal("10200"),
        margin_used=Decimal("0"), margin_ratio=Decimal("0"), timestamp=day2,
    )

    class DayClient:
        def __init__(self) -> None:
            self.snap = snap_d1

        def fetch_account_snapshot(self, account_scope: str) -> VenueAccountSnapshot:
            return self.snap

        def fetch_group_positions(self, strategy_ids: Sequence[str]) -> Sequence[VenuePosition]:
            return []

        def fetch_open_orders(self, strategy_ids: Sequence[str]) -> Sequence[VenueOrder]:
            return []

    client = DayClient()
    state = AggregatorState(risk_group=config.risk_group)
    log_statuses: dict[str, StrategyLogStatus] = {}

    # Simulate a position_closed on day 1 to have realized PnL.
    state.daily_realized_pnl = Decimal("50")
    state.current_utc_date = day1.date()

    # Day 1 cycle.
    state = reconcile_once(
        client, config, [], state, log_statuses, tmp_path, now_utc=day1,
    )
    assert state.start_of_day_equity == Decimal("10500")
    assert state.high_water_mark == Decimal("10500")
    assert state.daily_realized_pnl == Decimal("50")

    # Day 2 cycle -- day boundary.
    client.snap = snap_d2
    state = reconcile_once(
        client, config, [], state, log_statuses, tmp_path, now_utc=day2,
    )
    assert state.current_utc_date == day2.date()
    # Realized PnL reset.
    assert state.daily_realized_pnl == Decimal("0")
    # SoD equity re-anchored.
    assert state.start_of_day_equity == Decimal("10200")
    # HWM survives from day 1.
    assert state.high_water_mark == Decimal("10500")
    # Drawdown from HWM.
    expected_hwm_dd = (Decimal("10200") - Decimal("10500")) / Decimal("10500") * 100
    assert state.drawdown_hwm_pct == expected_hwm_dd


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


# ---------------------------------------------------------------------------
# CRITICAL-B: Checkpoint persistence
# ---------------------------------------------------------------------------


def test_checkpoint_save_load_roundtrip(tmp_path: Path) -> None:
    """Persist checkpoint, new instance loads it: offsets/HWM/daily PnL restored."""
    ckpt_path = tmp_path / "checkpoint.json"

    # Build state with meaningful values.
    state1 = AggregatorState(risk_group="crypto-main")
    state1.current_utc_date = date(2026, 6, 11)
    state1.daily_realized_pnl = Decimal("123.45")
    state1.latest_unrealized[("strat-a", "BTCUSDT")] = Decimal("50")
    state1.latest_unrealized[("strat-b", "ETHUSDT")] = Decimal("-20")
    state1.start_of_day_equity = Decimal("10000")
    state1.high_water_mark = Decimal("10500")
    state1.consecutive_failures = 2
    state1.fail_closed = True

    log_statuses1: dict[str, StrategyLogStatus] = {
        "strat-a": StrategyLogStatus(strategy_id="strat-a", log_offset=4096),
        "strat-b": StrategyLogStatus(strategy_id="strat-b", log_offset=8192),
    }
    save_checkpoint(ckpt_path, state1, log_statuses1)
    assert ckpt_path.exists()

    # Load into fresh state.
    state2 = AggregatorState(risk_group="crypto-main")
    log_statuses2: dict[str, StrategyLogStatus] = {}
    loaded = load_checkpoint(ckpt_path, state2, log_statuses2)

    assert loaded is True
    assert state2.current_utc_date == date(2026, 6, 11)
    assert state2.daily_realized_pnl == Decimal("123.45")
    assert state2.latest_unrealized[("strat-a", "BTCUSDT")] == Decimal("50")
    assert state2.latest_unrealized[("strat-b", "ETHUSDT")] == Decimal("-20")
    assert state2.start_of_day_equity == Decimal("10000")
    assert state2.high_water_mark == Decimal("10500")
    assert state2.consecutive_failures == 2
    assert state2.fail_closed is True
    assert log_statuses2["strat-a"].log_offset == 4096
    assert log_statuses2["strat-b"].log_offset == 8192


def test_checkpoint_missing_starts_fresh(tmp_path: Path) -> None:
    """Missing checkpoint file returns False and leaves state untouched."""
    ckpt_path = tmp_path / "nonexistent.json"
    state = AggregatorState(risk_group="g")
    log_statuses: dict[str, StrategyLogStatus] = {}
    assert load_checkpoint(ckpt_path, state, log_statuses) is False
    assert state.daily_realized_pnl == Decimal("0")


def test_checkpoint_corrupt_starts_fresh(tmp_path: Path) -> None:
    """Corrupt checkpoint file returns False with a WARNING."""
    ckpt_path = tmp_path / "checkpoint.json"
    ckpt_path.write_text("not json at all")
    state = AggregatorState(risk_group="g")
    log_statuses: dict[str, StrategyLogStatus] = {}
    assert load_checkpoint(ckpt_path, state, log_statuses) is False


def test_restart_loads_checkpoint_no_replay(tmp_path: Path) -> None:
    """After restart, checkpoint restores offsets so logs are not replayed."""
    sid = "binance.swap.x.btc.5m.v1"
    entry = _make_entry(sid)

    # Set up registry.
    doc = RegistryDocument(
        schema_version=1, defaults=RegistryDefaults(), accounts=[],
        strategies=[entry],
    )
    registry_path = tmp_path / "config" / "registry.toml"
    atomic_replace(registry_path, dump_registry(doc))

    # Set up log with one position_closed event.
    log_dir = tmp_path / "logs" / "strategies" / sid
    log_dir.mkdir(parents=True)
    log_file = log_dir / "bot.jsonl"
    today = datetime.now(UTC).date().isoformat()
    log_file.write_text(
        json.dumps({
            "event": "position_closed", "strategy_id": sid,
            "symbol": "BTCUSDT", "pnl": 100, "ts": f"{today}T03:00:00Z",
        }) + "\n"
    )

    config = _default_config()
    client = NullVenueClient()

    # First run: 1 iteration.
    stop = threading.Event()
    run_forever(config, registry_path, tmp_path, client, stop, max_iterations=1)

    # Verify checkpoint was saved.
    ckpt_path = _checkpoint_file(tmp_path, config.risk_group)
    assert ckpt_path.exists()
    ckpt_data = json.loads(ckpt_path.read_text())
    assert ckpt_data["daily_realized_pnl"] == "100"
    # The log offset should be past the event.
    assert ckpt_data["log_offsets"][sid] > 0

    # Second run: 1 iteration -- should NOT re-read the same event.
    run_forever(config, registry_path, tmp_path, client, stop, max_iterations=1)
    ckpt_data2 = json.loads(ckpt_path.read_text())
    # Realized PnL should still be 100, not 200 (no double-count).
    assert ckpt_data2["daily_realized_pnl"] == "100"


# ---------------------------------------------------------------------------
# publish_state
# ---------------------------------------------------------------------------


def test_publish_state_writes_valid_json(tmp_path: Path) -> None:
    config = _default_config()
    state = AggregatorState(risk_group=config.risk_group)
    state.last_success_ts = datetime.now(UTC)
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


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------


def test_load_aggregator_config(tmp_path: Path) -> None:
    cfg = tmp_path / "risk_groups.toml"
    cfg.write_text(
        '[risk_groups.crypto-main]\n'
        'account_scope = "binance-main"\n'
        'soft_cap_daily_loss_pct = 2.5\n'
        'hard_cap_daily_loss_pct = 4.5\n'
    )
    result = load_aggregator_config(cfg, "crypto-main")
    assert result.risk_group == "crypto-main"
    assert result.account_scope == "binance-main"
    assert result.soft_cap_daily_loss_pct == 2.5
    assert result.hard_cap_daily_loss_pct == 4.5


def test_load_aggregator_config_missing_group(tmp_path: Path) -> None:
    cfg = tmp_path / "risk_groups.toml"
    cfg.write_text('[risk_groups.other]\n')
    with pytest.raises(Exception, match="crypto-main"):
        load_aggregator_config(cfg, "crypto-main")


# ---------------------------------------------------------------------------
# Integration: run_forever with stub client
# ---------------------------------------------------------------------------


def test_run_forever_two_iterations_with_stub(tmp_path: Path) -> None:
    # Build a temp registry with one strategy in target group.
    doc = RegistryDocument(
        schema_version=1,
        defaults=RegistryDefaults(),
        accounts=[],
        strategies=[_make_entry("binance.swap.x.btc.5m.v1")],
    )
    registry_path = tmp_path / "config" / "registry.toml"
    atomic_replace(registry_path, dump_registry(doc))
    # Pre-create log dir so path validation passes (the dir need not have content).
    (tmp_path / "logs" / "strategies" / "binance.swap.x.btc.5m.v1").mkdir(parents=True)

    config = _default_config()
    client = StubVenueClient(
        snapshot=_snapshot(balance=Decimal("10000")),
        positions=[
            VenuePosition(
                strategy_id="binance.swap.x.btc.5m.v1",
                symbol="BTCUSDT",
                side="long",
                size=Decimal("0.1"),
                entry_price=Decimal("60000"),
                unrealized_pnl=Decimal("0"),
            )
        ],
    )

    stop_event = threading.Event()
    rc = run_forever(
        config,
        registry_path,
        tmp_path,
        client,
        stop_event=stop_event,
        max_iterations=2,
    )
    assert rc == 0
    state_path = tmp_path / "data" / "aggregator" / config.risk_group / "state.json"
    assert state_path.exists()
    data = json.loads(state_path.read_text())
    # After max_iterations the loop publishes a shutdown state with fail_closed=True.
    assert data["fail_closed"] is True


def test_null_venue_client_protocol_compatible() -> None:
    # Ensures NullVenueClient satisfies the VenueClient Protocol shape.
    client: NullVenueClient = NullVenueClient()
    snapshot = client.fetch_account_snapshot("anything")
    assert snapshot.account_scope == "anything"
    assert client.fetch_group_positions(["x"]) == []
    assert client.fetch_open_orders(["x"]) == []


# ---------------------------------------------------------------------------
# Venue client injection (load_venue_client / resolve_venue_client_spec)
# ---------------------------------------------------------------------------


def test_load_venue_client_valid_class() -> None:
    """Loading a valid VenueClient from a dotted-path spec succeeds."""
    # NullVenueClient itself is a valid target for the loader.
    spec = "src.risk.aggregator:NullVenueClient"
    client = load_venue_client(spec)
    # Must satisfy the protocol.
    snapshot = client.fetch_account_snapshot("test")
    assert snapshot.account_scope == "test"
    assert client.fetch_group_positions([]) == []
    assert client.fetch_open_orders([]) == []


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
        "src.risk.aggregator.VENUE_CLIENT_ALLOWED_PREFIXES",
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
