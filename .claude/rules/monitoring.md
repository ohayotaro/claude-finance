---
paths:
  - "src/monitoring/**"
  - "src/bot/**"
  - "src/risk/**"
---

# Monitoring Rules

## Structured Logging

### Mandatory: JSON Format
```python
import structlog

logger = structlog.get_logger()

# Every log entry must include:
logger.info("order_placed",
    strategy_id="binance.swap.mean-revert.btcusdt.5m.v1",
    symbol="BTC/USDT",
    side="buy",
    amount=0.001,
    price=65000.0,
    order_id="abc123",
)
```

Every log event MUST include `strategy_id`. The risk aggregator and monitoring layer partition on this field. Omitting it makes the event invisible to per-strategy dashboards and cross-strategy aggregation.

### Log Levels
| Level | Usage |
|-------|-------|
| DEBUG | Internal state, raw API responses |
| INFO | Order placed/filled, position opened/closed, signals |
| WARNING | Rate limit approached, partial fill, high latency |
| ERROR | Order rejected, API error, connection lost |
| CRITICAL | Emergency stop triggered, account limit hit, data corruption |

### Mandatory Log Events
- Bot startup / shutdown
- Exchange connection established / lost
- Every order: created, submitted, filled, cancelled, rejected
- Every position: opened, updated, closed
- PnL snapshot (every 5 minutes)
- Health check results

Every event above MUST include at minimum: `event`, `ts` (ISO 8601 UTC), and `strategy_id`.

## Metrics

### Core Metrics to Track
All metrics below MUST carry a `strategy_id` label so per-strategy panels and cross-strategy aggregation can partition correctly. Where a metric is account-level (e.g. margin), it carries an `account_scope` label instead.

| Metric | Type | Description |
|--------|------|-------------|
| `bot_uptime_seconds` | Gauge | Time since last restart |
| `exchange_connected` | Gauge | 1=connected, 0=disconnected |
| `orders_total` | Counter | Total orders by side/status |
| `fills_total` | Counter | Total fills by side |
| `position_size` | Gauge | Current position size per symbol |
| `unrealized_pnl` | Gauge | Current unrealized PnL |
| `realized_pnl_daily` | Gauge | Realized PnL today |
| `api_latency_ms` | Histogram | API call latency |
| `api_errors_total` | Counter | API errors by type |
| `websocket_reconnects` | Counter | WebSocket reconnection count |

## Alert Thresholds

| Condition | Severity | Action |
|-----------|----------|--------|
| Exchange disconnected > 30s (configurable) | WARNING | Notify via webhook |
| Exchange disconnected > 120s (configurable) | CRITICAL | Pause trading + notify |
| Daily loss > 3% of account (configurable) | WARNING | Notify |
| Daily loss > 5% of account (configurable) | CRITICAL | Emergency stop + notify |
| API error rate > 1% (5min window) (configurable) | WARNING | Notify |
| API error rate > 5% (5min window) (configurable) | CRITICAL | Pause trading + notify |
| Order rejected 3x consecutively (configurable) | WARNING | Notify + investigate |
| No heartbeat > 60s (configurable) | CRITICAL | Restart service |
| Latency p99 > 5000ms (configurable) | WARNING | Notify |

> **Note**: All thresholds are defaults and should be adjusted per project via `.claude/backtest-thresholds.json` or project configuration.

## Notification Channels

### Webhook Integration
Support at least one of:
- **Slack**: Incoming webhook
- **Discord**: Webhook URL
- **Telegram**: Bot API + chat ID

### Message Format
```json
{
    "severity": "CRITICAL",
    "strategy_id": "binance.swap.mean-revert.btcusdt.5m.v1",
    "risk_group": "crypto-main",
    "event": "daily_loss_limit",
    "message": "Daily loss exceeded 5% threshold (-5.23%)",
    "timestamp": "2026-04-21T15:30:00Z",
    "action_taken": "Emergency stop triggered"
}
```

## Per-Strategy Log Isolation

Each strategy writes to its own JSONL file at `logs/strategies/{strategy_id}/bot.jsonl`. This is the default layout defined in `multi-strategy.md` section 5.

- Log rotation is per-file (not per-account). Each strategy's `bot.jsonl` rotates independently at the thresholds defined in "Log Rotation" below.
- Even though logs are stored in separate files, every event MUST still include `strategy_id` in the JSON body. This allows safe concatenation and re-partitioning when logs are shipped to a central store.
- The risk aggregator and `/bot-monitor` discover log paths by reading `log_path` from `config/registry.toml` for each strategy.

## Log Rotation

- Max file size: 100MB per log file
- Retention: 30 days
- Compress rotated logs (gzip)
- For Docker: use `json-file` driver with `max-size` and `max-file` options
