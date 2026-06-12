"""Strategy registry: single source of truth for strategy identity.

Implements the contract in `.claude/rules/multi-strategy.md`. The CLI is the
sanctioned writer of `config/registry.toml`; all other code reads via
`load_registry` and resolves paths via `validate_registry_relative_path`.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import os
import re
import sys
import tempfile
import time
import tomllib
import zlib
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import IntEnum, StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

import tomli_w

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

# ---------------------------------------------------------------------------
# Enums and constants
# ---------------------------------------------------------------------------


class StrategyState(StrEnum):
    DRAFT = "draft"
    TESTNET = "testnet"
    LIVE = "live"
    DEPRECATED = "deprecated"
    RETIRED = "retired"


class Runtime(StrEnum):
    PYTHON = "python"
    MQL5 = "mql5"


class PositionMode(StrEnum):
    NETTING = "netting"
    HEDGING = "hedging"


class ExitCode(IntEnum):
    OK = 0
    USER_ERROR = 2
    INVARIANT_VIOLATION = 3
    LOCK_CONTENTION = 4
    SCHEMA_VERSION_MISMATCH = 5


SCHEMA_VERSION = 1

# Canonical regex from multi-strategy.md section 2.
STRATEGY_ID_RE: re.Pattern[str] = re.compile(
    r"^[a-z0-9]+(?:-[a-z0-9]+)*"
    r"\.[a-z0-9]+(?:-[a-z0-9]+)*"
    r"\.[a-z0-9]+(?:-[a-z0-9]+)*"
    r"\.[a-z0-9]+(?:-[a-z0-9]+)*"
    r"\.[1-9][0-9]*[smhdw]"
    r"\.v[1-9][0-9]*$"
)

# Safe pattern for exchange-native symbol strings.  Allows alphanumerics plus
# the handful of separators seen in real symbols (BTC/USDT, 7203.T, EUR-USD,
# USD_JPY) but rejects quotes, newlines, whitespace, TOML metacharacters, etc.
SAFE_SYMBOL_RE: re.Pattern[str] = re.compile(r"^[A-Za-z0-9._/\-]+$")

# States where the ``enabled`` flag can be toggled.  ``deprecated`` and
# ``retired`` are terminal -- strategies in those states must stay disabled.
ENABLEABLE_STATES: frozenset[StrategyState] = frozenset(
    {StrategyState.DRAFT, StrategyState.TESTNET, StrategyState.LIVE}
)

DEFAULT_MAGIC_RANGE_START = 20_000_000
DEFAULT_MAGIC_RANGE_END = 89_999_999
MAX_MAGIC_SALT_ITERATIONS = 1000
LOCK_TIMEOUT_S = 30.0
LOCK_POLL_INTERVAL_S = 0.1
ALLOWED_TRANSITIONS: dict[StrategyState, frozenset[StrategyState]] = {
    StrategyState.DRAFT: frozenset({StrategyState.TESTNET, StrategyState.DEPRECATED}),
    StrategyState.TESTNET: frozenset({StrategyState.LIVE, StrategyState.DEPRECATED}),
    StrategyState.LIVE: frozenset({StrategyState.DEPRECATED}),
    StrategyState.DEPRECATED: frozenset({StrategyState.RETIRED}),
    StrategyState.RETIRED: frozenset(),
}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class RegistryError(Exception):
    """Base for registry-domain errors. Carries an ExitCode."""

    exit_code: ExitCode = ExitCode.USER_ERROR

    def __init__(self, message: str, *, exit_code: ExitCode | None = None) -> None:
        super().__init__(message)
        if exit_code is not None:
            self.exit_code = exit_code


class UserError(RegistryError):
    exit_code = ExitCode.USER_ERROR


class InvariantViolationError(RegistryError):
    exit_code = ExitCode.INVARIANT_VIOLATION


class LockContentionError(RegistryError):
    exit_code = ExitCode.LOCK_CONTENTION


class SchemaVersionMismatchError(RegistryError):
    exit_code = ExitCode.SCHEMA_VERSION_MISMATCH


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RegistryDefaults:
    state_dir: str = "state/strategies"
    log_dir: str = "logs/strategies"
    config_dir: str = "config/strategies"
    magic_range_start: int = DEFAULT_MAGIC_RANGE_START
    magic_range_end: int = DEFAULT_MAGIC_RANGE_END


@dataclass(frozen=True, slots=True)
class AccountEntry:
    name: str
    position_mode: PositionMode
    notes: str = ""


@dataclass(slots=True)
class StrategyEntry:
    id: str
    family_id: str
    logic_version: str
    runtime: Runtime
    venue: str
    market: str
    symbol: str
    timeframe: str
    account_scope: str
    risk_group: str
    state: StrategyState
    enabled: bool
    config_path: str
    state_path: str
    log_path: str
    created_at: datetime
    updated_at: datetime
    db_path: str = ""
    magic_number: int = 0
    magic_salt: int = 0
    owner: str = ""
    notes: str = ""


@dataclass(slots=True)
class RegistryDocument:
    schema_version: int
    defaults: RegistryDefaults
    accounts: list[AccountEntry]
    strategies: list[StrategyEntry]


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def canonicalize_symbol(symbol: str) -> str:
    """Lowercase and strip formatting separators.

    Examples: BTC/USDT -> btcusdt, 7203.T -> 7203t, EUR-USD -> eurusd.
    """
    return re.sub(r"[/._\-]+", "", symbol).lower()


def compose_strategy_id(
    venue: str,
    market: str,
    logic_slug: str,
    symbol_canonical: str,
    timeframe: str,
    major: int,
) -> str:
    return f"{venue}.{market}.{logic_slug}.{symbol_canonical}.{timeframe}.v{major}"


def validate_strategy_id(strategy_id: str) -> bool:
    return STRATEGY_ID_RE.match(strategy_id) is not None


def allocate_magic_number(
    strategy_id: str,
    existing: set[int],
    *,
    range_start: int = DEFAULT_MAGIC_RANGE_START,
    range_size: int = DEFAULT_MAGIC_RANGE_END - DEFAULT_MAGIC_RANGE_START + 1,
    max_attempts: int = MAX_MAGIC_SALT_ITERATIONS,
) -> tuple[int, int]:
    """Return (magic_number, salt). See multi-strategy.md section 3."""
    for salt in range(max_attempts):
        key = strategy_id if salt == 0 else f"{strategy_id}#{salt}"
        candidate = range_start + (zlib.crc32(key.encode()) % range_size)
        if candidate not in existing:
            return candidate, salt
    raise InvariantViolationError(
        f"MagicNumber allocation exhausted after {max_attempts} iterations "
        f"for strategy_id={strategy_id} (existing={len(existing)})",
        exit_code=ExitCode.INVARIANT_VIOLATION,
    )


def allowed_transition(current: StrategyState, target: StrategyState) -> bool:
    return target in ALLOWED_TRANSITIONS.get(current, frozenset())


def validate_registry_relative_path(
    project_root: Path,
    candidate: str,
    expected_prefix: str,
) -> Path:
    """Reader-side path validation (multi-strategy.md section 10).

    Returns the absolute, resolved path. Raises ValueError on any violation.
    Public API consumed by bots and aggregator.
    """
    if not candidate:
        raise ValueError("empty path")
    candidate_pure = Path(candidate)
    if candidate_pure.is_absolute():
        raise ValueError(f"absolute paths forbidden in registry: {candidate}")
    # PurePath catches '..' segments before filesystem resolution can mask them.
    if any(part == ".." for part in candidate_pure.parts):
        raise ValueError(f"parent-traversal segments forbidden: {candidate}")
    root_real = os.path.realpath(project_root)
    joined_real = os.path.realpath(project_root / candidate_pure)
    try:
        common = os.path.commonpath([joined_real, root_real])
    except ValueError as exc:
        raise ValueError(f"path on different volume: {candidate}") from exc
    if common != root_real:
        raise ValueError(f"path escapes project root: {candidate}")
    prefix_pure = Path(expected_prefix)
    if not candidate_pure.parts[: len(prefix_pure.parts)] == prefix_pure.parts:
        raise ValueError(
            f"path does not start with expected prefix {expected_prefix!r}: {candidate}"
        )
    return Path(joined_real)


# ---------------------------------------------------------------------------
# TOML conversion
# ---------------------------------------------------------------------------


def _to_strategy_entry(raw: dict[str, Any]) -> StrategyEntry:
    try:
        state = StrategyState(raw["state"])
        runtime = Runtime(raw["runtime"])
        return StrategyEntry(
            id=raw["id"],
            family_id=raw["family_id"],
            logic_version=raw["logic_version"],
            runtime=runtime,
            venue=raw["venue"],
            market=raw["market"],
            symbol=raw["symbol"],
            timeframe=raw["timeframe"],
            account_scope=raw["account_scope"],
            risk_group=raw["risk_group"],
            state=state,
            enabled=bool(raw["enabled"]),
            config_path=raw["config_path"],
            state_path=raw["state_path"],
            log_path=raw["log_path"],
            created_at=_parse_dt(raw["created_at"]),
            updated_at=_parse_dt(raw["updated_at"]),
            db_path=raw.get("db_path", ""),
            magic_number=int(raw.get("magic_number", 0)),
            magic_salt=int(raw.get("magic_salt", 0)),
            owner=raw.get("owner", ""),
            notes=raw.get("notes", ""),
        )
    except KeyError as exc:
        raise InvariantViolationError(f"missing required strategy field: {exc}") from exc


def _to_account_entry(raw: dict[str, Any]) -> AccountEntry:
    return AccountEntry(
        name=raw["name"],
        position_mode=PositionMode(raw["position_mode"]),
        notes=raw.get("notes", ""),
    )


def _parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        # tomllib usually returns datetime; this is a fallback.
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise InvariantViolationError(f"unparseable timestamp: {value!r}")


def _strategy_to_dict(entry: StrategyEntry) -> dict[str, Any]:
    return {
        "id": entry.id,
        "family_id": entry.family_id,
        "logic_version": entry.logic_version,
        "runtime": entry.runtime.value,
        "venue": entry.venue,
        "market": entry.market,
        "symbol": entry.symbol,
        "timeframe": entry.timeframe,
        "account_scope": entry.account_scope,
        "risk_group": entry.risk_group,
        "state": entry.state.value,
        "enabled": entry.enabled,
        "config_path": entry.config_path,
        "state_path": entry.state_path,
        "log_path": entry.log_path,
        "db_path": entry.db_path,
        "magic_number": entry.magic_number,
        "magic_salt": entry.magic_salt,
        "created_at": entry.created_at,
        "updated_at": entry.updated_at,
        "owner": entry.owner,
        "notes": entry.notes,
    }


def load_registry(path: Path) -> RegistryDocument:
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    schema_version = int(data.get("schema_version", 0))
    if schema_version != SCHEMA_VERSION:
        raise SchemaVersionMismatchError(
            f"registry schema_version={schema_version}, expected {SCHEMA_VERSION}"
        )
    defaults_raw = data.get("defaults", {})
    defaults = RegistryDefaults(
        state_dir=defaults_raw.get("state_dir", RegistryDefaults().state_dir),
        log_dir=defaults_raw.get("log_dir", RegistryDefaults().log_dir),
        config_dir=defaults_raw.get("config_dir", RegistryDefaults().config_dir),
        magic_range_start=int(defaults_raw.get("magic_range_start", DEFAULT_MAGIC_RANGE_START)),
        magic_range_end=int(defaults_raw.get("magic_range_end", DEFAULT_MAGIC_RANGE_END)),
    )
    accounts = [_to_account_entry(a) for a in data.get("accounts", [])]
    strategies = [_to_strategy_entry(s) for s in data.get("strategies", [])]
    return RegistryDocument(
        schema_version=schema_version,
        defaults=defaults,
        accounts=accounts,
        strategies=strategies,
    )


def dump_registry(doc: RegistryDocument) -> bytes:
    payload: dict[str, Any] = {
        "schema_version": doc.schema_version,
        "defaults": asdict(doc.defaults),
    }
    if doc.accounts:
        payload["accounts"] = [
            {
                "name": a.name,
                "position_mode": a.position_mode.value,
                "notes": a.notes,
            }
            for a in doc.accounts
        ]
    if doc.strategies:
        sorted_strategies = sorted(doc.strategies, key=lambda s: s.id)
        payload["strategies"] = [_strategy_to_dict(s) for s in sorted_strategies]
    return tomli_w.dumps(payload).encode("utf-8")


# ---------------------------------------------------------------------------
# Locking and atomic write
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def locked_registry_file(path: Path) -> Iterator[None]:
    """Hold a non-blocking exclusive flock on a sidecar lock file.

    Polls up to LOCK_TIMEOUT_S so concurrent callers fail predictably rather
    than hanging forever.
    """
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        deadline = time.monotonic() + LOCK_TIMEOUT_S
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise LockContentionError(
                        f"could not acquire registry lock within {LOCK_TIMEOUT_S}s"
                    ) from None
                time.sleep(LOCK_POLL_INTERVAL_S)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def atomic_replace(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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


def write_registry(path: Path, doc: RegistryDocument) -> None:
    """Caller MUST already hold `locked_registry_file`."""
    atomic_replace(path, dump_registry(doc))


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------


def _now_utc() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _registry_path(project_root: Path) -> Path:
    return project_root / "config" / "registry.toml"


def _ensure_registry(project_root: Path) -> RegistryDocument:
    path = _registry_path(project_root)
    if not path.exists():
        doc = RegistryDocument(
            schema_version=SCHEMA_VERSION,
            defaults=RegistryDefaults(),
            accounts=[],
            strategies=[],
        )
        atomic_replace(path, dump_registry(doc))
        return doc
    return load_registry(path)


def _find_entry(doc: RegistryDocument, strategy_id: str) -> StrategyEntry | None:
    for entry in doc.strategies:
        if entry.id == strategy_id:
            return entry
    return None


def cmd_register(args: argparse.Namespace, project_root: Path) -> int:
    if not SAFE_SYMBOL_RE.match(args.symbol):
        raise UserError(
            f"symbol contains unsafe characters: {args.symbol!r} "
            "(allowed: A-Za-z0-9 . _ / -)"
        )
    symbol_canonical = canonicalize_symbol(args.symbol)
    try:
        logic_major = int(args.logic_version.split(".")[0])
    except (ValueError, IndexError) as exc:
        raise UserError(f"invalid --logic-version (need semver like 1.2.0): {exc}") from exc
    # strategy_id major must be >= 1 (regex). A pre-1.0 logic_version maps to v1.
    major = max(logic_major, 1)
    strategy_id = compose_strategy_id(
        args.venue, args.market, args.logic_slug, symbol_canonical, args.timeframe, major
    )
    if not validate_strategy_id(strategy_id):
        raise UserError(f"strategy_id failed validation: {strategy_id}")

    registry_path = _registry_path(project_root)
    with locked_registry_file(registry_path):
        doc = _ensure_registry(project_root)
        if _find_entry(doc, strategy_id) is not None:
            raise UserError(f"strategy_id already registered: {strategy_id}")
        # Near-duplicate detection: same venue/market/logic/symbol/timeframe with
        # any major. Different major is allowed, but we warn the user.
        for entry in doc.strategies:
            if (
                entry.venue == args.venue
                and entry.market == args.market
                and entry.symbol == args.symbol
                and entry.timeframe == args.timeframe
                and canonicalize_symbol(entry.symbol) == symbol_canonical
            ):
                # Same logical strategy at a different major; allowed but noted.
                print(
                    f"note: a sibling exists at major v{entry.id.rsplit('.v', 1)[-1]}: {entry.id}",
                    file=sys.stderr,
                )
                break

        runtime = Runtime(args.runtime)
        magic_number = 0
        magic_salt = 0
        if runtime is Runtime.MQL5:
            # Netting shared-symbol refusal (multi-strategy.md section 3).
            for acct in doc.accounts:
                if acct.name == args.account_scope and acct.position_mode is PositionMode.NETTING:
                    for entry in doc.strategies:
                        if (
                            entry.runtime is Runtime.MQL5
                            and entry.account_scope == args.account_scope
                            and entry.venue == args.venue
                            and entry.symbol == args.symbol
                            and entry.state is not StrategyState.RETIRED
                        ):
                            raise UserError(
                                "refused: netting account "
                                f"{args.account_scope!r} already has an active mql5 "
                                f"strategy on {args.venue}/{args.symbol}: {entry.id}"
                            )
            existing_magic = {
                e.magic_number
                for e in doc.strategies
                if e.runtime is Runtime.MQL5 and e.magic_number > 0
            }
            magic_number, magic_salt = allocate_magic_number(
                strategy_id,
                existing_magic,
                range_start=doc.defaults.magic_range_start,
                range_size=doc.defaults.magic_range_end - doc.defaults.magic_range_start + 1,
            )

        config_path = f"{doc.defaults.config_dir}/{strategy_id}.toml"
        state_path = f"{doc.defaults.state_dir}/{strategy_id}"
        log_path = f"{doc.defaults.log_dir}/{strategy_id}"
        db_path = f"{state_path}/state.db" if runtime is Runtime.PYTHON else ""

        now = _now_utc()
        entry = StrategyEntry(
            id=strategy_id,
            family_id=args.family_id or args.logic_slug,
            logic_version=args.logic_version,
            runtime=runtime,
            venue=args.venue,
            market=args.market,
            symbol=args.symbol,
            timeframe=args.timeframe,
            account_scope=args.account_scope,
            risk_group=args.risk_group,
            state=StrategyState.DRAFT,
            enabled=False,
            config_path=config_path,
            state_path=state_path,
            log_path=log_path,
            db_path=db_path,
            magic_number=magic_number,
            magic_salt=magic_salt,
            created_at=now,
            updated_at=now,
            owner=args.owner or "",
            notes="",
        )
        doc.strategies.append(entry)
        write_registry(registry_path, doc)

    _scaffold_strategy_dirs(project_root, entry)

    print(f"registered: {strategy_id}")
    print(f"  runtime:      {entry.runtime.value}")
    if entry.runtime is Runtime.MQL5:
        print(f"  magic_number: {entry.magic_number}")
    print(f"  config_path:  {entry.config_path}")
    print(f"  state:        {entry.state.value}")
    print(f"  enabled:      {entry.enabled}")
    return ExitCode.OK


def _scaffold_strategy_dirs(project_root: Path, entry: StrategyEntry) -> None:
    """Idempotent: safe to re-run after a partial crash."""
    state_dir = project_root / entry.state_path
    log_dir = project_root / entry.log_path
    config_file = project_root / entry.config_path
    reports_dir = project_root / "reports" / "strategies" / entry.id
    for d in (state_dir, log_dir, reports_dir):
        d.mkdir(parents=True, exist_ok=True)
        gitkeep = d / ".gitkeep"
        if not gitkeep.exists():
            gitkeep.touch()
    if not config_file.exists():
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(_per_strategy_config_template(entry))


def _per_strategy_config_template(entry: StrategyEntry) -> str:
    """Generate per-strategy config TOML.

    All user-supplied values are serialized via ``tomli_w`` to prevent TOML
    injection.  Static comments and placeholder sections are appended as
    literal text because ``tomli_w`` does not support comments.
    """
    data: dict[str, Any] = {
        "strategy_id": entry.id,
        "runtime": {
            "mode": "testnet",
            "symbol": entry.symbol,
            "timeframe": entry.timeframe,
        },
        "risk": {
            "max_position_size": 0.01,
            "max_daily_loss_pct": 2.0,
            "max_drawdown_pct": 10.0,
            "stop_loss_pct": 1.0,
            "take_profit_pct": 2.0,
        },
        "params": {},
        "notifications": {},
    }
    serialized = tomli_w.dumps(data)
    # Append comment hints for the notifications section.
    return (
        f"# {entry.id}\n"
        f"{serialized}\n"
        '# [notifications]\n'
        '# channel = "slack://#bot-alerts"\n'
        '# severity_floor = "WARNING"\n'
    )


def cmd_transition(args: argparse.Namespace, project_root: Path) -> int:
    target = StrategyState(args.target_state)
    registry_path = _registry_path(project_root)
    with locked_registry_file(registry_path):
        doc = _ensure_registry(project_root)
        entry = _find_entry(doc, args.strategy_id)
        if entry is None:
            raise UserError(f"unknown strategy_id: {args.strategy_id}")
        if not allowed_transition(entry.state, target):
            raise UserError(
                f"forbidden transition {entry.state.value} -> {target.value} "
                f"for {entry.id}"
            )
        entry.state = target
        entry.updated_at = _now_utc()
        if target is StrategyState.DEPRECATED:
            entry.enabled = False
        write_registry(registry_path, doc)
    print(f"transitioned {args.strategy_id}: -> {target.value}")
    return ExitCode.OK


def cmd_enable(args: argparse.Namespace, project_root: Path) -> int:
    registry_path = _registry_path(project_root)
    with locked_registry_file(registry_path):
        doc = _ensure_registry(project_root)
        entry = _find_entry(doc, args.strategy_id)
        if entry is None:
            raise UserError(f"unknown strategy_id: {args.strategy_id}")
        if entry.state not in ENABLEABLE_STATES:
            raise UserError(
                f"enable refused: state={entry.state.value} is terminal; "
                f"allowed states: {', '.join(sorted(s.value for s in ENABLEABLE_STATES))}"
            )
        entry.enabled = True
        entry.updated_at = _now_utc()
        write_registry(registry_path, doc)
    print(f"enabled {args.strategy_id}")
    return ExitCode.OK


def cmd_disable(args: argparse.Namespace, project_root: Path) -> int:
    registry_path = _registry_path(project_root)
    with locked_registry_file(registry_path):
        doc = _ensure_registry(project_root)
        entry = _find_entry(doc, args.strategy_id)
        if entry is None:
            raise UserError(f"unknown strategy_id: {args.strategy_id}")
        if entry.state not in ENABLEABLE_STATES:
            raise UserError(
                f"disable refused: state={entry.state.value} is terminal; "
                f"allowed states: {', '.join(sorted(s.value for s in ENABLEABLE_STATES))}"
            )
        entry.enabled = False
        entry.updated_at = _now_utc()
        write_registry(registry_path, doc)
    print(f"disabled {args.strategy_id}")
    return ExitCode.OK


def cmd_list(args: argparse.Namespace, project_root: Path) -> int:
    doc = _ensure_registry(project_root)
    rows = doc.strategies
    if args.state is not None:
        rows = [r for r in rows if r.state.value == args.state]
    if args.risk_group is not None:
        rows = [r for r in rows if r.risk_group == args.risk_group]
    if args.venue is not None:
        rows = [r for r in rows if r.venue == args.venue]
    if args.runtime is not None:
        rows = [r for r in rows if r.runtime.value == args.runtime]
    print(f"{'strategy_id':<55} {'runtime':<8} {'state':<11} {'enabled':<8} risk_group")
    for r in sorted(rows, key=lambda r: r.id):
        print(
            f"{r.id:<55} {r.runtime.value:<8} {r.state.value:<11} "
            f"{str(r.enabled).lower():<8} {r.risk_group}"
        )
    return ExitCode.OK


def cmd_show(args: argparse.Namespace, project_root: Path) -> int:
    doc = _ensure_registry(project_root)
    entry = _find_entry(doc, args.strategy_id)
    if entry is None:
        raise UserError(f"unknown strategy_id: {args.strategy_id}")
    print(tomli_w.dumps({"strategy": _strategy_to_dict(entry)}))
    print("Paths (exists?):")
    for label, candidate in (
        ("config_path", entry.config_path),
        ("state_path", entry.state_path),
        ("log_path", entry.log_path),
        ("db_path", entry.db_path),
    ):
        if not candidate:
            print(f"  {label:<13} (unset)")
            continue
        exists = (project_root / candidate).exists()
        marker = "[ok]" if exists else "[missing]"
        print(f"  {label:<13} {candidate} {marker}")
    return ExitCode.OK


def cmd_audit(args: argparse.Namespace, project_root: Path) -> int:
    doc = _ensure_registry(project_root)
    violations: list[str] = []

    seen_ids: set[str] = set()
    for entry in doc.strategies:
        if not validate_strategy_id(entry.id):
            violations.append(f"invalid strategy_id format: {entry.id}")
        if entry.id in seen_ids:
            violations.append(f"duplicate strategy_id: {entry.id}")
        seen_ids.add(entry.id)

    mql5_magics: dict[int, str] = {}
    for entry in doc.strategies:
        if entry.runtime is Runtime.MQL5:
            if not (
                doc.defaults.magic_range_start <= entry.magic_number <= doc.defaults.magic_range_end
            ):
                violations.append(
                    f"magic_number out of reserved range for {entry.id}: {entry.magic_number}"
                )
            if entry.magic_number in mql5_magics:
                violations.append(
                    f"duplicate magic_number {entry.magic_number}: "
                    f"{mql5_magics[entry.magic_number]} vs {entry.id}"
                )
            mql5_magics[entry.magic_number] = entry.id
            if entry.magic_number <= 0:
                violations.append(f"mql5 entry without magic_number: {entry.id}")
        else:
            if entry.magic_number != 0:
                violations.append(
                    f"python entry with non-zero magic_number: {entry.id}"
                )

    canonical_seen: dict[tuple[str, str, str, str, str, str], str] = {}
    for entry in doc.strategies:
        key = (
            entry.venue,
            entry.market,
            entry.id.split(".")[2],
            canonicalize_symbol(entry.symbol),
            entry.timeframe,
            entry.id.rsplit(".v", 1)[-1],
        )
        if key in canonical_seen:
            violations.append(
                f"canonicalization collision: {entry.id} vs {canonical_seen[key]}"
            )
        canonical_seen[key] = entry.id

    for entry in doc.strategies:
        try:
            validate_registry_relative_path(
                project_root, entry.config_path, doc.defaults.config_dir
            )
            validate_registry_relative_path(
                project_root, entry.state_path, doc.defaults.state_dir
            )
            validate_registry_relative_path(
                project_root, entry.log_path, doc.defaults.log_dir
            )
        except ValueError as exc:
            violations.append(f"path validation failed for {entry.id}: {exc}")

    for entry in doc.strategies:
        if entry.updated_at < entry.created_at:
            violations.append(f"updated_at before created_at: {entry.id}")

    missing_paths: list[tuple[StrategyEntry, str, Path]] = []
    for entry in doc.strategies:
        for kind, declared in (
            ("config_path", entry.config_path),
            ("state_path", entry.state_path),
            ("log_path", entry.log_path),
        ):
            if not declared:
                continue
            full = project_root / declared
            if not full.exists():
                missing_paths.append((entry, kind, full))
                violations.append(f"declared {kind} missing for {entry.id}: {declared}")

    if violations:
        print("audit: violations:")
        for v in violations:
            print(f"  - {v}")

    if missing_paths and getattr(args, "fix", False):
        print("audit --fix: scaffolding missing directories")
        for entry, _kind, _full in missing_paths:
            _scaffold_strategy_dirs(project_root, entry)
        # Re-run audit after fix to report residual violations cleanly.
        print("audit --fix: complete (re-run audit to verify)")

    if violations and not getattr(args, "fix", False):
        return ExitCode.INVARIANT_VIOLATION
    if not violations:
        print(f"audit: ok ({len(doc.strategies)} strategies, {len(doc.accounts)} accounts)")
    return ExitCode.OK


def cmd_migrate(args: argparse.Namespace, project_root: Path) -> int:
    """Schema migration entrypoint. Only `1 -> 1` (no-op) implemented today."""
    registry_path = _registry_path(project_root)
    with locked_registry_file(registry_path):
        doc = load_registry(registry_path)
        if doc.schema_version == SCHEMA_VERSION:
            print(f"migrate: registry already at schema_version={SCHEMA_VERSION}")
            return ExitCode.OK
        # Future bumps would back up then transform.
        backup = registry_path.with_suffix(
            f".bak.v{doc.schema_version}.{int(time.time())}.toml"
        )
        backup.write_bytes(registry_path.read_bytes())
        print(f"migrate: backed up old registry to {backup.name}")
        raise UserError("no migration path defined yet beyond schema_version=1")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="orchestrator.registry")
    parser.add_argument(
        "--project-root",
        default=os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()),
        help="Project root (default: $CLAUDE_PROJECT_DIR or cwd)",
    )
    sub = parser.add_subparsers(dest="action", required=True)

    p_register = sub.add_parser("register", help="Mint a new strategy_id")
    p_register.add_argument("--venue", required=True)
    p_register.add_argument("--market", required=True)
    p_register.add_argument("--logic-slug", required=True)
    p_register.add_argument("--symbol", required=True)
    p_register.add_argument("--timeframe", required=True)
    p_register.add_argument("--runtime", required=True, choices=[r.value for r in Runtime])
    p_register.add_argument("--account-scope", required=True)
    p_register.add_argument("--risk-group", required=True)
    p_register.add_argument("--logic-version", default="0.1.0")
    p_register.add_argument("--family-id", default="")
    p_register.add_argument("--owner", default="")

    p_transition = sub.add_parser("transition", help="Move state forward")
    p_transition.add_argument("strategy_id")
    p_transition.add_argument(
        "target_state", choices=[s.value for s in StrategyState]
    )

    p_enable = sub.add_parser("enable", help="Set enabled=true (draft/testnet/live)")
    p_enable.add_argument("strategy_id")

    p_disable = sub.add_parser("disable", help="Set enabled=false")
    p_disable.add_argument("strategy_id")

    p_list = sub.add_parser("list", help="List strategies")
    p_list.add_argument("--state", default=None)
    p_list.add_argument("--risk-group", default=None)
    p_list.add_argument("--venue", default=None)
    p_list.add_argument("--runtime", default=None)

    p_show = sub.add_parser("show", help="Show one strategy")
    p_show.add_argument("strategy_id")

    p_audit = sub.add_parser("audit", help="Verify invariants (CI-runnable)")
    p_audit.add_argument("--fix", action="store_true", help="Auto-scaffold missing dirs")

    sub.add_parser("migrate", help="Schema migration (no-op for v1)")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    project_root = Path(args.project_root).resolve()
    handlers: dict[str, Any] = {
        "register": cmd_register,
        "transition": cmd_transition,
        "enable": cmd_enable,
        "disable": cmd_disable,
        "list": cmd_list,
        "show": cmd_show,
        "audit": cmd_audit,
        "migrate": cmd_migrate,
    }
    handler = handlers[args.action]
    try:
        return int(handler(args, project_root))
    except RegistryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return int(exc.exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
