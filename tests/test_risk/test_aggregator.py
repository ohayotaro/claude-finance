"""Orchestration and CLI tests for the risk aggregator facade."""

from __future__ import annotations

# ruff: noqa: F401
import ast
import json
import logging
import signal
import threading
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

import src.risk.accounting as accounting_module
import src.risk.aggregator as aggregator_module
import src.risk.config as config_module
import src.risk.observations as observations_module
import src.risk.persistence as persistence_module
import src.risk.publication as publication_module
from src.orchestrator.registry import (
    ExitCode,
    RegistryDefaults,
    RegistryDocument,
    StrategyState,
    atomic_replace,
    dump_registry,
)
from src.risk.accounting import AggregatorState
from src.risk.aggregator import main, reconcile_once, run_forever
from src.risk.config import AggregatorConfig, _checkpoint_file
from src.risk.ledger import FillLedger, VenueFill
from src.risk.observations import NullVenueClient, StrategyLogStatus, VenuePosition
from src.risk.persistence import save_checkpoint
from src.risk.publication import publish_state, state_to_dict
from tests.test_risk._aggregator_support import (
    StubVenueClient,
    _default_config,
    _ledger_batch,
    _make_entry,
    _snapshot,
    _write_registry,
    _write_risk_group_config,
)


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


def test_null_venue_client_reconcile_is_unhealthy_fail_closed(tmp_path: Path) -> None:
    config = _default_config()
    client = NullVenueClient()
    state = AggregatorState(risk_group=config.risk_group)
    state.last_success_ts = datetime.now(UTC)
    state.fail_closed = False
    log_statuses: dict[str, StrategyLogStatus] = {}

    state = reconcile_once(client, config, [], state, log_statuses, tmp_path)
    data = state_to_dict(state, config)

    assert state.fail_closed is True
    assert state.last_success_ts is None
    assert data["fail_closed"] is True
    assert data["healthy"] is False


def test_restart_loads_ledger_without_double_count(tmp_path: Path) -> None:
    """After restart, ledger identities prevent venue-history double counting."""
    sid = "binance.swap.x.btc.5m.v1"
    entry = _make_entry(sid)

    # Set up registry.
    doc = RegistryDocument(
        schema_version=1, defaults=RegistryDefaults(), accounts=[],
        strategies=[entry],
    )
    registry_path = tmp_path / "config" / "registry.toml"
    atomic_replace(registry_path, dump_registry(doc))

    now = datetime.now(UTC)
    fill = VenueFill(
        account_scope="binance-main",
        strategy_id=sid,
        symbol="BTCUSDT",
        order_id="order-1",
        fill_id="fill-1",
        occurred_at=now,
        side="sell",
        quantity=Decimal("1"),
        execution_price=Decimal("100"),
        gross_realized_pnl=Decimal("100"),
        commission=Decimal("1"),
        fees=Decimal("0"),
        quote_currency="USD",
    )

    config = _default_config()
    client = StubVenueClient(
        snapshot=_snapshot(timestamp=now),
        ledger_batches=(_ledger_batch(now, fills=(fill,)),),
    )

    # First run: 1 iteration.
    stop = threading.Event()
    run_forever(config, registry_path, tmp_path, client, stop, max_iterations=1)

    # Verify checkpoint was saved.
    ckpt_path = _checkpoint_file(tmp_path, config.risk_group)
    assert ckpt_path.exists()
    ckpt_data = json.loads(ckpt_path.read_text())
    assert ckpt_data["schema_version"] == 3
    first_state = json.loads(
        (tmp_path / "data/aggregator/crypto-main/state.json").read_text()
    )
    assert first_state["daily_realized_pnl"] == "99"

    # Second run: 1 iteration -- should NOT re-read the same event.
    run_forever(config, registry_path, tmp_path, client, stop, max_iterations=1)
    ckpt_data2 = json.loads(ckpt_path.read_text())
    assert ckpt_data2["schema_version"] == 3
    second_state = json.loads(
        (tmp_path / "data/aggregator/crypto-main/state.json").read_text()
    )
    assert second_state["daily_realized_pnl"] == "99"


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
                account_scope="binance-main",
                quote_currency="USD",
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


