"""Shared factories for decomposed risk aggregator tests."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from src.orchestrator.registry import (
    RegistryDefaults,
    RegistryDocument,
    Runtime,
    StrategyEntry,
    StrategyState,
    atomic_replace,
    dump_registry,
)
from src.risk.config import AggregatorConfig
from src.risk.ledger import VenueLedgerBatch
from src.risk.observations import (
    VenueAccountSnapshot,
    VenueOrder,
    VenueOrdersObservation,
    VenuePosition,
    VenuePositionsObservation,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from src.risk.ledger import VenueFill


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
        account_scope="binance-main",
        quote_currency="USD",
        poll_interval_s=0.05,
        soft_cap_daily_loss_pct=3.0,
        hard_cap_daily_loss_pct=5.0,
        margin_emergency_threshold=0.95,
        fail_closed_after_consecutive_failures=5,
        malformed_log_quarantine_per_minute=100,
        health_window_s=120.0,
    )


def _write_registry(tmp_path: Path, entries: Sequence[StrategyEntry]) -> Path:
    doc = RegistryDocument(
        schema_version=1,
        defaults=RegistryDefaults(),
        accounts=[],
        strategies=list(entries),
    )
    registry_path = tmp_path / "config" / "registry.toml"
    atomic_replace(registry_path, dump_registry(doc))
    return registry_path


def _write_risk_group_config(tmp_path: Path, risk_group: str = "crypto-main") -> Path:
    config_path = tmp_path / "config" / "risk_groups.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        f"[risk_groups.{risk_group}]\n"
        'account_scope = "binance-main"\n'
        'quote_currency = "USD"\n'
        "poll_interval_s = 0.05\n",
    )
    return config_path


def _snapshot(
    balance: Decimal = Decimal("10000"),
    margin_ratio: Decimal = Decimal("0"),
    equity: Decimal | None = None,
    *,
    timestamp: datetime | None = None,
    quote_currency: str = "USD",
) -> VenueAccountSnapshot:
    eq = equity if equity is not None else balance
    return VenueAccountSnapshot(
        account_scope="binance-main",
        balance=balance,
        equity=eq,
        margin_used=balance * margin_ratio,
        margin_ratio=margin_ratio,
        timestamp=timestamp or datetime.now(UTC),
        quote_currency=quote_currency,
    )


class StubVenueClient:
    def __init__(
        self,
        snapshot: VenueAccountSnapshot,
        positions: Sequence[VenuePosition] = (),
        orders: Sequence[VenueOrder] = (),
        ledger_batches: Sequence[VenueLedgerBatch] = (),
        raise_count: int = 0,
        positions_as_of_cut: datetime | None = None,
    ) -> None:
        self._snapshot = snapshot
        self._positions = positions
        self._orders = orders
        self._ledger_batches = list(ledger_batches)
        self._raise_count = raise_count
        self._positions_as_of_cut = positions_as_of_cut
        self.call_count = 0

    def fetch_account_snapshot(self, account_scope: str) -> VenueAccountSnapshot:
        self.call_count += 1
        if self.call_count <= self._raise_count:
            raise RuntimeError(f"simulated venue failure {self.call_count}")
        return self._snapshot

    def fetch_group_positions(
        self, strategy_ids: Sequence[str]
    ) -> VenuePositionsObservation:
        if self._positions_as_of_cut is None:
            return VenuePositionsObservation(
                positions=tuple(self._positions),
                as_of=self._snapshot.timestamp,
                complete=True,
            )
        return VenuePositionsObservation(
            positions=tuple(self._positions),
            as_of=self._snapshot.timestamp,
            complete=True,
            as_of_cut=self._positions_as_of_cut,
        )

    def fetch_open_orders(
        self, strategy_ids: Sequence[str]
    ) -> VenueOrdersObservation:
        return VenueOrdersObservation(
            orders=tuple(self._orders),
            as_of=self._snapshot.timestamp,
            complete=True,
        )

    def fetch_ledger_batch(
        self,
        account_scope: str,
        strategy_ids: Sequence[str],
        cursor: str | None,
    ) -> VenueLedgerBatch:
        if self._ledger_batches:
            return self._ledger_batches.pop(0)
        now = self._snapshot.timestamp
        return VenueLedgerBatch(
            fills=(),
            cash_events=(),
            next_cursor=cursor or "cursor-empty",
            as_of=now,
            complete=True,
            authoritative=True,
        )


def _ledger_batch(
    as_of: datetime,
    *,
    cursor: str = "cursor-1",
    fills: tuple[VenueFill, ...] = (),
) -> VenueLedgerBatch:
    return VenueLedgerBatch(
        fills=fills,
        cash_events=(),
        next_cursor=cursor,
        as_of=as_of,
        complete=True,
        authoritative=True,
    )
