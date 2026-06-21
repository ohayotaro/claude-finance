# Bot Development Rules

## Multi-Strategy Bot Pattern

Every bot MUST be strategy-aware from the start. The default model is one process = one strategy.

- **CLI interface**: Accept `--strategy-id` as a required command-line argument. Example: `uv run python -m src.bot.main --strategy-id binance.swap.mean-revert.btcusdt.5m.v1`
- **Config resolution**: Read the strategy's config from `config/strategies/{strategy_id}.toml`. The path is looked up in `config/registry.toml`, not hardcoded.
- **State store**: Open the `StateStore` at `state/strategies/{strategy_id}/` (default SQLite backend at `state/strategies/{strategy_id}/state.db`).
- **Logging**: Write structured JSONL to `logs/strategies/{strategy_id}/bot.jsonl`. Every log event includes `strategy_id`.
- **Registry validation**: On startup, the bot MUST verify that `strategy_id` exists in `config/registry.toml`, that `enabled == true`, and that `state` permits the requested mode (e.g., `state = "live"` for live trading). Refuse to start otherwise.
- **Environment**: The `STRATEGY_ID` environment variable is set per container/service (see `deployment.md`). The bot MAY read it as a fallback when `--strategy-id` is not provided on the CLI.

See `multi-strategy.md` sections 5 and 7 for the full isolation and skill contract requirements.

## ccxt Standard Patterns

### Exchange Initialization
```python
import ccxt.async_support as ccxt

exchange = ccxt.binance({
    "apiKey": os.environ["BINANCE_API_KEY"],
    "secret": os.environ["BINANCE_SECRET_KEY"],
    "sandbox": True,  # Always start with sandbox/testnet
    "enableRateLimit": True,  # Mandatory
    "options": {"defaultType": "swap"},  # spot, swap, future
})
```

### Order Lifecycle
- Always use `create_order()` with explicit parameters (not shortcuts)
- Check order status after placement: `fetch_order(id, symbol)`
- Handle partial fills: track `filled` vs `amount`
- Implement timeout for pending orders (cancel after N seconds)
- Log every state transition: created → open → partial → filled/cancelled

## WebSocket Management

### Mandatory Patterns
- Auto-reconnect with exponential backoff (1s, 2s, 4s, 8s... max 60s)
- Heartbeat/ping-pong monitoring (detect stale connections)
- Separate streams for: price data, order updates, position changes
- Message queue for processing (prevent backpressure)
- Graceful shutdown: unsubscribe before disconnect

### Connection Health
```python
# Check connection health every 30 seconds
# If no message received in 60 seconds → reconnect
# If 3 consecutive reconnect failures → alert + pause trading
```

## asyncio Best Practices

- Use `asyncio.gather()` for concurrent API calls
- Never use `time.sleep()` — always `await asyncio.sleep()`
- Implement proper cancellation with `asyncio.shield()` for critical operations
- Use `asyncio.Queue` for producer-consumer patterns
- Handle `asyncio.CancelledError` for graceful shutdown

## Rate Limiting

- Always enable ccxt's built-in rate limiter (`enableRateLimit: True`)
- For burst operations, implement custom token bucket
- Log rate limit warnings (HTTP 429 responses)
- Different limits for: REST orders, REST queries, WebSocket subscriptions

## Order State Machine

```
CREATED → SUBMITTED → OPEN → PARTIALLY_FILLED → FILLED
                         │                         │
                         └→ CANCELLED              └→ CANCELLED (partial)
                         │
                         └→ REJECTED
                         │
                         └→ EXPIRED
```

- Track every transition with timestamp
- Store full order history in persistent storage
- Reconcile local state with exchange state periodically

## Structured Logging Contract (Mandatory)

Every bot MUST emit structured JSON logs (via structlog or equivalent) for the following events. This is the contract between the bot and the orchestrator's monitoring layer (`/bot-monitor`, `/incident-response`).

### Mandatory Log Events

**Lifecycle:**
```json
{"event": "bot_started",    "strategy_id": "...", "version": "...", "config_hash": "...", "ts": "ISO8601"}
{"event": "bot_stopped",    "strategy_id": "...", "reason": "user|kill_switch|error|maintenance", "uptime_s": 3600, "ts": "..."}
{"event": "bot_heartbeat",  "strategy_id": "...", "uptime_s": 3600, "open_positions": 2, "daily_pnl": -0.5, "ts": "..."}
```
Heartbeat interval: every 60 seconds (configurable).

**Orders:**
```json
{"event": "order_created",  "strategy_id": "...", "order_id": "...", "symbol": "...", "side": "buy", "type": "limit", "size": 0.01, "price": 65000.0, "ts": "..."}
{"event": "order_submitted","strategy_id": "...", "order_id": "...", "exchange_id": "...", "ts": "..."}
{"event": "order_filled",   "strategy_id": "...", "order_id": "...", "fill_price": 65001.5, "fill_size": 0.01, "slippage_bps": 2.3, "ts": "..."}
{"event": "order_cancelled","strategy_id": "...", "order_id": "...", "reason": "timeout|user|exchange", "ts": "..."}
{"event": "order_rejected", "strategy_id": "...", "order_id": "...", "reason": "insufficient_balance", "ts": "..."}
```

