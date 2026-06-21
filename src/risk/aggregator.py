"""Cross-strategy risk aggregator service.

Implements the contract in `.claude/rules/multi-strategy.md` sections 6 and 10:
reads strategies in a `risk_group` from the registry, polls venue authoritative
state, parses per-strategy JSONL logs for supplemental PnL, and publishes a
soft/hard-cap signal to `data/aggregator/{risk_group}/state.json`.

The aggregator never places orders. It only emits signals consumed by bots
(via the aggregator state file's `healthy`, `soft_cap`, `hard_cap` fields).
"""

from __future__ import annotations

import argparse
import contextlib
import importlib
import json
import logging
import os
import signal
import tempfile
import threading
import time
import tomllib
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from src.orchestrator.registry import (
    ExitCode,
    RegistryDocument,
    StrategyEntry,
    StrategyState,
    load_registry,
    validate_registry_relative_path,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

# ---------------------------------------------------------------------------
# Structured JSON logging formatter (MEDIUM-F)
# ---------------------------------------------------------------------------


class _JsonFormatter(logging.Formatter):
    """Emit one JSON object per line with ts, level, event, and risk_group."""

    def __init__(self, risk_group: str = "") -> None:
        super().__init__()
        self._risk_group = risk_group

    def format(self, record: logging.LogRecord) -> str:
        obj: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "event": record.getMessage(),
        }
        if self._risk_group:
            obj["risk_group"] = self._risk_group
        return json.dumps(obj, default=str)


logger = logging.getLogger("aggregator")

# ---------------------------------------------------------------------------
# Venue client module allowlist (HIGH-D)
# ---------------------------------------------------------------------------

VENUE_CLIENT_ALLOWED_PREFIXES: tuple[str, ...] = ("src.risk.",)

# Maximum bytes to read from a single strategy log per cycle (MEDIUM-G).
LOG_READ_CHUNK_SIZE: int = 4 * 1024 * 1024  # 4 MB

LIVE_CAPABLE_STATES: frozenset[StrategyState] = frozenset(
    {StrategyState.LIVE, StrategyState.TESTNET}
)


# ---------------------------------------------------------------------------
# Venue contract (Protocol so tests can stub)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VenuePosition:
    strategy_id: str | None
    symbol: str
    side: str
    size: Decimal
    entry_price: Decimal
    unrealized_pnl: Decimal


@dataclass(frozen=True, slots=True)
class VenueOrder:
    order_id: str
    strategy_id: str | None
    symbol: str
    side: str
    size: Decimal
    price: Decimal
    status: str


@dataclass(frozen=True, slots=True)
class VenueAccountSnapshot:
    account_scope: str
    balance: Decimal
    equity: Decimal
    margin_used: Decimal
    margin_ratio: Decimal
    timestamp: datetime


@runtime_checkable
class VenueClient(Protocol):
    def fetch_account_snapshot(self, account_scope: str) -> VenueAccountSnapshot: ...
    def fetch_group_positions(self, strategy_ids: Sequence[str]) -> Sequence[VenuePosition]: ...
    def fetch_open_orders(self, strategy_ids: Sequence[str]) -> Sequence[VenueOrder]: ...


class NullVenueClient:
    """Returns empty non-authoritative data for test/development setups only."""

    def fetch_account_snapshot(self, account_scope: str) -> VenueAccountSnapshot:
        return VenueAccountSnapshot(
            account_scope=account_scope,
            balance=Decimal("0"),
            equity=Decimal("0"),
            margin_used=Decimal("0"),
            margin_ratio=Decimal("0"),
            timestamp=datetime.now(UTC),
        )

    def fetch_group_positions(
        self, strategy_ids: Sequence[str]
    ) -> Sequence[VenuePosition]:
        return []

    def fetch_open_orders(self, strategy_ids: Sequence[str]) -> Sequence[VenueOrder]:
        return []


class VenueClientLoadError(Exception):
    """Raised when an explicit venue client spec cannot be loaded or validated."""


