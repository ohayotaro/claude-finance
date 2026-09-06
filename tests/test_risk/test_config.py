"""Tests for risk aggregator configuration."""

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

@pytest.mark.parametrize(
    ("body", "message"),
    [
        (
            '[risk_groups.g]\naccount_scope = "acc"\n',
            "quote_currency",
        ),
        (
            '[risk_groups.g]\naccount_scope = "acc"\nquote_currency = "USD"\n'
            "poll_interval_s = 61\n",
            "poll_interval_s",
        ),
        (
            '[risk_groups.g]\naccount_scope = "acc"\nquote_currency = "USD"\n'
            "soft_cap_daily_loss_pct = 6\nhard_cap_daily_loss_pct = 5\n",
            "soft_cap",
        ),
        (
            '[risk_groups.g]\naccount_scope = "acc"\nquote_currency = "USD"\n'
            "accounting_cut_max_skew_s = 121\nhealth_window_s = 120\n",
            "accounting_cut_max_skew_s",
        ),
    ],
)
def test_load_aggregator_config_rejects_unsafe_values(
    tmp_path: Path,
    body: str,
    message: str,
) -> None:
    path = tmp_path / "risk_groups.toml"
    path.write_text(body)
    with pytest.raises(ValueError, match=message):
        load_aggregator_config(path, "g")


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("poll_interval_s", "inf"),
        ("soft_cap_daily_loss_pct", "nan"),
        ("hard_cap_daily_loss_pct", "inf"),
        ("margin_emergency_threshold", "nan"),
        ("health_window_s", "inf"),
        ("future_skew_tolerance_s", "nan"),
        ("accounting_cut_max_skew_s", "inf"),
        ("fail_closed_after_consecutive_failures", "inf"),
        ("malformed_log_quarantine_per_minute", "nan"),
    ],
)
def test_config_rejects_non_finite_values(
    tmp_path: Path, field_name: str, value: str
) -> None:
    path = tmp_path / "risk_groups.toml"
    path.write_text(
        '[risk_groups.safe-group]\naccount_scope = "acc"\nquote_currency = "USD"\n'
        f"{field_name} = {value}\n"
    )
    with pytest.raises(ValueError, match=field_name):
        load_aggregator_config(path, "safe-group")


def test_example_risk_groups_config_loads() -> None:
    config_path = Path(__file__).parents[2] / "config" / "risk_groups.toml"
    config = load_aggregator_config(config_path, "example-main")
    assert config.account_scope == "example-main"
    assert config.quote_currency == "USD"
    assert 0 < config.poll_interval_s <= 60
    assert config.future_skew_tolerance_s == 2.0
    assert config.accounting_cut_max_skew_s == config.poll_interval_s


def test_load_aggregator_config(tmp_path: Path) -> None:
    cfg = tmp_path / "risk_groups.toml"
    cfg.write_text(
        '[risk_groups.crypto-main]\n'
        'account_scope = "binance-main"\n'
        'quote_currency = "USD"\n'
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


def test_unsafe_risk_group_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "risk_groups.toml"
    path.write_text(
        '[risk_groups.safe-group]\naccount_scope = "acc"\nquote_currency = "USD"\n'
    )
    for unsafe in ("../escape", "/absolute", "Bad_Name", "two--hyphens"):
        with pytest.raises(ValueError, match="risk_group"):
            load_aggregator_config(path, unsafe)
        with pytest.raises(ValueError, match="risk_group"):
            _ledger_file(tmp_path, unsafe)
        with pytest.raises(ValueError, match="risk_group"):
            _state_file(tmp_path, unsafe)
        with pytest.raises(ValueError, match="risk_group"):
            _checkpoint_file(tmp_path, unsafe)

    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    aggregator_dir = tmp_path / "data" / "aggregator"
    aggregator_dir.parent.mkdir(parents=True)
    aggregator_dir.symlink_to(outside, target_is_directory=True)
    for resolver in (_ledger_file, _state_file, _checkpoint_file):
        with pytest.raises(ValueError, match="project root"):
            resolver(tmp_path, "safe-group")

    def unexpected_config_load(path: Path, risk_group: str) -> AggregatorConfig:
        raise AssertionError("main must validate risk_group before loading config")

    monkeypatch.setattr(
        "src.risk.aggregator.load_aggregator_config", unexpected_config_load
    )
    assert main(
        ["--risk-group", "../escape", "--project-root", str(tmp_path)]
    ) == int(ExitCode.INVARIANT_VIOLATION)
