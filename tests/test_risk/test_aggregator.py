"""Tests for src.risk.aggregator."""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime, timedelta
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
    compute_group_metrics,
    determine_signals,
    load_aggregator_config,
    load_group_strategies,
    load_venue_client,
    publish_state,
    read_strategy_log_delta,
    reconcile_once,
    resolve_venue_client_spec,
    run_forever,
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


def test_log_delta_well_formed(tmp_path: Path) -> None:
    log = tmp_path / "bot.jsonl"
    lines = [
        {"event": "bot_started", "strategy_id": "x", "ts": "2026-05-14T00:00:00Z"},
        {"event": "position_update", "strategy_id": "x", "unrealized_pnl": 12.5},
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
        '{"event": "bot_started", "strategy_id": "x"}\n'
        "this is not json\n"
        '{"event": "order_placed"}\n'  # missing strategy_id
        '{"event": "order_filled", "strategy_id": "x"}\n'
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
        '{"event": "bot_started", "strategy_id": "x"}\n'
        '{"event": "incomp'  # no newline
    )
    status = StrategyLogStatus(strategy_id="x")
    result = read_strategy_log_delta(log, status, quarantine_threshold=100)
    assert len(result.events) == 1
    status.log_offset = result.new_offset
    # Now complete the partial line.
    with log.open("a") as fh:
        fh.write('lete", "strategy_id": "x"}\n')
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
) -> VenueAccountSnapshot:
    return VenueAccountSnapshot(
        account_scope="acc",
        balance=balance,
        equity=balance,
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
    """Explicit spec with a non-existent module raises VenueClientLoadError."""
    with pytest.raises(VenueClientLoadError, match="failed to import module"):
        load_venue_client("totally.bogus.module:SomeClass")


def test_load_venue_client_missing_class() -> None:
    """Explicit spec where the module exists but the class does not."""
    with pytest.raises(VenueClientLoadError, match="not found in module"):
        load_venue_client("src.risk.aggregator:NonExistentClassName")


def test_load_venue_client_class_not_protocol_compliant() -> None:
    """Explicit spec where the class lacks required VenueClient methods."""
    # int() has none of the protocol methods.
    with pytest.raises(VenueClientLoadError, match="does not satisfy VenueClient protocol"):
        load_venue_client("builtins:int")


def test_load_venue_client_bad_spec_format() -> None:
    """Spec without colon separator is rejected."""
    with pytest.raises(VenueClientLoadError, match="must be 'module:ClassName'"):
        load_venue_client("src.risk.aggregator.NullVenueClient")


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