def test_run_forever_refuses_null_venue_for_live_capable_strategy(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    entry = _make_entry("binance.swap.x.btc.5m.v1", enabled=False)
    registry_path = _write_registry(tmp_path, [entry])
    config = _default_config()
    caplog.set_level(logging.CRITICAL, logger="aggregator")

    rc = run_forever(
        config,
        registry_path,
        tmp_path,
        NullVenueClient(),
        stop_event=threading.Event(),
        max_iterations=1,
    )

    assert rc == int(ExitCode.INVARIANT_VIOLATION)
    assert any(
        record.levelno == logging.CRITICAL
        and "NullVenueClient" in record.getMessage()
        and entry.id in record.getMessage()
        for record in caplog.records
    )
    state_path = tmp_path / "data" / "aggregator" / config.risk_group / "state.json"
    data = json.loads(state_path.read_text())
    assert data["healthy"] is False
    assert data["fail_closed"] is True


@pytest.mark.parametrize("state", [StrategyState.LIVE, StrategyState.TESTNET])
def test_main_refuses_null_venue_for_live_capable_strategy(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    state: StrategyState,
) -> None:
    entry = _make_entry("binance.swap.x.btc.5m.v1", state=state, enabled=False)
    registry_path = _write_registry(tmp_path, [entry])
    config_path = _write_risk_group_config(tmp_path)
    caplog.set_level(logging.CRITICAL, logger="aggregator")

    rc = main([
        "--risk-group",
        "crypto-main",
        "--project-root",
        str(tmp_path),
        "--registry",
        str(registry_path),
        "--config",
        str(config_path),
    ])

    assert rc == int(ExitCode.INVARIANT_VIOLATION)
    assert any(
        record.levelno == logging.CRITICAL
        and "NullVenueClient" in record.getMessage()
        and f"{entry.id}:{state.value}" in record.getMessage()
        for record in caplog.records
    )


def test_main_null_venue_refusal_publishes_fail_closed_state(tmp_path: Path) -> None:
    entry = _make_entry("binance.swap.x.btc.5m.v1", enabled=False)
    registry_path = _write_registry(tmp_path, [entry])
    config_path = _write_risk_group_config(tmp_path)
    state_path = tmp_path / "data" / "aggregator" / "crypto-main" / "state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(json.dumps({"healthy": True, "fail_closed": False}))

    result = main([
        "--risk-group",
        "crypto-main",
        "--project-root",
        str(tmp_path),
        "--registry",
        str(registry_path),
        "--config",
        str(config_path),
    ])

    assert result == int(ExitCode.INVARIANT_VIOLATION)
    published = json.loads(state_path.read_text())
    assert published["schema_version"] == 2
    assert published["healthy"] is False
    assert published["fail_closed"] is True
    assert published["metric_metadata"]["group_daily_pnl"]["source"] == "none"


def test_adapter_load_failure_publishes_fail_closed_state(tmp_path: Path) -> None:
    registry_path = _write_registry(tmp_path, [])
    config_path = _write_risk_group_config(tmp_path)
    state_path = tmp_path / "data" / "aggregator" / "crypto-main" / "state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(json.dumps({"healthy": True, "fail_closed": False}))

    result = main([
        "--risk-group",
        "crypto-main",
        "--project-root",
        str(tmp_path),
        "--registry",
        str(registry_path),
        "--config",
        str(config_path),
        "--venue-client",
        "src.risk.missing_adapter:Client",
    ])

    assert result == int(ExitCode.INVARIANT_VIOLATION)
    published = json.loads(state_path.read_text())
    assert published["schema_version"] == 2
    assert published["healthy"] is False
    assert published["fail_closed"] is True
    assert published["metric_metadata"]["group_daily_pnl"]["source"] == "none"


@pytest.mark.parametrize("failure", ["load", "path"])
def test_registry_failure_publishes_fail_closed_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    entry = _make_entry("binance.swap.x.btc.5m.v1", enabled=False)
    if failure == "path":
        entry = replace(entry, log_path="../outside/bot.jsonl")
        registry_path = _write_registry(tmp_path, [entry])
    else:
        registry_path = tmp_path / "config" / "registry.toml"
        registry_path.parent.mkdir(parents=True)
        registry_path.write_text("not valid toml = [")
    config_path = _write_risk_group_config(tmp_path)
    state_path = tmp_path / "data" / "aggregator" / "crypto-main" / "state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(json.dumps({"healthy": True, "fail_closed": False}))
    monkeypatch.setattr(
        aggregator_module,
        "load_venue_client",
        lambda spec: StubVenueClient(snapshot=_snapshot()),
    )

    result = main([
        "--risk-group",
        "crypto-main",
        "--project-root",
        str(tmp_path),
        "--registry",
        str(registry_path),
        "--config",
        str(config_path),
        "--venue-client",
        "src.risk.test_adapter:Client",
    ])

    assert result == int(ExitCode.INVARIANT_VIOLATION)
    published = json.loads(state_path.read_text())
    assert published["schema_version"] == 2
    assert published["healthy"] is False
    assert published["fail_closed"] is True
    assert published["metric_metadata"]["group_daily_pnl"]["source"] == "none"


def test_main_allows_null_venue_for_draft_strategies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = _make_entry(
        "binance.swap.x.btc.5m.v1",
        state=StrategyState.DRAFT,
        enabled=False,
    )
    registry_path = _write_registry(tmp_path, [entry])
    config_path = _write_risk_group_config(tmp_path)
    called: dict[str, object] = {}

    def fake_run_forever(
        config: AggregatorConfig,
        registry_path: Path,
        project_root: Path,
        client: NullVenueClient,
        stop_event: threading.Event,
    ) -> int:
        called["config"] = config
        called["registry_path"] = registry_path
        called["project_root"] = project_root
        called["client"] = client
        called["stop_event"] = stop_event
        return int(ExitCode.OK)

    monkeypatch.setattr("src.risk.aggregator.run_forever", fake_run_forever)

    rc = main([
        "--risk-group",
        "crypto-main",
        "--project-root",
        str(tmp_path),
        "--registry",
        str(registry_path),
        "--config",
        str(config_path),
    ])

    assert rc == int(ExitCode.OK)
    assert called["config"].risk_group == "crypto-main"
    assert called["registry_path"] == registry_path
    assert called["project_root"] == tmp_path.resolve()
    assert isinstance(called["client"], NullVenueClient)
    assert isinstance(called["stop_event"], threading.Event)


def test_main_registers_sigterm_on_non_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = _make_entry(
        "binance.swap.x.btc.5m.v1",
        state=StrategyState.DRAFT,
        enabled=False,
    )
    registry_path = _write_registry(tmp_path, [entry])
    config_path = _write_risk_group_config(tmp_path)
    registered: list[object] = []

    def fake_signal(signum: object, handler: object) -> None:
        registered.append(signum)

    def fake_run_forever(
        config: AggregatorConfig,
        registry_path: Path,
        project_root: Path,
        client: NullVenueClient,
        stop_event: threading.Event,
    ) -> int:
        return int(ExitCode.OK)

    monkeypatch.setattr("src.risk.aggregator.sys.platform", "linux")
    monkeypatch.setattr("src.risk.aggregator.signal.signal", fake_signal)
    monkeypatch.setattr("src.risk.aggregator.run_forever", fake_run_forever)

    rc = main([
        "--risk-group",
        "crypto-main",
        "--project-root",
        str(tmp_path),
        "--registry",
        str(registry_path),
        "--config",
        str(config_path),
    ])

    assert rc == int(ExitCode.OK)
    assert registered == [signal.SIGINT, signal.SIGTERM]


def test_main_registers_sigbreak_on_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = _make_entry(
        "binance.swap.x.btc.5m.v1",
        state=StrategyState.DRAFT,
        enabled=False,
    )
    registry_path = _write_registry(tmp_path, [entry])
    config_path = _write_risk_group_config(tmp_path)
    sigbreak = 21
    registered: list[object] = []

    def fake_signal(signum: object, handler: object) -> None:
        registered.append(signum)

    def fake_run_forever(
        config: AggregatorConfig,
        registry_path: Path,
        project_root: Path,
        client: NullVenueClient,
        stop_event: threading.Event,
    ) -> int:
        return int(ExitCode.OK)

    monkeypatch.setattr("src.risk.aggregator.sys.platform", "win32")
    monkeypatch.setattr("src.risk.aggregator.signal.SIGBREAK", sigbreak, raising=False)
    monkeypatch.setattr("src.risk.aggregator.signal.signal", fake_signal)
    monkeypatch.setattr("src.risk.aggregator.run_forever", fake_run_forever)

    rc = main([
        "--risk-group",
        "crypto-main",
        "--project-root",
        str(tmp_path),
        "--registry",
        str(registry_path),
        "--config",
        str(config_path),
    ])

    assert rc == int(ExitCode.OK)
    assert registered == [signal.SIGINT, sigbreak]


def test_conflicting_fill_identity_makes_reconciliation_fail_closed(
    tmp_path: Path,
) -> None:
    sid = "binance.swap.x.btcusdt.5m.v1"
    entry = _make_entry(sid)
    now = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)

    def make_fill(gross_pnl: str) -> VenueFill:
        return VenueFill(
            account_scope="binance-main",
            strategy_id=sid,
            symbol="BTCUSDT",
            order_id="order-1",
            fill_id="fill-1",
            occurred_at=now,
            side="sell",
            quantity=Decimal("1"),
            execution_price=Decimal("100"),
            gross_realized_pnl=Decimal(gross_pnl),
            commission=Decimal("1"),
            fees=Decimal("0"),
            quote_currency="USD",
        )

    client = StubVenueClient(
        snapshot=_snapshot(timestamp=now),
        ledger_batches=(
            _ledger_batch(now, cursor="cursor-1", fills=(make_fill("10"),)),
            _ledger_batch(now, cursor="cursor-2", fills=(make_fill("11"),)),
        ),
    )
    ledger = FillLedger(tmp_path / "ledger.sqlite3", "binance-main", "USD")
    state = AggregatorState(risk_group="crypto-main")
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
    assert state.daily_realized_pnl == Decimal("9")

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
    assert state.fail_closed is True
    assert state.daily_realized_pnl == Decimal("9")
    assert ledger.cursor == "cursor-1"