**Positions:**
```json
{"event": "position_opened","strategy_id": "...", "symbol": "...", "side": "long", "size": 0.01, "entry_price": 65000.0, "ts": "..."}
{"event": "position_closed","strategy_id": "...", "symbol": "...", "side": "long", "size": 0.01, "exit_price": 65500.0, "pnl": 5.0, "pnl_pct": 0.77, "holding_s": 1800, "ts": "..."}
{"event": "position_update","strategy_id": "...", "symbol": "...", "unrealized_pnl": 3.2, "unrealized_pnl_pct": 0.49, "ts": "..."}
```
Position update interval: every 30 seconds while a position is open (configurable).

**Safety:**
```json
{"event": "safety_triggered","strategy_id": "...", "gate": "daily_loss_limit", "details": "daily loss -5.1% exceeds -5.0% threshold", "action": "block_new_entries", "ts": "..."}
{"event": "reconnect",      "strategy_id": "...", "target": "websocket", "attempt": 3, "backoff_s": 8, "ts": "..."}
{"event": "reconciliation", "strategy_id": "...", "status": "mismatch", "local_size": 0.01, "exchange_size": 0.0, "ts": "..."}
```

**Performance (periodic, every 5 minutes):**
```json
{"event": "perf_snapshot",  "strategy_id": "...", "api_latency_p50_ms": 45, "api_latency_p99_ms": 230, "api_errors_1h": 2, "ws_reconnects_1h": 0, "ts": "..."}
```

### Log Output Rules
- Format: JSON, one event per line (JSONL)
- Output: stdout (for Docker/systemd capture) AND file (`logs/strategies/{strategy_id}/bot.jsonl`)
- All events include `ts` (ISO 8601 UTC) and `event` (snake_case event name)
- Sensitive data (API keys, secrets) MUST NEVER appear in logs
- Log level mapping: lifecycle=INFO, orders=INFO, positions=INFO, safety=WARNING, errors=ERROR, heartbeat=DEBUG
- Rotation: 100MB per file, 10 files retained (configurable via monitoring.md)

## Exchange-Specific Adapters (Non-ccxt Exchanges)

For exchanges not fully supported by ccxt, build direct adapters:

### REST Client Pattern
```python
class ExchangeRestClient(Protocol):
    async def get_ticker(self, symbol: str) -> Ticker: ...
    async def get_positions(self) -> list[Position]: ...
    async def place_order(self, order: OrderRequest) -> OrderResult: ...
    async def cancel_order(self, order_id: str) -> None: ...
    async def get_balance(self) -> Balance: ...
```

- HMAC-SHA256 signature for private endpoints
- Per-endpoint rate limiting (internal RateLimiter class)
- Retry on 429/500/502/503 with exponential backoff

### WebSocket Client Pattern
- JSON-RPC 2.0 or exchange-specific protocol
- Channel subscription management
- Watchdog timer (restart on N seconds of silence)
- Auto-reconnect with exponential backoff (1s → 30s cap)

## State Persistence (Pluggable Backend)

### StateStore Protocol
```python
class StateStore(Protocol):
    async def save_position(self, position: Position) -> None: ...
    async def load_positions(self) -> list[Position]: ...
    async def save_trade(self, trade: Trade) -> None: ...
    async def load_trades(self, since: datetime) -> list[Trade]: ...
    async def save_checkpoint(self, state: dict) -> None: ...
    async def load_checkpoint(self) -> dict | None: ...
```

The `StateStore` protocol above is the ONLY interface bots use to persist state. This abstraction exists specifically to allow later migration from per-strategy SQLite to a central PostgreSQL backend WITHOUT changing skill contracts. Bots MUST NOT bypass `StateStore` to touch SQLite directly. See `multi-strategy.md` section 5 for the state store abstraction requirements.

### Recommended Default (SQLite + WAL)

SQLite with WAL mode is the recommended default. PostgreSQL, Redis, or other backends can be used depending on project requirements. One DB per strategy is the default layout.

```python
# aiosqlite with WAL for concurrent read/write safety
# Path resolved from registry: state/strategies/{strategy_id}/state.db
async with aiosqlite.connect("state/strategies/{strategy_id}/state.db") as db:
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA synchronous=NORMAL")
    await db.execute("PRAGMA busy_timeout=5000")
```

### Required Tables
- **positions**: Current open positions (symbol, side, size, entry_price, timestamp)
- **trades**: Completed trade history (entry, exit, PnL, duration)
- **checkpoints**: Bot state snapshots for crash recovery

### Crash Recovery Protocol
1. On startup, query exchange for actual positions
2. Compare with stored state in SQLite
3. If mismatch: reconcile (exchange state = source of truth)
4. If 3+ consecutive mismatches: emergency shutdown + alert
5. Resume normal operation only after reconciliation

## Testing Requirements

- **Testnet/sandbox mandatory**: All new bots must pass testnet before live
- **Dry-run mode**: Every bot must support `--dry-run` flag (log orders without executing)
- **Paper trading**: Simulate execution with real market data, fake orders
- **Integration tests**: Test with real exchange sandbox API
- **Stress tests**: Simulate rapid price changes, connection drops, partial fills
- **Replay tests**: Bit-exact replay of historical tick data to verify signal parity