def load_venue_client(spec: str) -> VenueClient:
    """Import and instantiate a VenueClient from a dotted-path spec.

    The module portion of the spec is validated against
    ``VENUE_CLIENT_ALLOWED_PREFIXES`` before any import is attempted.
    This prevents arbitrary code execution from a malformed config.

    Args:
        spec: A string in ``module:ClassName`` form, e.g.
            ``"src.risk.venues.binance:BinanceVenueClient"``.

    Returns:
        An instance of the resolved class that satisfies the ``VenueClient``
        protocol.

    Raises:
        VenueClientLoadError: If the module prefix is not in the allowlist,
            the module cannot be imported, the class cannot be found, the
            instance fails the ``VenueClient`` protocol check, or
            instantiation (with no args) raises.
    """
    if ":" not in spec:
        raise VenueClientLoadError(
            f"venue client spec must be 'module:ClassName', got: {spec!r}"
        )
    module_path, class_name = spec.rsplit(":", 1)
    if not any(module_path.startswith(prefix) for prefix in VENUE_CLIENT_ALLOWED_PREFIXES):
        logger.critical(
            "venue client module %r does not match allowed prefixes %r -- "
            "refusing to import (fail-closed)",
            module_path,
            VENUE_CLIENT_ALLOWED_PREFIXES,
        )
        raise VenueClientLoadError(
            f"module {module_path!r} is not in the allowed prefix list "
            f"{VENUE_CLIENT_ALLOWED_PREFIXES!r}"
        )
    try:
        module = importlib.import_module(module_path)
    except Exception as exc:
        raise VenueClientLoadError(
            f"failed to import module {module_path!r}: {exc}"
        ) from exc
    cls = getattr(module, class_name, None)
    if cls is None:
        raise VenueClientLoadError(
            f"class {class_name!r} not found in module {module_path!r}"
        )
    try:
        instance = cls()
    except Exception as exc:
        raise VenueClientLoadError(
            f"failed to instantiate {spec!r}: {exc}"
        ) from exc
    if not isinstance(instance, VenueClient):
        missing = [
            name
            for name in ("fetch_account_snapshot", "fetch_group_positions", "fetch_open_orders")
            if not callable(getattr(instance, name, None))
        ]
        raise VenueClientLoadError(
            f"instance from {spec!r} does not satisfy VenueClient protocol; "
            f"missing or non-callable: {missing}"
        )
    return instance


def resolve_venue_client_spec(
    cli_arg: str | None,
    config_block: dict[str, Any] | None,
) -> str | None:
    """Determine the venue client spec from CLI arg or config.

    Precedence (highest first):
      1. ``cli_arg`` (``--venue-client`` on the command line)
      2. ``venue_client`` key in the risk-group config block
      3. ``None`` (fall back to ``NullVenueClient``)

    Args:
        cli_arg: Value of ``--venue-client`` CLI argument, or ``None``.
        config_block: The raw dict for this risk-group from
            ``risk_groups.toml``, or ``None``.

    Returns:
        The dotted-path spec string, or ``None`` if no spec was configured.
    """
    if cli_arg is not None:
        return cli_arg
    if config_block is not None:
        val = config_block.get("venue_client")
        if val is not None:
            return str(val)
    return None


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AggregatorConfig:
    risk_group: str
    account_scope: str = "default"
    poll_interval_s: float = 60.0
    soft_cap_daily_loss_pct: float = 3.0
    hard_cap_daily_loss_pct: float = 5.0
    margin_emergency_threshold: float = 0.95
    fail_closed_after_consecutive_failures: int = 5
    malformed_log_quarantine_per_minute: int = 100
    health_window_s: float = 120.0


class ConfigError(Exception):
    pass


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
    return AggregatorConfig(
        risk_group=risk_group,
        account_scope=str(block.get("account_scope", "default")),
        poll_interval_s=float(block.get("poll_interval_s", 60.0)),
        soft_cap_daily_loss_pct=float(block.get("soft_cap_daily_loss_pct", 3.0)),
        hard_cap_daily_loss_pct=float(block.get("hard_cap_daily_loss_pct", 5.0)),
        margin_emergency_threshold=float(block.get("margin_emergency_threshold", 0.95)),
        fail_closed_after_consecutive_failures=int(
            block.get("fail_closed_after_consecutive_failures", 5)
        ),
        malformed_log_quarantine_per_minute=int(
            block.get("malformed_log_quarantine_per_minute", 100)
        ),
        health_window_s=float(block.get("health_window_s", 120.0)),
    )


