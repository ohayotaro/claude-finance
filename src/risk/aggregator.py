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
from datetime import UTC, datetime, timedelta
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

logger = logging.getLogger("aggregator")


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
    """Returns empty data. Used when no real venue integration is wired up."""

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

    Args:
        spec: A string in ``module:ClassName`` form, e.g.
            ``"src.risk.venues.binance:BinanceVenueClient"``.

    Returns:
        An instance of the resolved class that satisfies the ``VenueClient``
        protocol.

    Raises:
        VenueClientLoadError: If the module cannot be imported, the class
            cannot be found, the instance fails the ``VenueClient`` protocol
            check, or instantiation (with no args) raises.

    Note:
        The spec is loaded from repo-controlled config (CLI arg or
        ``risk_groups.toml``), so the arbitrary-import surface is accepted
        by design.
    """
    if ":" not in spec:
        raise VenueClientLoadError(
            f"venue client spec must be 'module:ClassName', got: {spec!r}"
        )
    module_path, class_name = spec.rsplit(":", 1)
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
    """Read `config/risk_groups.toml`; pick the block for risk_group."""
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


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def load_group_strategies(
    registry_doc: RegistryDocument, risk_group: str
) -> list[StrategyEntry]:
    """Strategies in this risk_group that are actively trading."""
    active = {StrategyState.TESTNET, StrategyState.LIVE}
    return [
        e
        for e in registry_doc.strategies
        if e.risk_group == risk_group and e.state in active and e.enabled
    ]


def read_strategy_log_delta(
    log_path: Path,
    status: StrategyLogStatus,
    *,
    quarantine_threshold: int,
    now: float | None = None,
) -> LogParseResult:
    """Tail the JSONL log from `status.log_offset`, parse, skip malformed lines."""
    if not log_path.exists():
        return LogParseResult(events=[], malformed_count=0, new_offset=status.log_offset)
    events: list[dict[str, Any]] = []
    malformed = 0
    current_offset = status.log_offset
    with log_path.open("rb") as fh:
        fh.seek(status.log_offset)
        remaining = fh.read()
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
        if not isinstance(event, dict) or "event" not in event or "strategy_id" not in event:
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


def reconcile_once(
    client: VenueClient,
    config: AggregatorConfig,
    strategies: list[StrategyEntry],
    state: AggregatorState,
    log_statuses: dict[str, StrategyLogStatus],
    project_root: Path,
) -> AggregatorState:
    """Venue-authoritative pull + log delta read + threshold check.

    Encodes failure in state. Never raises on venue errors.
    """
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

    # Read per-strategy log deltas (supplemental, NOT authoritative for caps).
    quarantine_threshold = config.malformed_log_quarantine_per_minute
    daily_pnl = Decimal("0")
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
        # Sum unrealized + realized pnl from position_update / position_closed events.
        for event in result.events:
            if event.get("event") == "position_closed":
                with contextlib.suppress(Exception):
                    daily_pnl += Decimal(str(event.get("pnl", 0)))
            elif event.get("event") == "position_update":
                with contextlib.suppress(Exception):
                    daily_pnl += Decimal(str(event.get("unrealized_pnl", 0)))
    state.group_daily_pnl = daily_pnl
    determine_signals(state, config)
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
        "open_position_count": state.open_position_count,
        "open_order_count": state.open_order_count,
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
        strategies = load_group_strategies(doc, config.risk_group)
        state = reconcile_once(client, config, strategies, state, log_statuses, project_root)
        publish_state(state_path, state, config)
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

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

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
