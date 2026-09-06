"""Regression tests for the venue-reconciled risk ledger."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from src.risk.ledger import (
    FillLedger,
    LedgerIdentityConflictError,
    LedgerSchemaError,
    LedgerValidationError,
    VenueCashEvent,
    VenueFill,
    VenueLedgerBatch,
)

if TYPE_CHECKING:
    from pathlib import Path


ACCOUNT = "binance-main"
STRATEGY = "binance.swap.x.btcusdt.5m.v1"
CURRENCY = "USD"


def _fill(
    *,
    order_id: str,
    fill_id: str,
    occurred_at: datetime,
    side: str,
    gross_realized_pnl: str,
    commission: str,
    fees: str,
) -> VenueFill:
    return VenueFill(
        account_scope=ACCOUNT,
        strategy_id=STRATEGY,
        symbol="BTCUSDT",
        order_id=order_id,
        fill_id=fill_id,
        occurred_at=occurred_at,
        side=side,
        quantity=Decimal("1"),
        execution_price=Decimal("100"),
        gross_realized_pnl=Decimal(gross_realized_pnl),
        commission=Decimal(commission),
        fees=Decimal(fees),
        quote_currency=CURRENCY,
    )


def _batch(
    *,
    cursor: str,
    as_of: datetime,
    fills: tuple[VenueFill, ...] = (),
    cash_events: tuple[VenueCashEvent, ...] = (),
) -> VenueLedgerBatch:
    return VenueLedgerBatch(
        fills=fills,
        cash_events=cash_events,
        next_cursor=cursor,
        as_of=as_of,
        complete=True,
        authoritative=True,
    )


def test_closed_round_trip_net_of_costs_and_funding_is_idempotent(
    tmp_path: Path,
) -> None:
    occurred_at = datetime(2026, 9, 5, 8, 0, tzinfo=UTC)
    opening = _fill(
        order_id="order-open",
        fill_id="fill-open",
        occurred_at=occurred_at,
        side="buy",
        gross_realized_pnl="0",
        commission="1.00",
        fees="0.50",
    )
    closing = _fill(
        order_id="order-close",
        fill_id="fill-close",
        occurred_at=occurred_at,
        side="sell",
        gross_realized_pnl="120.00",
        commission="1.25",
        fees="0.25",
    )
    funding = VenueCashEvent(
        account_scope=ACCOUNT,
        event_id="funding-1",
        strategy_id=STRATEGY,
        symbol="BTCUSDT",
        occurred_at=occurred_at,
        kind="funding",
        cash_delta=Decimal("-4.00"),
        realized_pnl_delta=Decimal("-4.00"),
        quote_currency=CURRENCY,
    )
    ledger_path = tmp_path / "ledger.sqlite3"
    ledger = FillLedger(ledger_path, ACCOUNT, CURRENCY)

    ledger.ingest_batch(
        _batch(
            cursor="cursor-1",
            as_of=occurred_at,
            fills=(opening, closing),
            cash_events=(funding,),
        ),
        {STRATEGY},
    )
    expected = Decimal("113.00")
    assert ledger.realized_pnl_for_day(occurred_at.date()) == expected

    ledger.ingest_batch(
        _batch(
            cursor="cursor-2",
            as_of=occurred_at,
            fills=(closing, opening, closing),
            cash_events=(funding, funding),
        ),
        {STRATEGY},
    )
    assert ledger.realized_pnl_for_day(occurred_at.date()) == expected


def test_cash_and_borrow_events_have_explicit_pnl_effects(tmp_path: Path) -> None:
    occurred_at = datetime(2026, 9, 5, 9, 0, tzinfo=UTC)
    events = (
        VenueCashEvent(
            account_scope=ACCOUNT,
            event_id="borrow-1",
            strategy_id=STRATEGY,
            symbol="BTCUSDT",
            occurred_at=occurred_at,
            kind="borrow_cost",
            cash_delta=Decimal("-1.50"),
            realized_pnl_delta=Decimal("-1.50"),
            quote_currency=CURRENCY,
        ),
        VenueCashEvent(
            account_scope=ACCOUNT,
            event_id="deposit-1",
            strategy_id=None,
            symbol=None,
            occurred_at=occurred_at,
            kind="deposit",
            cash_delta=Decimal("1000"),
            realized_pnl_delta=Decimal("0"),
            quote_currency=CURRENCY,
        ),
    )
    ledger = FillLedger(tmp_path / "ledger.sqlite3", ACCOUNT, CURRENCY)
    ledger.ingest_batch(
        _batch(cursor="cursor-1", as_of=occurred_at, cash_events=events),
        {STRATEGY},
    )
    assert ledger.realized_pnl_for_day(occurred_at.date()) == Decimal("-1.50")


def test_conflicting_duplicate_fill_identity_fails_closed(tmp_path: Path) -> None:
    occurred_at = datetime(2026, 9, 5, 10, 0, tzinfo=UTC)
    original = _fill(
        order_id="order-1",
        fill_id="fill-1",
        occurred_at=occurred_at,
        side="sell",
        gross_realized_pnl="10",
        commission="1",
        fees="0",
    )
    conflicting = _fill(
        order_id="order-1",
        fill_id="fill-1",
        occurred_at=occurred_at,
        side="sell",
        gross_realized_pnl="11",
        commission="1",
        fees="0",
    )
    ledger = FillLedger(tmp_path / "ledger.sqlite3", ACCOUNT, CURRENCY)
    ledger.ingest_batch(
        _batch(cursor="cursor-1", as_of=occurred_at, fills=(original,)),
        {STRATEGY},
    )

    with pytest.raises(LedgerIdentityConflictError, match="fill identity conflict"):
        ledger.ingest_batch(
            _batch(cursor="cursor-2", as_of=occurred_at, fills=(conflicting,)),
            {STRATEGY},
        )

    assert ledger.cursor == "cursor-1"
    assert ledger.realized_pnl_for_day(occurred_at.date()) == Decimal("9")


def test_ledger_restart_replay_does_not_double_count(tmp_path: Path) -> None:
    occurred_at = datetime(2026, 9, 5, 11, 0, tzinfo=UTC)
    fill = _fill(
        order_id="order-1",
        fill_id="fill-1",
        occurred_at=occurred_at,
        side="sell",
        gross_realized_pnl="25",
        commission="1",
        fees="0.5",
    )
    path = tmp_path / "ledger.sqlite3"
    FillLedger(path, ACCOUNT, CURRENCY).ingest_batch(
        _batch(cursor="cursor-1", as_of=occurred_at, fills=(fill,)),
        {STRATEGY},
    )

    restarted = FillLedger(path, ACCOUNT, CURRENCY)
    assert restarted.cursor == "cursor-1"
    restarted.ingest_batch(
        _batch(cursor="cursor-2", as_of=occurred_at, fills=(fill,)),
        {STRATEGY},
    )
    assert restarted.realized_pnl_for_day(occurred_at.date()) == Decimal("23.5")


def test_late_precheckpoint_fill_is_ingested_by_availability_cursor(
    tmp_path: Path,
) -> None:
    first_seen = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    late_occurred = datetime(2026, 9, 4, 23, 59, tzinfo=UTC)
    ledger_path = tmp_path / "ledger.sqlite3"
    ledger = FillLedger(ledger_path, ACCOUNT, CURRENCY)
    ledger.ingest_batch(
        _batch(cursor="cursor-1", as_of=first_seen),
        {STRATEGY},
    )
    ledger = FillLedger(ledger_path, ACCOUNT, CURRENCY)
    assert ledger.cursor == "cursor-1"
    late_fill = _fill(
        order_id="late-order",
        fill_id="late-fill",
        occurred_at=late_occurred,
        side="sell",
        gross_realized_pnl="30",
        commission="2",
        fees="0",
    )

    ledger.ingest_batch(
        _batch(
            cursor="cursor-2",
            as_of=first_seen,
            fills=(late_fill,),
        ),
        {STRATEGY},
    )
    assert ledger.cursor == "cursor-2"
    assert ledger.realized_pnl_for_day(date(2026, 9, 4)) == Decimal("28")
    assert ledger.realized_pnl_for_day(date(2026, 9, 5)) == Decimal("0")


def test_previous_utc_day_fill_arriving_today_is_not_today_pnl(
    tmp_path: Path,
) -> None:
    arrived_at = datetime(2026, 9, 5, 0, 1, tzinfo=UTC)
    fill = _fill(
        order_id="boundary-order",
        fill_id="boundary-fill",
        occurred_at=datetime(2026, 9, 4, 23, 59, 59, tzinfo=UTC),
        side="sell",
        gross_realized_pnl="50",
        commission="1",
        fees="1",
    )
    ledger = FillLedger(tmp_path / "ledger.sqlite3", ACCOUNT, CURRENCY)
    ledger.ingest_batch(
        _batch(cursor="cursor-1", as_of=arrived_at, fills=(fill,)),
        {STRATEGY},
    )
    assert ledger.realized_pnl_for_day(date(2026, 9, 4)) == Decimal("48")
    assert ledger.realized_pnl_for_day(date(2026, 9, 5)) == Decimal("0")


def test_unknown_or_incomplete_ledger_schema_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "ledger.sqlite3"
    connection = sqlite3.connect(path)
    with connection:
        connection.execute("CREATE TABLE ledger_metadata(key TEXT PRIMARY KEY, value TEXT)")
        connection.execute("PRAGMA user_version = 1")
    connection.close()

    with pytest.raises(LedgerSchemaError, match="invalid columns"):
        FillLedger(path, ACCOUNT, CURRENCY)

    assert path.exists()


@pytest.mark.parametrize("flag_name", ["complete", "authoritative"])
@pytest.mark.parametrize("invalid_value", ["false", 1, None])
def test_non_boolean_batch_flags_fail_closed(
    tmp_path: Path,
    flag_name: str,
    invalid_value: object,
) -> None:
    now = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    ledger = FillLedger(tmp_path / "ledger.sqlite3", ACCOUNT, CURRENCY)
    batch = replace(
        _batch(cursor="cursor-1", as_of=now),
        **{flag_name: invalid_value},
    )

    with pytest.raises(LedgerValidationError, match=flag_name):
        ledger.ingest_batch(batch, {STRATEGY})

    assert ledger.generation == 0
    assert ledger.cursor is None


def test_generator_ledger_batch_is_materialized_once(tmp_path: Path) -> None:
    now = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    fill = _fill(
        order_id="order-1",
        fill_id="fill-1",
        occurred_at=now,
        side="sell",
        gross_realized_pnl="10",
        commission="1",
        fees="0.5",
    )
    cash_event = VenueCashEvent(
        account_scope=ACCOUNT,
        event_id="funding-1",
        strategy_id=STRATEGY,
        symbol="BTCUSDT",
        occurred_at=now,
        kind="funding",
        cash_delta=Decimal("-2"),
        realized_pnl_delta=Decimal("-2"),
        quote_currency=CURRENCY,
    )
    batch = replace(
        _batch(cursor="cursor-1", as_of=now),
        fills=(record for record in (fill,)),
        cash_events=(record for record in (cash_event,)),
    )
    ledger = FillLedger(tmp_path / "ledger.sqlite3", ACCOUNT, CURRENCY)

    result = ledger.ingest_batch(batch, {STRATEGY})  # type: ignore[arg-type]

    assert result.inserted_fills == 1
    assert result.inserted_cash_events == 1
    assert ledger.cursor == "cursor-1"
    assert ledger.generation == 1
    assert ledger.realized_pnl_for_day(now.date()) == Decimal("6.5")


def test_ledger_accumulation_is_exact_for_supported_domain(tmp_path: Path) -> None:
    now = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    positive = _fill(
        order_id="a-order",
        fill_id="a-fill",
        occurred_at=now,
        side="sell",
        gross_realized_pnl="10000000000000000000000000000.01",
        commission="0",
        fees="0",
    )
    negative = _fill(
        order_id="b-order",
        fill_id="b-fill",
        occurred_at=now,
        side="sell",
        gross_realized_pnl="-10000000000000000000000000000.00",
        commission="0",
        fees="0",
    )
    totals: list[Decimal] = []

    for index, fills in enumerate(((positive, negative), (negative, positive))):
        ledger = FillLedger(tmp_path / f"ledger-{index}.sqlite3", ACCOUNT, CURRENCY)
        ledger.ingest_batch(
            _batch(cursor="cursor-1", as_of=now, fills=fills),
            {STRATEGY},
        )
        totals.append(ledger.realized_pnl_for_day(now.date()))

    assert totals == [Decimal("0.01"), Decimal("0.01")]


def test_daily_total_from_boundary_ledger_entries_is_queryable(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    fills = tuple(
        _fill(
            order_id=f"order-{index}",
            fill_id=f"fill-{index}",
            occurred_at=now,
            side="sell",
            gross_realized_pnl="1e40",
            commission="0",
            fees="0",
        )
        for index in range(10)
    )
    ledger = FillLedger(tmp_path / "ledger.sqlite3", ACCOUNT, CURRENCY)

    ledger.ingest_batch(
        _batch(cursor="cursor-1", as_of=now, fills=fills),
        {STRATEGY},
    )

    assert ledger.realized_pnl_for_day(now.date()) == Decimal("1e41")


@pytest.mark.parametrize(
    "damage",
    [
        "missing_generation",
        "missing_cursor_after_empty_batch",
        "rows_with_initial_generation",
        "missing_as_of",
    ],
)
def test_missing_or_inconsistent_ledger_metadata_is_refused(
    tmp_path: Path,
    damage: str,
) -> None:
    now = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    path = tmp_path / "ledger.sqlite3"
    ledger = FillLedger(path, ACCOUNT, CURRENCY)
    if damage == "missing_cursor_after_empty_batch":
        ledger.ingest_batch(_batch(cursor="cursor-1", as_of=now), {STRATEGY})
    elif damage in {"rows_with_initial_generation", "missing_as_of"}:
        fill = _fill(
            order_id="order-1",
            fill_id="fill-1",
            occurred_at=now,
            side="sell",
            gross_realized_pnl="10",
            commission="1",
            fees="0",
        )
        ledger.ingest_batch(
            _batch(cursor="cursor-1", as_of=now, fills=(fill,)),
            {STRATEGY},
        )

    connection = sqlite3.connect(path)
    with connection:
        if damage == "missing_generation":
            connection.execute("DELETE FROM ledger_metadata WHERE key = 'generation'")
        elif damage == "missing_cursor_after_empty_batch":
            connection.execute("DELETE FROM ledger_metadata WHERE key = 'cursor'")
        elif damage == "rows_with_initial_generation":
            connection.execute("DELETE FROM ledger_metadata WHERE key IN ('cursor', 'as_of')")
            connection.execute(
                "UPDATE ledger_metadata SET value = '0' WHERE key = 'generation'"
            )
        else:
            connection.execute("DELETE FROM ledger_metadata WHERE key = 'as_of'")
    connection.close()

    with pytest.raises(LedgerSchemaError, match="metadata"):
        FillLedger(path, ACCOUNT, CURRENCY)


def test_ledger_metadata_snapshot_binds_cursor_generation_and_as_of(
    tmp_path: Path,
) -> None:
    as_of = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
    ledger = FillLedger(tmp_path / "ledger.sqlite3", ACCOUNT, CURRENCY)
    ledger.ingest_batch(_batch(cursor="cursor-1", as_of=as_of), {STRATEGY})

    metadata = ledger.binding

    assert metadata.cursor == "cursor-1"
    assert metadata.generation == 1
    assert metadata.as_of == as_of
