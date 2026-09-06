"""Configuration and path policy for the risk aggregator."""

from __future__ import annotations

import math
import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.orchestrator.registry import StrategyState

LIVE_CAPABLE_STATES: frozenset[StrategyState] = frozenset(
    {StrategyState.LIVE, StrategyState.TESTNET}
)
RISK_VISIBLE_STATES: frozenset[StrategyState] = frozenset(
    {
        StrategyState.TESTNET,
        StrategyState.LIVE,
        StrategyState.DEPRECATED,
        StrategyState.RETIRED,
    }
)
RISK_GROUP_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

@dataclass(frozen=True, slots=True)
class AggregatorConfig:
    risk_group: str
    account_scope: str
    quote_currency: str
    poll_interval_s: float = 60.0
    soft_cap_daily_loss_pct: float = 3.0
    hard_cap_daily_loss_pct: float = 5.0
    margin_emergency_threshold: float = 0.95
    fail_closed_after_consecutive_failures: int = 5
    malformed_log_quarantine_per_minute: int = 100
    health_window_s: float = 120.0
    future_skew_tolerance_s: float = 2.0
    # ``None`` is resolved to ``poll_interval_s`` for direct construction.
    accounting_cut_max_skew_s: float | None = None


class ConfigError(ValueError):
    """Raised when risk-group configuration is absent or unsafe."""

    pass


def _validate_risk_group_slug(risk_group: str) -> None:
    if not isinstance(risk_group, str) or RISK_GROUP_SLUG_PATTERN.fullmatch(risk_group) is None:
        raise ConfigError(
            "risk_group must be a lowercase slug containing only alphanumeric "
            "segments separated by single hyphens"
        )


def _config_float(block: dict[str, Any], field_name: str, default: float) -> float:
    raw = block.get(field_name, default)
    if isinstance(raw, bool):
        raise ConfigError(f"{field_name} must be a finite number")
    try:
        value = float(raw)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ConfigError(f"{field_name} must be a finite number") from exc
    if not math.isfinite(value):
        raise ConfigError(f"{field_name} must be a finite number")
    return value


def _config_int(block: dict[str, Any], field_name: str, default: int) -> int:
    raw = block.get(field_name, default)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ConfigError(f"{field_name} must be a finite integer")
    if isinstance(raw, float) and (not math.isfinite(raw) or not raw.is_integer()):
        raise ConfigError(f"{field_name} must be a finite integer")
    return int(raw)