# ---------------------------------------------------------------------------
# Observation state
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class StrategyLogStatus:
    strategy_id: str
    log_offset: int = 0
    malformed_timestamps: deque[float] = field(default_factory=lambda: deque(maxlen=10_000))
    quarantined: bool = False


@dataclass(frozen=True, slots=True)
class LogParseResult:
    events: list[dict[str, Any]]
    malformed_count: int
    new_offset: int


@dataclass(slots=True)
class AggregatorState:
    risk_group: str
    last_success_ts: datetime | None = None
    consecutive_failures: int = 0
    fail_closed: bool = False
    soft_cap: bool = False
    hard_cap: bool = False
    margin_emergency: bool = False
    warnings: list[str] = field(default_factory=list)
    quarantined_strategies: set[str] = field(default_factory=set)
    last_snapshot: VenueAccountSnapshot | None = None
    group_net_exposure: Decimal = Decimal("0")
    group_gross_exposure: Decimal = Decimal("0")
    group_daily_pnl: Decimal = Decimal("0")
    open_position_count: int = 0
    open_order_count: int = 0
    # -- CRITICAL-A: proper daily PnL accounting --
    # Realized PnL accumulated from position_closed events in the current UTC day.
    daily_realized_pnl: Decimal = Decimal("0")
    # Latest unrealized PnL per (strategy_id, symbol) -- overwrite, not sum.
    latest_unrealized: dict[tuple[str, str], Decimal] = field(default_factory=dict)
    # Current UTC date for day-boundary detection.
    current_utc_date: date | None = None
    # -- CRITICAL-C: drawdown tracking --
    # Start-of-day equity baseline, set on first successful cycle of each UTC day.
    start_of_day_equity: Decimal | None = None
    # All-time high-water mark equity, persisted across days.
    high_water_mark: Decimal | None = None
    # Computed drawdown percentages (published in state dict).
    drawdown_sod_pct: Decimal = Decimal("0")
    drawdown_hwm_pct: Decimal = Decimal("0")


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def load_group_strategies(
    registry_doc: RegistryDocument, risk_group: str
) -> list[StrategyEntry]:
    """Strategies in this risk_group that are actively trading."""
    return [
        e
        for e in registry_doc.strategies
        if e.risk_group == risk_group and e.state in LIVE_CAPABLE_STATES and e.enabled
    ]


def _is_null_venue_client(client: VenueClient) -> bool:
    return isinstance(client, NullVenueClient)


def _live_capable_group_strategies(
    registry_doc: RegistryDocument, risk_group: str
) -> list[StrategyEntry]:
    """All live/testnet entries in a risk group, independent of enabled."""
    return [
        e
        for e in registry_doc.strategies
        if e.risk_group == risk_group and e.state in LIVE_CAPABLE_STATES
    ]


def _log_null_venue_live_capable_refusal(
    risk_group: str, strategies: Sequence[StrategyEntry]
) -> None:
    strategy_states = ", ".join(f"{entry.id}:{entry.state.value}" for entry in strategies)
    logger.critical(
        "refusing to start risk aggregator for risk_group=%s with NullVenueClient: "
        "live-capable strategies require authoritative venue reconciliation "
        "(strategy_states=%s)",
        risk_group,
        strategy_states,
    )