def test_existing_ledger_without_checkpoint_refuses_restart(tmp_path: Path) -> None:
    config = _default_config()
    ledger_path = tmp_path / "data/aggregator/crypto-main/ledger.sqlite3"
    FillLedger(ledger_path, "binance-main", "USD")
    registry_path = _write_registry(tmp_path, [])

    result = run_forever(
        config,
        registry_path,
        tmp_path,
        StubVenueClient(snapshot=_snapshot()),
        max_iterations=1,
    )

    assert result == int(ExitCode.INVARIANT_VIOLATION)
    state = json.loads(
        (tmp_path / "data/aggregator/crypto-main/state.json").read_text()
    )
    assert state["fail_closed"] is True
    assert state["healthy"] is False


def test_design_records_ledger_aggregator_exception() -> None:
    design_path = Path(__file__).resolve().parents[2] / ".claude" / "docs" / "DESIGN.md"
    design = design_path.read_text("utf-8")

    assert "ADR-005: Venue-Reconciled Risk Ledger" in design
    assert "explicit approved exception to ADR-004" in design
    assert "SQLite fill ledger" in design


def test_post_commit_accounting_exception_publishes_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    state = AggregatorState(risk_group="crypto-main")
    state.group_net_exposure = Decimal("50")
    state.group_gross_exposure = Decimal("50")
    ledger = FillLedger(tmp_path / "ledger.sqlite3", "binance-main", "USD")

    def fail_accounting(
        positions: object,
    ) -> tuple[Decimal, Decimal, int]:
        raise ArithmeticError("simulated post-commit accounting failure")

    monkeypatch.setattr(accounting_module, "compute_group_metrics", fail_accounting)
    reconcile_once(
        StubVenueClient(
            snapshot=_snapshot(timestamp=now),
            ledger_batches=(_ledger_batch(now),),
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

    assert ledger.generation == 1
    assert state.fail_closed is True
    assert state.consecutive_failures == 1
    assert state.group_net_exposure == Decimal("50")
    assert state.group_gross_exposure == Decimal("50")
    assert save_checkpoint(tmp_path / "checkpoint.json", state, {}, ledger=ledger) is False
    state_path = tmp_path / "state.json"
    publish_state(state_path, state, _default_config(), now_utc=now)
    payload = json.loads(state_path.read_text())
    assert payload["healthy"] is False
    assert payload["fail_closed"] is True
    assert payload["metric_metadata"]["group_daily_pnl"]["source"] == "none"


def test_aggregator_module_boundaries_are_bounded_and_inward() -> None:
    project_root = Path(__file__).parents[2]
    limits = {
        "aggregator.py": 600,
        "config.py": 900,
        "observations.py": 900,
        "accounting.py": 900,
        "persistence.py": 900,
        "publication.py": 900,
    }
    risk_dir = project_root / "src" / "risk"
    for filename, limit in limits.items():
        source = (risk_dir / filename).read_text()
        assert len(source.splitlines()) < limit
        if filename == "aggregator.py":
            continue
        tree = ast.parse(source)
        assert not any(
            (
                isinstance(node, ast.ImportFrom)
                and node.module == "src.risk.aggregator"
            )
            or (
                isinstance(node, ast.Import)
                and any(alias.name == "src.risk.aggregator" for alias in node.names)
            )
            for node in ast.walk(tree)
        )

    facade = ast.parse((risk_dir / "aggregator.py").read_text())
    definitions = {
        node.name
        for node in facade.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert definitions == {
        "_JsonFormatter",
        "_run_forever_locked",
        "_save_checkpoint_for_publication",
        "_utc_now",
        "main",
        "reconcile_once",
        "run_forever",
    }


def test_aggregator_public_reexports_remain_available() -> None:
    expected = {
        "AggregatorConfig": config_module.AggregatorConfig,
        "AggregatorState": accounting_module.AggregatorState,
        "NullVenueClient": observations_module.NullVenueClient,
        "VenuePosition": observations_module.VenuePosition,
        "load_checkpoint": persistence_module.load_checkpoint,
        "publish_state": publication_module.publish_state,
        "read_strategy_log_delta": observations_module.read_strategy_log_delta,
        "validate_state_metric_metadata": (
            publication_module.validate_state_metric_metadata
        ),
    }
    for name, owner in expected.items():
        assert getattr(aggregator_module, name) is owner
    assert isinstance(
        aggregator_module.load_venue_client(
            "src.risk.aggregator:NullVenueClient"
        ),
        observations_module.NullVenueClient,
    )


def test_adr_005_documents_aggregator_module_map() -> None:
    design = (
        Path(__file__).parents[2] / ".claude" / "docs" / "DESIGN.md"
    ).read_text()
    assert "Module map (risk-ledger-accounting-002)" in design
    for module in (
        "config.py",
        "observations.py",
        "accounting.py",
        "persistence.py",
        "publication.py",
        "aggregator.py",
    ):
        assert module in design
    assert "No extracted module imports `aggregator.py`" in design