def load_aggregator_config(path: Path, risk_group: str) -> AggregatorConfig:
    """Read ``config/risk_groups.toml``; pick the block for *risk_group*.

    Threshold units:

    - ``soft_cap_daily_loss_pct`` / ``hard_cap_daily_loss_pct``: percentage
      values where ``3.0`` means 3 %. The aggregator computes
      ``-(daily_pnl / balance) * 100`` and compares against these.
    - ``margin_emergency_threshold``: a **fraction** where ``0.95`` means
      95 % margin usage. Compared directly against the venue snapshot's
      ``margin_ratio`` field.
    """
    _validate_risk_group_slug(risk_group)
    if not path.exists():
        raise ConfigError(f"risk_groups config missing: {path}")
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    blocks = data.get("risk_groups", {})
    if not isinstance(blocks, dict) or risk_group not in blocks:
        raise ConfigError(f"risk_group {risk_group!r} not defined in {path}")
    block = blocks[risk_group]
    if not isinstance(block, dict):
        raise ConfigError(f"risk_group {risk_group!r} must be a table")
    required_text = ("account_scope", "quote_currency")
    for field_name in required_text:
        value = block.get(field_name)
        if (
            not isinstance(value, str)
            or not value.strip()
            or value.strip() != value
        ):
            raise ConfigError(
                f"risk_group {risk_group!r} requires non-empty {field_name}"
            )
    poll_interval_s = _config_float(block, "poll_interval_s", 60.0)
    accounting_cut_max_skew_s = _config_float(
        block,
        "accounting_cut_max_skew_s",
        poll_interval_s,
    )
    config = AggregatorConfig(
        risk_group=risk_group,
        account_scope=str(block["account_scope"]),
        quote_currency=str(block["quote_currency"]),
        poll_interval_s=poll_interval_s,
        soft_cap_daily_loss_pct=_config_float(
            block, "soft_cap_daily_loss_pct", 3.0
        ),
        hard_cap_daily_loss_pct=_config_float(
            block, "hard_cap_daily_loss_pct", 5.0
        ),
        margin_emergency_threshold=_config_float(
            block, "margin_emergency_threshold", 0.95
        ),
        fail_closed_after_consecutive_failures=_config_int(
            block, "fail_closed_after_consecutive_failures", 5
        ),
        malformed_log_quarantine_per_minute=_config_int(
            block, "malformed_log_quarantine_per_minute", 100
        ),
        health_window_s=_config_float(block, "health_window_s", 120.0),
        future_skew_tolerance_s=_config_float(
            block, "future_skew_tolerance_s", 2.0
        ),
        accounting_cut_max_skew_s=accounting_cut_max_skew_s,
    )
    if not 0 < config.poll_interval_s <= 60:
        raise ConfigError("poll_interval_s must be greater than zero and at most 60")
    if not 0 < config.soft_cap_daily_loss_pct <= config.hard_cap_daily_loss_pct:
        raise ConfigError(
            "daily loss thresholds must satisfy 0 < soft_cap <= hard_cap"
        )
    if not 0 < config.margin_emergency_threshold <= 1:
        raise ConfigError("margin_emergency_threshold must be in (0, 1]")
    if config.fail_closed_after_consecutive_failures <= 0:
        raise ConfigError("fail_closed_after_consecutive_failures must be positive")
    if config.malformed_log_quarantine_per_minute <= 0:
        raise ConfigError("malformed_log_quarantine_per_minute must be positive")
    if config.health_window_s <= 0:
        raise ConfigError("health_window_s must be positive")
    if not 0 <= config.future_skew_tolerance_s <= 5:
        raise ConfigError("future_skew_tolerance_s must be in [0, 5]")
    if (
        config.accounting_cut_max_skew_s is None
        or not 0 <= config.accounting_cut_max_skew_s <= config.health_window_s
    ):
        raise ConfigError(
            "accounting_cut_max_skew_s must be in [0, health_window_s]"
        )
    return config


def _aggregator_file(project_root: Path, risk_group: str, filename: str) -> Path:
    """Resolve an aggregator artifact and prove it remains under project root."""
    _validate_risk_group_slug(risk_group)
    resolved_root = project_root.resolve()
    candidate = (resolved_root / "data" / "aggregator" / risk_group / filename).resolve()
    try:
        common = Path(os.path.commonpath((resolved_root, candidate)))
    except ValueError as exc:
        raise ConfigError("aggregator paths must remain under project root") from exc
    if common != resolved_root:
        raise ConfigError("aggregator paths must remain under project root")
    return candidate


def _ledger_file(project_root: Path, risk_group: str) -> Path:
    return _aggregator_file(project_root, risk_group, "ledger.sqlite3")


def _checkpoint_file(project_root: Path, risk_group: str) -> Path:
    """Checkpoint lives next to the published state file."""
    return _aggregator_file(project_root, risk_group, "checkpoint.json")


def _state_file(project_root: Path, risk_group: str) -> Path:
    return _aggregator_file(project_root, risk_group, "state.json")


def _load_risk_group_block(config_path: Path, risk_group: str) -> dict[str, Any]:
    """Read the raw TOML block for a risk group.

    Returns an empty dict if the file is missing or the group is absent.
    This is a best-effort helper for extracting optional fields (like
    ``venue_client``) that are not part of the typed ``AggregatorConfig``.
    """
    if not config_path.exists():
        return {}
    with config_path.open("rb") as fh:
        data = tomllib.load(fh)
    blocks = data.get("risk_groups", {})
    if not isinstance(blocks, dict):
        return {}
    block = blocks.get(risk_group)
    return block if isinstance(block, dict) else {}