def read_strategy_log_delta(
    log_path: Path,
    status: StrategyLogStatus,
    *,
    quarantine_threshold: int,
    now: float | None = None,
    max_bytes: int = LOG_READ_CHUNK_SIZE,
) -> LogParseResult:
    """Tail the JSONL log from `status.log_offset`, parse, skip malformed lines.

    At most ``max_bytes`` (default 4 MB) are read per call. If the unread
    portion of the file is larger, the remainder will be picked up on the
    next cycle via the returned ``new_offset``.
    """
    if not log_path.exists():
        return LogParseResult(events=[], malformed_count=0, new_offset=status.log_offset)
    events: list[dict[str, Any]] = []
    malformed = 0
    current_offset = status.log_offset
    with log_path.open("rb") as fh:
        fh.seek(status.log_offset)
        remaining = fh.read(max_bytes)
    if not remaining:
        return LogParseResult(events=[], malformed_count=0, new_offset=status.log_offset)
    # Process only fully-terminated lines so a partial final write is retried later.
    last_newline = remaining.rfind(b"\n")
    if last_newline < 0:
        return LogParseResult(events=[], malformed_count=0, new_offset=status.log_offset)
    complete = remaining[: last_newline + 1]
    current_offset = status.log_offset + len(complete)
    ts_now = now if now is not None else time.time()
    for raw in complete.splitlines():
        if not raw.strip():
            continue
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            malformed += 1
            status.malformed_timestamps.append(ts_now)
            continue
        if not isinstance(event, dict) or not all(
            k in event for k in ("event", "strategy_id", "ts")
        ):
            malformed += 1
            status.malformed_timestamps.append(ts_now)
            continue
        events.append(event)
    # Prune malformed timestamps older than 60s.
    cutoff = ts_now - 60.0
    while status.malformed_timestamps and status.malformed_timestamps[0] < cutoff:
        status.malformed_timestamps.popleft()
    if not status.quarantined and len(status.malformed_timestamps) >= quarantine_threshold:
        status.quarantined = True
        logger.critical(
            "quarantining strategy due to malformed log rate: strategy_id=%s rate_per_minute=%d",
            status.strategy_id,
            len(status.malformed_timestamps),
        )
    if malformed:
        logger.warning(
            "malformed log lines skipped: strategy_id=%s count=%d total_recent=%d",
            status.strategy_id,
            malformed,
            len(status.malformed_timestamps),
        )
    return LogParseResult(events=events, malformed_count=malformed, new_offset=current_offset)


def compute_group_metrics(
    positions: Iterable[VenuePosition],
) -> tuple[Decimal, Decimal, int]:
    """Return (net_exposure, gross_exposure, position_count). Signs by side."""
    net = Decimal("0")
    gross = Decimal("0")
    count = 0
    for p in positions:
        notional = p.size * p.entry_price
        gross += abs(notional)
        net += notional if p.side == "long" else -notional
        count += 1
    return net, gross, count


def determine_signals(state: AggregatorState, config: AggregatorConfig) -> AggregatorState:
    """Apply threshold rules to mutate cap flags. Pure: returns the same instance."""
    snapshot = state.last_snapshot
    state.soft_cap = False
    state.hard_cap = False
    state.margin_emergency = False
    if snapshot is None or snapshot.balance == 0:
        return state
    daily_loss_pct = -(state.group_daily_pnl / snapshot.balance) * Decimal("100")
    if daily_loss_pct >= Decimal(str(config.hard_cap_daily_loss_pct)):
        state.hard_cap = True
        state.soft_cap = True
    elif daily_loss_pct >= Decimal(str(config.soft_cap_daily_loss_pct)):
        state.soft_cap = True
    if snapshot.margin_ratio >= Decimal(str(config.margin_emergency_threshold)):
        state.margin_emergency = True
    return state


# ---------------------------------------------------------------------------
# Reconciliation cycle
# ---------------------------------------------------------------------------


def _parse_event_ts(event: dict[str, Any]) -> datetime | None:
    """Best-effort parse of the ``ts`` field to a UTC datetime."""
    raw = event.get("ts")
    if raw is None:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except (ValueError, TypeError):
        return None


def _check_day_boundary(state: AggregatorState, today: date) -> None:
    """Reset daily accumulators when the UTC date rolls over."""
    if state.current_utc_date is not None and state.current_utc_date == today:
        return
    # Day boundary crossed (or first cycle ever).
    state.current_utc_date = today
    state.daily_realized_pnl = Decimal("0")
    state.latest_unrealized = {}
    # SoD equity baseline will be set on the first successful venue fetch
    # of the new day (in reconcile_once, after the snapshot arrives).
    state.start_of_day_equity = None
    logger.info("UTC day boundary: counters reset for %s", today.isoformat())


