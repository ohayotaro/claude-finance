"""Durable, venue-authoritative fill and cash-event ledger.

The ledger stores normalized venue records using stable identities. It does
not infer realized profit and loss from trades: venue adapters must supply
gross realized PnL and explicit cost/cash effects in the configured quote
currency.
"""

from __future__ import annotations

import contextlib
import sqlite3
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Context, Decimal, Inexact, InvalidOperation, Overflow, Rounded, localcontext
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

LEDGER_SCHEMA_VERSION = 1
# Venue-normalized inputs and derived accounting values have separate bounds.
# Inputs are limited to adjusted exponent/scale 40. Exact products, totals, and
# persisted aggregate values may grow to adjusted exponent/scale 100.
DECIMAL_INPUT_MAX_ADJUSTED_EXPONENT = 40
DECIMAL_INPUT_MAX_SCALE = 40
DECIMAL_DERIVED_MAX_ADJUSTED_EXPONENT = 100
DECIMAL_DERIVED_MAX_SCALE = 100
# A supported input can carry 81 coefficient digits and a product can carry
# 162. This leaves 94 further significant digits for exact accumulation.
# Any operation exceeding that headroom traps instead of silently rounding.
DECIMAL_ARITHMETIC_PRECISION = 256
_DECIMAL_ARITHMETIC_CONTEXT = Context(prec=DECIMAL_ARITHMETIC_PRECISION)
for _decimal_signal in (Inexact, Rounded, Overflow, InvalidOperation):
    _DECIMAL_ARITHMETIC_CONTEXT.traps[_decimal_signal] = True


class LedgerError(Exception):
    """Base class for ledger failures that must make reconciliation fail closed."""


class LedgerSchemaError(LedgerError):
    """Raised when an existing ledger has an unknown or invalid schema."""


class LedgerValidationError(LedgerError):
    """Raised when a venue ledger batch violates the normalized contract."""


class LedgerIdentityConflictError(LedgerError):
    """Raised when a stable identity is replayed with different contents."""


@contextlib.contextmanager
def decimal_arithmetic_context() -> Iterator[Context]:
    """Provide deterministic exact arithmetic for the supported input domain."""
    with localcontext(_DECIMAL_ARITHMETIC_CONTEXT) as arithmetic_context:
        yield arithmetic_context


@dataclass(frozen=True, slots=True)
class VenueFill:
    """One normalized venue fill with authoritative realized PnL fields."""

    account_scope: str
    strategy_id: str
    symbol: str
    order_id: str
    fill_id: str
    occurred_at: datetime
    side: str
    quantity: Decimal
    execution_price: Decimal
    gross_realized_pnl: Decimal
    commission: Decimal
    fees: Decimal
    quote_currency: str


@dataclass(frozen=True, slots=True)
class VenueCashEvent:
    """One normalized funding, borrow, transfer, or adjustment event."""

    account_scope: str
    event_id: str
    strategy_id: str | None
    symbol: str | None
    occurred_at: datetime
    kind: str
    cash_delta: Decimal
    realized_pnl_delta: Decimal
    quote_currency: str


@dataclass(frozen=True, slots=True)
class VenueLedgerBatch:
    """Gap-free records newly visible after a venue history cursor."""

    fills: tuple[VenueFill, ...]
    cash_events: tuple[VenueCashEvent, ...]
    next_cursor: str
    as_of: datetime
    complete: bool
    authoritative: bool = True


@dataclass(frozen=True, slots=True)
class LedgerIngestResult:
    """Counts of newly persisted records; replays are excluded."""

    inserted_fills: int
    inserted_cash_events: int


@dataclass(frozen=True, slots=True)
class LedgerBinding:
    """Atomic metadata snapshot for the latest committed ledger batch."""

    cursor: str | None
    generation: int
    as_of: datetime | None


def _utc_text(value: datetime, field_name: str) -> tuple[str, str]:
    if value.tzinfo is None or value.utcoffset() is None:
        raise LedgerValidationError(f"{field_name} must be timezone-aware")
    normalized = value.astimezone(UTC)
    return normalized.isoformat(timespec="microseconds"), normalized.date().isoformat()


