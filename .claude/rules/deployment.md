---
paths:
  - "docker/**"
  - "**/Dockerfile"
  - "**/docker-compose*.yml"
  - "**/*.service"
  - "**/*.plist"
---

# Deployment Rules

## Docker Best Practices

### Dockerfile Standards
- Multi-stage builds (builder + runtime)
- Run as non-root user (`USER appuser`)
- Pin base image versions (e.g., `python:3.11-slim-bookworm`, never `:latest`)
- Copy only necessary files (use `.dockerignore`)
- Install dependencies before copying source (layer caching)
- Set `PYTHONDONTWRITEBYTECODE=1` and `PYTHONUNBUFFERED=1`

### Docker Compose
- Use named volumes for persistent data
- Set `restart: unless-stopped` for bot services
- Define health checks in compose file
- Use `.env` file for environment variables (never hardcode)
- Separate services: bot, monitoring, logging

## Environment Variables

### Mandatory
```bash
# Strategy identity (required per bot service)
STRATEGY_ID=<strategy_id>

# Exchange credentials
EXCHANGE_API_KEY=
EXCHANGE_SECRET_KEY=

# Bot configuration
BOT_MODE=live|testnet|dry-run
BOT_SYMBOL=BTC/USDT
BOT_STRATEGY=

# Risk limits
MAX_POSITION_SIZE=
MAX_DAILY_LOSS=

# Monitoring
ALERT_WEBHOOK_URL=
LOG_LEVEL=INFO
```

### Rules
- All secrets via environment variables (never in code or Docker image)
- Use `.env` for local development, Docker secrets for production
- Different `.env` files per environment (`.env.testnet`, `.env.production`)
- Rotate API keys periodically

## Health Checks

### Mandatory for Every Bot
```python
# HTTP endpoint: GET /health → 200 OK
{
    "status": "healthy",
    "strategy_id": "binance.swap.mean-revert.btcusdt.5m.v1",
    "uptime_seconds": 3600,
    "exchange_connected": true,
    "last_heartbeat": "2026-04-21T12:00:00Z",
    "open_positions": 2,
    "daily_pnl": -0.5
}
```

- Health check interval: 30 seconds
- Unhealthy after 3 consecutive failures
- Auto-restart on unhealthy (Docker/systemd)

## systemd Service (VPS)

Service naming convention: `bot-{strategy_id_safe}` where `strategy_id_safe` replaces dots with dashes (e.g., `bot-binance-swap-mean-revert-btcusdt-5m-v1`).

```ini
[Unit]
Description=Trading Bot - {strategy_id}
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=botuser
Environment="STRATEGY_ID={strategy_id}"
EnvironmentFile=/etc/bot/{strategy_id_safe}.env
ExecStart=/usr/bin/docker compose -f /opt/bot/{strategy_id_safe}/docker-compose.yml up
ExecStop=/usr/bin/docker compose -f /opt/bot/{strategy_id_safe}/docker-compose.yml down
Restart=on-failure
RestartSec=30
StartLimitInterval=300
StartLimitBurst=5

[Install]
WantedBy=multi-user.target
```

## Multi-Strategy Deployment

The default deployment model is: 1 strategy = 1 container = 1 systemd unit (or 1 launchd plist). This maps directly to the process isolation model in `multi-strategy.md` sections 5 and 6.

### Naming Convention
- Container and service names follow the pattern `bot-{strategy_id_safe}` where `strategy_id_safe` replaces all dots in `strategy_id` with dashes.
- Example: strategy `binance.swap.mean-revert.btcusdt.5m.v1` becomes service `bot-binance-swap-mean-revert-btcusdt-5m-v1`.

### Strategy Resolution
Each container reads its `strategy_id` from the `STRATEGY_ID` environment variable. The bot process uses this to:
1. Look up its entry in `config/registry.toml`.
2. Resolve all paths (config, state, logs) from the registry entry.
3. Verify `enabled == true` and `state` permits the requested mode before starting.

### Risk Aggregator
The risk aggregator (`src/risk/aggregator.py`) is deployed as a separate container/service, scoped per `risk_group`. It reads the registry to discover which strategies belong to its group and monitors their state and logs. See the "Cross-Strategy Risk Aggregation" section in `risk-management.md`.

### Shared-Process Exception
Running multiple strategies in a single process is an explicit opt-in for non-live or tightly-coupled bundles. It MUST be documented in `CLAUDE.md` Zone C with justification. The orchestrator MUST NOT default to it.

## CI/CD Pipeline

- Lint + type check on every push
- Run tests (unit + testnet integration) on PR
- Build Docker image on merge to main
- Deploy to staging first, then production (manual approval)
- Keep last 3 Docker image versions for rollback

## Rollback Procedure

1. Stop current bot: `docker compose down`
2. Verify all positions are closed or transferred
3. Switch to previous image version
4. Start: `docker compose up -d`
5. Verify health check passes
6. Monitor for 15 minutes before confirming

## macOS launchd (Optional Alternative)

> **Note**: For local/development deployment on macOS. For production, prefer Docker or systemd.

For local/dev deployment on macOS (alternative to Docker):

### plist Template
One plist per strategy. Use `strategy_id_safe_svc` (dots replaced by dashes) in the Label for consistency with the Docker/systemd naming. Per-strategy logs go under `logs/strategies/{strategy_id}/`.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "...">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.trading.{strategy_id_safe_svc}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/path/to/.venv/bin/python</string>
        <string>-m</string>
        <string>src.bot.main</string>
        <string>--strategy-id</string>
        <string>{strategy_id}</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/path/to/project</string>
    <key>KeepAlive</key>
    <true/>
    <key>ThrottleInterval</key>
    <integer>30</integer>
    <key>StandardOutPath</key>
    <string>/path/to/project/logs/strategies/{strategy_id}/stdout.log</string>
    <key>StandardErrorPath</key>
    <string>/path/to/project/logs/strategies/{strategy_id}/stderr.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>STRATEGY_ID</key>
        <string>{strategy_id}</string>
        <key>DOTENV_PATH</key>
        <string>/path/to/project/config/strategies/{strategy_id}.env</string>
    </dict>
</dict>
</plist>
```

### Service Management
```bash
# Load and start
launchctl load ~/Library/LaunchAgents/com.trading.{strategy_id_safe_svc}.plist

# Stop and unload
launchctl unload ~/Library/LaunchAgents/com.trading.{strategy_id_safe_svc}.plist

# Check status
launchctl list | grep trading

# View logs
tail -f /path/to/project/logs/strategies/{strategy_id}/stdout.log
```

### Notes
- KeepAlive: auto-restart on crash (respects ThrottleInterval)
- KillSwitch (exit code 0): does NOT trigger restart (clean exit)
- Use for development/single-machine setups; prefer Docker for production