def reconcile_once(
    client: VenueClient,
    config: AggregatorConfig,
    strategies: list[StrategyEntry],
    state: AggregatorState,
    log_statuses: dict[str, StrategyLogStatus],
    project_root: Path,
    *,
    now_utc: datetime | None = None,
) -> AggregatorState:
    """Venue-authoritative pull + log delta read + threshold check.

    Encodes failure in state. Never raises on venue errors.
    """
    if now_utc is None:
        now_utc = datetime.now(UTC)
    _check_day_boundary(state, now_utc.date())
    using_null_venue = _is_null_venue_client(client)

    strategy_ids = [s.id for s in strategies]
    try:
        snapshot = client.fetch_account_snapshot(config.account_scope)
        positions = list(client.fetch_group_positions(strategy_ids))
        orders = list(client.fetch_open_orders(strategy_ids))
    except Exception as exc:
        state.consecutive_failures += 1
        msg = f"venue reconciliation failed (attempt {state.consecutive_failures}): {exc}"
        if state.consecutive_failures >= config.fail_closed_after_consecutive_failures:
            if not state.fail_closed:
                logger.critical("entering fail-closed: %s", msg)
            state.fail_closed = True
        elif state.consecutive_failures >= 3:
            logger.critical(msg)
        else:
            logger.warning(msg)
        return state

    state.consecutive_failures = 0
    state.fail_closed = False
    state.last_snapshot = snapshot
    state.last_success_ts = snapshot.timestamp
    net, gross, count = compute_group_metrics(positions)
    state.group_net_exposure = net
    state.group_gross_exposure = gross
    state.open_position_count = count
    state.open_order_count = len(orders)

    # -- CRITICAL-C: drawdown baselines --
    equity = snapshot.equity
    if state.start_of_day_equity is None and equity > 0:
        state.start_of_day_equity = equity
    if state.high_water_mark is None or equity > state.high_water_mark:
        state.high_water_mark = equity
    if state.start_of_day_equity and state.start_of_day_equity > 0:
        state.drawdown_sod_pct = (
            (equity - state.start_of_day_equity) / state.start_of_day_equity
        ) * Decimal("100")
    if state.high_water_mark and state.high_water_mark > 0:
        state.drawdown_hwm_pct = (
            (equity - state.high_water_mark) / state.high_water_mark
        ) * Decimal("100")

    # -- Read per-strategy log deltas (supplemental, NOT authoritative for caps). --
    quarantine_threshold = config.malformed_log_quarantine_per_minute
    today = now_utc.date()
    for s in strategies:
        if s.id not in log_statuses:
            log_statuses[s.id] = StrategyLogStatus(strategy_id=s.id)
        status = log_statuses[s.id]
        if status.quarantined:
            state.quarantined_strategies.add(s.id)
            continue
        try:
            full_log = validate_registry_relative_path(
                project_root, f"{s.log_path}/bot.jsonl", s.log_path,
            )
        except ValueError as exc:
            logger.error("path validation failed for %s: %s", s.id, exc)
            continue
        result = read_strategy_log_delta(
            full_log, status, quarantine_threshold=quarantine_threshold,
        )
        status.log_offset = result.new_offset
        # -- CRITICAL-A: correct PnL accounting --
        for event in result.events:
            event_ts = _parse_event_ts(event)
            if event.get("event") == "position_closed":
                # Only count realized PnL whose ts falls in the current UTC day.
                if event_ts is not None and event_ts.date() == today:
                    with contextlib.suppress(Exception):
                        state.daily_realized_pnl += Decimal(str(event.get("pnl", 0)))
            elif event.get("event") == "position_update":
                # unrealized_pnl is a LEVEL -- overwrite per (strategy, symbol).
                sid = str(event.get("strategy_id", ""))
                sym = str(event.get("symbol", ""))
                if sid and sym:
                    with contextlib.suppress(Exception):
                        state.latest_unrealized[(sid, sym)] = Decimal(
                            str(event.get("unrealized_pnl", 0))
                        )

    # Compute group_daily_pnl: realized (accumulated) + unrealized (latest levels).
    # When the venue snapshot provides authoritative unrealized PnL from
    # positions, prefer it for the group total.
    venue_unrealized = sum(
        (p.unrealized_pnl for p in positions), Decimal("0"),
    )
    if venue_unrealized != Decimal("0") or positions:
        # Venue has position data -- use its unrealized total.
        total_unrealized = venue_unrealized
    else:
        # No venue position data (NullVenueClient) -- fall back to log-derived.
        total_unrealized = sum(state.latest_unrealized.values(), Decimal("0"))
    state.group_daily_pnl = state.daily_realized_pnl + total_unrealized
    determine_signals(state, config)
    if using_null_venue:
        state.fail_closed = True
        state.last_success_ts = None
    return state