def _bounded_decimal_text(
    value: Decimal,
    field_name: str,
    *,
    max_adjusted_exponent: int,
    max_scale: int,
) -> str:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise LedgerValidationError(f"{field_name} must be finite")
    exponent = value.as_tuple().exponent
    if (
        abs(value.adjusted()) > max_adjusted_exponent
        or not isinstance(exponent, int)
        or abs(exponent) > max_scale
    ):
        raise LedgerValidationError(
            f"{field_name} is outside the supported Decimal range"
        )
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in {"", "-0"}:
        return "0"
    return text


def _decimal_text(value: Decimal, field_name: str) -> str:
    """Serialize one venue-normalized input within the input domain."""
    return _bounded_decimal_text(
        value,
        field_name,
        max_adjusted_exponent=DECIMAL_INPUT_MAX_ADJUSTED_EXPONENT,
        max_scale=DECIMAL_INPUT_MAX_SCALE,
    )


def _derived_decimal_text(value: Decimal, field_name: str) -> str:
    """Validate an exact derived value within the wider aggregate domain."""
    return _bounded_decimal_text(
        value,
        field_name,
        max_adjusted_exponent=DECIMAL_DERIVED_MAX_ADJUSTED_EXPONENT,
        max_scale=DECIMAL_DERIVED_MAX_SCALE,
    )


def _required_text(value: str, field_name: str) -> str:
    if not value or value.strip() != value or "\x00" in value:
        raise LedgerValidationError(f"{field_name} must be a non-empty normalized string")
    return value