# ---------------------------------------------------------------------------
# Publishing
# ---------------------------------------------------------------------------


def _is_healthy(state: AggregatorState, config: AggregatorConfig) -> bool:
    if state.fail_closed or state.last_success_ts is None:
        return False
    age = datetime.now(UTC) - state.last_success_ts
    return age <= timedelta(seconds=config.health_window_s)


def state_to_dict(state: AggregatorState, config: AggregatorConfig) -> dict[str, Any]:
    return {
        "risk_group": state.risk_group,
        "healthy": _is_healthy(state, config),
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
        "open_position_count": state.open_position_count,
        "open_order_count": state.open_order_count,
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
        "config": {
            "soft_cap_daily_loss_pct": config.soft_cap_daily_loss_pct,
            "hard_cap_daily_loss_pct": config.hard_cap_daily_loss_pct,
            "margin_emergency_threshold": config.margin_emergency_threshold,
            "health_window_s": config.health_window_s,
        },
    }


def publish_state(path: Path, state: AggregatorState, config: AggregatorConfig) -> None:
    """Atomic JSON write."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state_to_dict(state, config), sort_keys=True).encode("utf-8")
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


# ---------------------------------------------------------------------------
# Checkpoint persistence (CRITICAL-B)
# ---------------------------------------------------------------------------


def _checkpoint_file(project_root: Path, risk_group: str) -> Path:
    """Checkpoint lives next to the published state file."""
    return project_root / "data" / "aggregator" / risk_group / "checkpoint.json"


def save_checkpoint(
    path: Path,
    state: AggregatorState,
    log_statuses: dict[str, StrategyLogStatus],
) -> None:
    """Atomically persist aggregator state for crash recovery.

    Uses the same temp-file + os.replace pattern as ``publish_state``.
    """
    offsets: dict[str, int] = {
        sid: ls.log_offset for sid, ls in log_statuses.items()
    }
    payload: dict[str, Any] = {
        "current_utc_date": (
            state.current_utc_date.isoformat()
            if state.current_utc_date is not None else None
        ),
        "daily_realized_pnl": str(state.daily_realized_pnl),
        "latest_unrealized": {
            f"{sid}\x00{sym}": str(val)
            for (sid, sym), val in state.latest_unrealized.items()
        },
        "start_of_day_equity": (
            str(state.start_of_day_equity)
            if state.start_of_day_equity is not None else None
        ),
        "high_water_mark": (
            str(state.high_water_mark)
            if state.high_water_mark is not None else None
        ),
        "consecutive_failures": state.consecutive_failures,
        "fail_closed": state.fail_closed,
        "log_offsets": offsets,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, sort_keys=True).encode("utf-8")
    with tempfile.NamedTemporaryFile(
        mode="wb",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as tmp:
        tmp_name = tmp.name
        try:
            tmp.write(data)
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


def load_checkpoint(
    path: Path,
    state: AggregatorState,
    log_statuses: dict[str, StrategyLogStatus],
) -> bool:
    """Restore aggregator state from a checkpoint file.

    Returns True if a checkpoint was loaded, False if missing or corrupt
    (a WARNING is logged on corruption; the caller starts fresh).
    """
    if not path.exists():
        return False
    try:
        raw = json.loads(path.read_text("utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("corrupt or unreadable checkpoint, starting fresh: %s", exc)
        return False
    try:
        saved_date_str = raw.get("current_utc_date")
        if saved_date_str is not None:
            state.current_utc_date = date.fromisoformat(saved_date_str)
        state.daily_realized_pnl = Decimal(raw.get("daily_realized_pnl", "0"))
        for key_str, val_str in raw.get("latest_unrealized", {}).items():
            parts = key_str.split("\x00", 1)
            if len(parts) == 2:
                state.latest_unrealized[(parts[0], parts[1])] = Decimal(val_str)
        sod = raw.get("start_of_day_equity")
        state.start_of_day_equity = Decimal(sod) if sod is not None else None
        hwm = raw.get("high_water_mark")
        state.high_water_mark = Decimal(hwm) if hwm is not None else None
        state.consecutive_failures = int(raw.get("consecutive_failures", 0))
        state.fail_closed = bool(raw.get("fail_closed", False))
        for sid, offset in raw.get("log_offsets", {}).items():
            log_statuses[sid] = StrategyLogStatus(
                strategy_id=sid, log_offset=int(offset),
            )
    except (ValueError, TypeError, KeyError) as exc:
        logger.warning("checkpoint parse error, starting fresh: %s", exc)
        # Reset any partially loaded state.
        state.current_utc_date = None
        state.daily_realized_pnl = Decimal("0")
        state.latest_unrealized = {}
        state.start_of_day_equity = None
        state.high_water_mark = None
        state.consecutive_failures = 0
        state.fail_closed = False
        log_statuses.clear()
        return False
    logger.info(
        "checkpoint loaded: date=%s realized=%s hwm=%s offsets=%d",
        state.current_utc_date,
        state.daily_realized_pnl,
        state.high_water_mark,
        len(log_statuses),
    )
    return True


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def _state_file(project_root: Path, risk_group: str) -> Path:
    return project_root / "data" / "aggregator" / risk_group / "state.json"


def run_forever(
    config: AggregatorConfig,
    registry_path: Path,
    project_root: Path,
    client: VenueClient,
    stop_event: threading.Event | None = None,
    *,
    max_iterations: int | None = None,
) -> int:
    """Reconcile every poll_interval_s. Returns 0 on clean shutdown."""
    state = AggregatorState(risk_group=config.risk_group)
    log_statuses: dict[str, StrategyLogStatus] = {}
    state_path = _state_file(project_root, config.risk_group)
    checkpoint_path = _checkpoint_file(project_root, config.risk_group)
    load_checkpoint(checkpoint_path, state, log_statuses)
    iterations = 0
    while True:
        if stop_event is not None and stop_event.is_set():
            break
        if max_iterations is not None and iterations >= max_iterations:
            break
        cycle_start = time.monotonic()
        try:
            doc = load_registry(registry_path)
        except Exception as exc:
            logger.error("registry load failed: %s", exc)
            publish_state(state_path, state, config)
            time.sleep(min(config.poll_interval_s, 5.0))
            iterations += 1
            continue
        live_capable = _live_capable_group_strategies(doc, config.risk_group)
        if _is_null_venue_client(client) and live_capable:
            _log_null_venue_live_capable_refusal(config.risk_group, live_capable)
            state.fail_closed = True
            publish_state(state_path, state, config)
            save_checkpoint(checkpoint_path, state, log_statuses)
            return int(ExitCode.INVARIANT_VIOLATION)
        strategies = load_group_strategies(doc, config.risk_group)
        state = reconcile_once(client, config, strategies, state, log_statuses, project_root)
        publish_state(state_path, state, config)
        save_checkpoint(checkpoint_path, state, log_statuses)
        iterations += 1
        elapsed = time.monotonic() - cycle_start
        sleep_for = max(0.0, config.poll_interval_s - elapsed)
        if stop_event is not None:
            stop_event.wait(sleep_for)
        else:
            time.sleep(sleep_for)
    # Final shutdown publish with healthy=false (last_success_ts is preserved but
    # bots should not trust an aggregator that has exited).
    state.fail_closed = True
    publish_state(state_path, state, config)
    save_checkpoint(checkpoint_path, state, log_statuses)
    return int(ExitCode.OK)


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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="risk.aggregator")
    parser.add_argument("--risk-group", required=True)
    parser.add_argument(
        "--project-root",
        default=os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()),
    )
    parser.add_argument("--registry", default=None)
    parser.add_argument("--config", default=None)
    parser.add_argument(
        "--venue-client",
        default=None,
        help=(
            "Dotted-path spec for the VenueClient implementation, e.g. "
            "'src.risk.venues.binance:BinanceVenueClient'. "
            "Overrides the 'venue_client' key in risk_groups.toml."
        ),
    )
    args = parser.parse_args(argv)

    project_root = Path(args.project_root).resolve()
    registry_path = (
        Path(args.registry) if args.registry else project_root / "config" / "registry.toml"
    )
    config_path = (
        Path(args.config) if args.config else project_root / "config" / "risk_groups.toml"
    )

    handler = logging.StreamHandler()
    handler.setFormatter(_JsonFormatter(risk_group=args.risk_group))
    logging.basicConfig(level=logging.INFO, handlers=[handler])

    try:
        config = load_aggregator_config(config_path, args.risk_group)
    except ConfigError as exc:
        logger.error("config error: %s", exc)
        return int(ExitCode.INVARIANT_VIOLATION)

    # Resolve and load the venue client.
    raw_block = _load_risk_group_block(config_path, args.risk_group)
    venue_spec = resolve_venue_client_spec(args.venue_client, raw_block)
    client: VenueClient
    if venue_spec is not None:
        try:
            client = load_venue_client(venue_spec)
        except VenueClientLoadError as exc:
            logger.critical(
                "failed to load venue client from spec %r: %s -- "
                "refusing to start (fail-closed)",
                venue_spec,
                exc,
            )
            return int(ExitCode.INVARIANT_VIOLATION)
        logger.info("venue client loaded from spec: %s", venue_spec)
    else:
        client = NullVenueClient()
        logger.warning(
            "no venue client configured; using NullVenueClient (empty data). "
            "Set --venue-client or 'venue_client' in risk_groups.toml for live use."
        )

    # Startup-time path validation for every strategy in this risk_group.
    try:
        doc = load_registry(registry_path)
    except Exception as exc:
        logger.error("registry load failed at startup: %s", exc)
        return int(ExitCode.INVARIANT_VIOLATION)
    live_capable = _live_capable_group_strategies(doc, config.risk_group)
    if _is_null_venue_client(client) and live_capable:
        _log_null_venue_live_capable_refusal(config.risk_group, live_capable)
        return int(ExitCode.INVARIANT_VIOLATION)
    for entry in load_group_strategies(doc, config.risk_group):
        try:
            validate_registry_relative_path(project_root, entry.log_path, "logs/strategies")
            validate_registry_relative_path(project_root, entry.state_path, "state/strategies")
            validate_registry_relative_path(project_root, entry.config_path, "config/strategies")
        except ValueError as exc:
            logger.error("path validation failed for %s: %s", entry.id, exc)
            return int(ExitCode.INVARIANT_VIOLATION)

    entry_count = len(load_group_strategies(doc, config.risk_group))
    if entry_count:
        logger.info(
            "aggregator starting for risk_group=%s (%d strategies)",
            config.risk_group,
            entry_count,
        )
    else:
        logger.warning(
            "aggregator starting with zero active strategies for risk_group=%s",
            config.risk_group,
        )

    stop_event = threading.Event()

    def _signal_handler(signum: int, frame: Any) -> None:  # noqa: ARG001
        logger.info("received signal %d, shutting down", signum)
        stop_event.set()

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    return run_forever(config, registry_path, project_root, client, stop_event)


if __name__ == "__main__":
    raise SystemExit(main())