class FillLedger:
    """SQLite-backed authoritative record ledger for one account and currency."""

    def __init__(self, path: Path, account_scope: str, quote_currency: str) -> None:
        self.path = path
        self.account_scope = _required_text(account_scope, "account_scope")
        self.quote_currency = _required_text(quote_currency, "quote_currency")
        self.existed_before_open = path.exists()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_or_validate()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize_or_validate(self) -> None:
        try:
            connection = self._connect()
            try:
                version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                if version == 0 and not self.existed_before_open:
                    self._create_schema(connection)
                elif version != LEDGER_SCHEMA_VERSION:
                    raise LedgerSchemaError(
                        f"unsupported ledger schema version {version}; "
                        f"expected {LEDGER_SCHEMA_VERSION}"
                    )
                self._validate_schema(connection)
                self._validate_metadata(connection)
            finally:
                connection.close()
        except LedgerError:
            raise
        except sqlite3.DatabaseError as exc:
            raise LedgerSchemaError(f"invalid or corrupt ledger: {exc}") from exc

    @staticmethod
    def _validate_schema(connection: sqlite3.Connection) -> None:
        integrity = connection.execute("PRAGMA quick_check").fetchone()
        if integrity is None or integrity[0] != "ok":
            raise LedgerSchemaError("ledger integrity check failed")
        expected_columns = {
            "ledger_metadata": ("key", "value"),
            "fills": (
                "account_scope",
                "strategy_id",
                "symbol",
                "order_id",
                "fill_id",
                "occurred_at",
                "occurred_date",
                "side",
                "quantity",
                "execution_price",
                "gross_realized_pnl",
                "commission",
                "fees",
                "quote_currency",
            ),
            "cash_events": (
                "account_scope",
                "event_id",
                "strategy_id",
                "symbol",
                "occurred_at",
                "occurred_date",
                "kind",
                "cash_delta",
                "realized_pnl_delta",
                "quote_currency",
            ),
        }
        expected_primary_keys = {
            "ledger_metadata": {"key": 1},
            "fills": {
                "account_scope": 1,
                "strategy_id": 2,
                "symbol": 3,
                "order_id": 4,
                "fill_id": 5,
            },
            "cash_events": {"account_scope": 1, "event_id": 2},
        }
        for table_name, columns in expected_columns.items():
            rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
            actual_columns = tuple(str(row[1]) for row in rows)
            if actual_columns != columns:
                raise LedgerSchemaError(f"ledger table {table_name} has invalid columns")
            primary_keys = {
                str(row[1]): int(row[5]) for row in rows if int(row[5]) > 0
            }
            if primary_keys != expected_primary_keys[table_name]:
                raise LedgerSchemaError(
                    f"ledger table {table_name} has invalid primary key"
                )

    def _create_schema(self, connection: sqlite3.Connection) -> None:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        with connection:
            connection.execute(
                """
                CREATE TABLE ledger_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE fills (
                    account_scope TEXT NOT NULL,
                    strategy_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    order_id TEXT NOT NULL,
                    fill_id TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    occurred_date TEXT NOT NULL,
                    side TEXT NOT NULL,
                    quantity TEXT NOT NULL,
                    execution_price TEXT NOT NULL,
                    gross_realized_pnl TEXT NOT NULL,
                    commission TEXT NOT NULL,
                    fees TEXT NOT NULL,
                    quote_currency TEXT NOT NULL,
                    PRIMARY KEY (
                        account_scope, strategy_id, symbol, order_id, fill_id
                    )
                ) WITHOUT ROWID
                """
            )
            connection.execute(
                """
                CREATE TABLE cash_events (
                    account_scope TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    strategy_id TEXT,
                    symbol TEXT,
                    occurred_at TEXT NOT NULL,
                    occurred_date TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    cash_delta TEXT NOT NULL,
                    realized_pnl_delta TEXT NOT NULL,
                    quote_currency TEXT NOT NULL,
                    PRIMARY KEY (account_scope, event_id)
                ) WITHOUT ROWID
                """
            )
            connection.execute(
                "CREATE INDEX fills_occurred_date_idx ON fills(occurred_date)"
            )
            connection.execute(
                "CREATE INDEX cash_events_occurred_date_idx "
                "ON cash_events(occurred_date)"
            )
            connection.executemany(
                "INSERT INTO ledger_metadata(key, value) VALUES (?, ?)",
                (
                    ("account_scope", self.account_scope),
                    ("quote_currency", self.quote_currency),
                    ("generation", "0"),
                ),
            )
            connection.execute(f"PRAGMA user_version = {LEDGER_SCHEMA_VERSION}")

    def _validate_metadata(self, connection: sqlite3.Connection) -> None:
        try:
            rows = connection.execute(
                "SELECT key, value FROM ledger_metadata"
            ).fetchall()
        except sqlite3.DatabaseError as exc:
            raise LedgerSchemaError(f"ledger metadata is unavailable: {exc}") from exc
        if not all(isinstance(key, str) and isinstance(value, str) for key, value in rows):
            raise LedgerSchemaError("ledger metadata keys and values must be text")
        metadata = dict(rows)
        expected = {
            "account_scope": self.account_scope,
            "quote_currency": self.quote_currency,
        }
        if metadata.get("account_scope") != expected["account_scope"]:
            raise LedgerSchemaError("ledger account_scope does not match configuration")
        if metadata.get("quote_currency") != expected["quote_currency"]:
            raise LedgerSchemaError("ledger quote_currency does not match configuration")
        raw_generation = metadata.get("generation")
        if raw_generation is None:
            raise LedgerSchemaError("ledger generation metadata is missing")
        try:
            generation = int(raw_generation)
        except ValueError as exc:
            raise LedgerSchemaError("ledger generation metadata is invalid") from exc
        if generation < 0 or str(generation) != raw_generation:
            raise LedgerSchemaError("ledger generation metadata is invalid")

        fill_count = int(connection.execute("SELECT COUNT(*) FROM fills").fetchone()[0])
        cash_event_count = int(
            connection.execute("SELECT COUNT(*) FROM cash_events").fetchone()[0]
        )
        has_records = fill_count > 0 or cash_event_count > 0
        cursor = metadata.get("cursor")
        raw_as_of = metadata.get("as_of")
        if generation == 0:
            if has_records or cursor is not None or raw_as_of is not None:
                raise LedgerSchemaError(
                    "ledger metadata is inconsistent with initial generation"
                )
            return
        if cursor is None or not cursor or cursor.strip() != cursor or "\x00" in cursor:
            raise LedgerSchemaError("ledger cursor metadata is missing or invalid")
        if raw_as_of is None:
            raise LedgerSchemaError("ledger as_of metadata is missing")
        try:
            as_of = datetime.fromisoformat(raw_as_of)
        except ValueError as exc:
            raise LedgerSchemaError("ledger as_of metadata is invalid") from exc
        if (
            as_of.tzinfo is None
            or as_of.utcoffset() is None
            or as_of.utcoffset() != timedelta(0)
        ):
            raise LedgerSchemaError("ledger as_of metadata must be UTC")

    @property
    def cursor(self) -> str | None:
        """Return the last transactionally committed venue history cursor."""
        return self.binding.cursor

    @property
    def generation(self) -> int:
        """Return the monotonically increasing committed-batch generation."""
        return self.binding.generation

    @property
    def binding(self) -> LedgerBinding:
        """Read cursor, generation, and as-of time from one SQLite snapshot."""
        try:
            connection = self._connect()
            try:
                self._validate_metadata(connection)
                rows = connection.execute(
                    "SELECT key, value FROM ledger_metadata "
                    "WHERE key IN ('cursor', 'generation', 'as_of')"
                ).fetchall()
            finally:
                connection.close()
        except sqlite3.DatabaseError as exc:
            raise LedgerError(f"failed to read ledger binding: {exc}") from exc
        metadata = {str(key): str(value) for key, value in rows}
        raw_generation = metadata.get("generation")
        if raw_generation is None:
            raise LedgerSchemaError("ledger generation metadata is missing")
        try:
            generation = int(raw_generation)
        except ValueError as exc:
            raise LedgerError("ledger generation metadata is invalid") from exc
        if generation < 0 or str(generation) != raw_generation:
            raise LedgerError("ledger generation metadata is invalid")
        raw_as_of = metadata.get("as_of")
        as_of = datetime.fromisoformat(raw_as_of) if raw_as_of is not None else None
        return LedgerBinding(
            cursor=metadata.get("cursor"),
            generation=generation,
            as_of=as_of,
        )

    @property
    def as_of(self) -> datetime | None:
        """Return the most recent authoritative batch timestamp."""
        return self.binding.as_of

    def ingest_batch(
        self,
        batch: VenueLedgerBatch,
        allowed_strategy_ids: set[str],
    ) -> LedgerIngestResult:
        """Atomically insert a complete batch and advance its venue cursor.

        Exact replays are no-ops. A reused fill or cash-event identity with
        different normalized contents aborts the whole transaction.
        """
        batch = self._materialize_batch(batch)
        batch_as_of, _ = self._validate_batch(batch, allowed_strategy_ids)
        inserted_fills = 0
        inserted_cash_events = 0
        try:
            connection = self._connect()
            connection.execute("PRAGMA synchronous = FULL")
            try:
                with connection:
                    self._validate_metadata(connection)
                    for fill in batch.fills:
                        inserted_fills += self._insert_fill(connection, fill)
                    for event in batch.cash_events:
                        inserted_cash_events += self._insert_cash_event(connection, event)
                    previous_as_of = self._metadata_value_in_connection(
                        connection, "as_of"
                    )
                    effective_as_of = batch_as_of
                    if previous_as_of is not None:
                        previous = datetime.fromisoformat(previous_as_of)
                        if batch_as_of < previous:
                            raise LedgerValidationError(
                                "ledger batch as_of regressed behind the committed cursor"
                            )
                    connection.execute(
                        "INSERT INTO ledger_metadata(key, value) VALUES ('cursor', ?) "
                        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (batch.next_cursor,),
                    )
                    connection.execute(
                        "INSERT INTO ledger_metadata(key, value) VALUES ('as_of', ?) "
                        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (effective_as_of.isoformat(timespec="microseconds"),),
                    )
                    raw_generation = self._metadata_value_in_connection(
                        connection, "generation"
                    )
                    try:
                        generation = int(raw_generation or "0")
                    except ValueError as exc:
                        raise LedgerValidationError(
                            "ledger generation metadata is invalid"
                        ) from exc
                    if generation < 0 or (
                        raw_generation is not None
                        and str(generation) != raw_generation
                    ):
                        raise LedgerValidationError(
                            "ledger generation metadata is invalid"
                        )
                    connection.execute(
                        "INSERT INTO ledger_metadata(key, value) "
                        "VALUES ('generation', ?) "
                        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (str(generation + 1),),
                    )
            finally:
                connection.close()
        except LedgerError:
            raise
        except sqlite3.DatabaseError as exc:
            raise LedgerError(f"ledger batch transaction failed: {exc}") from exc
        return LedgerIngestResult(inserted_fills, inserted_cash_events)

    @staticmethod
    def _materialize_batch(batch: VenueLedgerBatch) -> VenueLedgerBatch:
        """Consume each adapter collection once before validation and mutation."""
        if not isinstance(batch, VenueLedgerBatch):
            raise LedgerValidationError("ledger batch has an invalid type")
        try:
            fills = tuple(batch.fills)
            cash_events = tuple(batch.cash_events)
        except Exception as exc:
            raise LedgerValidationError(
                "ledger batch collections must be finite iterables"
            ) from exc
        return replace(batch, fills=fills, cash_events=cash_events)

    def _validate_batch(
        self,
        batch: VenueLedgerBatch,
        allowed_strategy_ids: set[str],
    ) -> tuple[datetime, str]:
        if type(batch.authoritative) is not bool:
            raise LedgerValidationError("batch.authoritative must be a boolean")
        if batch.authoritative is not True:
            raise LedgerValidationError("batch.authoritative must be true")
        if type(batch.complete) is not bool:
            raise LedgerValidationError("batch.complete must be a boolean")
        if batch.complete is not True:
            raise LedgerValidationError("batch.complete must be true")
        _required_text(batch.next_cursor, "next_cursor")
        as_of_text, _ = _utc_text(batch.as_of, "batch.as_of")
        batch_as_of = datetime.fromisoformat(as_of_text)
        for fill in batch.fills:
            if not isinstance(fill, VenueFill):
                raise LedgerValidationError("batch fill has an invalid type")
            self._validate_fill(fill, allowed_strategy_ids, batch_as_of)
        for event in batch.cash_events:
            if not isinstance(event, VenueCashEvent):
                raise LedgerValidationError("batch cash event has an invalid type")
            self._validate_cash_event(event, allowed_strategy_ids, batch_as_of)
        return batch_as_of, as_of_text

    def _validate_fill(
        self,
        fill: VenueFill,
        allowed_strategy_ids: set[str],
        batch_as_of: datetime,
    ) -> None:
        if fill.account_scope != self.account_scope:
            raise LedgerValidationError("fill account_scope does not match ledger")
        if fill.quote_currency != self.quote_currency:
            raise LedgerValidationError("fill quote_currency does not match ledger")
        if fill.strategy_id not in allowed_strategy_ids:
            raise LedgerValidationError("fill strategy_id is outside the risk group")
        for text_value, name in (
            (fill.strategy_id, "fill.strategy_id"),
            (fill.symbol, "fill.symbol"),
            (fill.order_id, "fill.order_id"),
            (fill.fill_id, "fill.fill_id"),
            (fill.side, "fill.side"),
        ):
            _required_text(text_value, name)
        if fill.side not in {"buy", "sell"}:
            raise LedgerValidationError("fill.side must be buy or sell")
        occurred_text, _ = _utc_text(fill.occurred_at, "fill.occurred_at")
        if datetime.fromisoformat(occurred_text) > batch_as_of:
            raise LedgerValidationError("fill occurred_at is after batch.as_of")
        for decimal_value, name in (
            (fill.quantity, "fill.quantity"),
            (fill.execution_price, "fill.execution_price"),
            (fill.gross_realized_pnl, "fill.gross_realized_pnl"),
            (fill.commission, "fill.commission"),
            (fill.fees, "fill.fees"),
        ):
            _decimal_text(decimal_value, name)
        if fill.quantity <= 0:
            raise LedgerValidationError("fill.quantity must be positive")
        if fill.execution_price < 0:
            raise LedgerValidationError("fill.execution_price must be non-negative")
        if fill.commission < 0 or fill.fees < 0:
            raise LedgerValidationError("fill commission and fees must be non-negative")

    def _validate_cash_event(
        self,
        event: VenueCashEvent,
        allowed_strategy_ids: set[str],
        batch_as_of: datetime,
    ) -> None:
        if event.account_scope != self.account_scope:
            raise LedgerValidationError("cash event account_scope does not match ledger")
        if event.quote_currency != self.quote_currency:
            raise LedgerValidationError("cash event quote_currency does not match ledger")
        if event.strategy_id is not None and event.strategy_id not in allowed_strategy_ids:
            raise LedgerValidationError("cash event strategy_id is outside the risk group")
        _required_text(event.event_id, "cash_event.event_id")
        _required_text(event.kind, "cash_event.kind")
        if event.strategy_id is not None:
            _required_text(event.strategy_id, "cash_event.strategy_id")
        if event.symbol is not None:
            _required_text(event.symbol, "cash_event.symbol")
        occurred_text, _ = _utc_text(event.occurred_at, "cash_event.occurred_at")
        if datetime.fromisoformat(occurred_text) > batch_as_of:
            raise LedgerValidationError("cash event occurred_at is after batch.as_of")
        _decimal_text(event.cash_delta, "cash_event.cash_delta")
        _decimal_text(event.realized_pnl_delta, "cash_event.realized_pnl_delta")

    @staticmethod
    def _metadata_value_in_connection(
        connection: sqlite3.Connection, key: str
    ) -> str | None:
        row = connection.execute(
            "SELECT value FROM ledger_metadata WHERE key = ?", (key,)
        ).fetchone()
        return str(row[0]) if row is not None else None

    def _insert_fill(self, connection: sqlite3.Connection, fill: VenueFill) -> int:
        occurred_at, occurred_date = _utc_text(fill.occurred_at, "fill.occurred_at")
        values = (
            fill.account_scope,
            fill.strategy_id,
            fill.symbol,
            fill.order_id,
            fill.fill_id,
            occurred_at,
            occurred_date,
            fill.side,
            _decimal_text(fill.quantity, "fill.quantity"),
            _decimal_text(fill.execution_price, "fill.execution_price"),
            _decimal_text(fill.gross_realized_pnl, "fill.gross_realized_pnl"),
            _decimal_text(fill.commission, "fill.commission"),
            _decimal_text(fill.fees, "fill.fees"),
            fill.quote_currency,
        )
        cursor = connection.execute(
            "INSERT OR IGNORE INTO fills VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            values,
        )
        if cursor.rowcount == 1:
            return 1
        existing = connection.execute(
            "SELECT * FROM fills WHERE account_scope=? AND strategy_id=? AND symbol=? "
            "AND order_id=? AND fill_id=?",
            values[:5],
        ).fetchone()
        if existing != values:
            raise LedgerIdentityConflictError(
                "fill identity conflict for "
                f"{fill.account_scope}/{fill.strategy_id}/{fill.symbol}/"
                f"{fill.order_id}/{fill.fill_id}"
            )
        return 0

    def _insert_cash_event(
        self, connection: sqlite3.Connection, event: VenueCashEvent
    ) -> int:
        occurred_at, occurred_date = _utc_text(
            event.occurred_at, "cash_event.occurred_at"
        )
        values = (
            event.account_scope,
            event.event_id,
            event.strategy_id,
            event.symbol,
            occurred_at,
            occurred_date,
            event.kind,
            _decimal_text(event.cash_delta, "cash_event.cash_delta"),
            _decimal_text(event.realized_pnl_delta, "cash_event.realized_pnl_delta"),
            event.quote_currency,
        )
        cursor = connection.execute(
            "INSERT OR IGNORE INTO cash_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            values,
        )
        if cursor.rowcount == 1:
            return 1
        existing = connection.execute(
            "SELECT * FROM cash_events WHERE account_scope=? AND event_id=?",
            values[:2],
        ).fetchone()
        if existing != values:
            raise LedgerIdentityConflictError(
                f"cash event identity conflict for {event.account_scope}/{event.event_id}"
            )
        return 0

    def realized_pnl_for_day(
        self,
        utc_day: date,
        *,
        through: datetime | None = None,
    ) -> Decimal:
        """Return exact net realized PnL for a UTC day through an optional cut."""
        day_text = utc_day.isoformat()
        through_text = (
            _utc_text(through, "realized_pnl.through")[0]
            if through is not None
            else None
        )
        cutoff_clause = " AND occurred_at <= ?" if through_text is not None else ""
        parameters: tuple[str, ...] = (
            (self.account_scope, day_text, through_text)
            if through_text is not None
            else (self.account_scope, day_text)
        )
        try:
            with decimal_arithmetic_context():
                total = Decimal("0")
                connection = self._connect()
                try:
                    fill_rows = connection.execute(
                        "SELECT gross_realized_pnl, commission, fees FROM fills "
                        "WHERE account_scope = ? AND occurred_date = ?" + cutoff_clause,
                        parameters,
                    )
                    for gross, commission, fees in fill_rows:
                        total += Decimal(str(gross))
                        total -= Decimal(str(commission))
                        total -= Decimal(str(fees))
                    cash_rows = connection.execute(
                        "SELECT realized_pnl_delta FROM cash_events "
                        "WHERE account_scope = ? AND occurred_date = ?" + cutoff_clause,
                        parameters,
                    )
                    for (realized_pnl_delta,) in cash_rows:
                        total += Decimal(str(realized_pnl_delta))
                finally:
                    connection.close()
                _derived_decimal_text(total, "daily_realized_pnl")
        except (sqlite3.DatabaseError, ArithmeticError) as exc:
            raise LedgerError(f"failed to calculate realized PnL: {exc}") from exc
        return total
