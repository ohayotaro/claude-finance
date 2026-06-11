---
name: bot-deploy
description: Deploy trading bots with Docker, systemd, and environment management. Includes health checks, logging, and Codex deployment review.
agent: infra-ops
context: fork
allowed-tools: "Bash(python *) Bash(docker *) Bash(uv *) Bash(codex *) Bash(curl *) Read Write Edit Glob Grep"
---

# Bot Deployment

Containerize and deploy trading bots to production.

## Workflow

### Step 0: Validate Strategy is Registered

**Required argument**: `strategy_id` (first positional argument, e.g., `/bot-deploy binance.swap.mean-revert.btcusdt.5m.v1`).

If `strategy_id` is not provided, refuse with:
```
Error: strategy_id is required.
Usage: /bot-deploy {strategy_id}

Register a strategy first: /strategy-register register
```

Validation steps:
1. Call `/strategy-register show {strategy_id}` to confirm the entry exists.
2. Verify the current `state` is `testnet` (for first live deploy) or `live` (for re-deploy / update).
3. If `state == "draft"`, refuse with: "Strategy is still in `draft` state. Complete testnet validation and run `/strategy-register transition {strategy_id} testnet` first."
4. If `state` is `deprecated` or `retired`, refuse with: "Strategy `{strategy_id}` is `{state}`. Register a new version via `/strategy-register register`."
5. Extract `config_path`, `state_path`, `log_path`, `risk_group`, and `account_scope` from the registry entry.
6. Derive `strategy_id_safe_svc` by replacing all dots in `strategy_id` with dashes (for Docker/systemd naming).

### Step 1: Environment Assessment
Ask the user:
1. Deployment target (local Docker, VPS, cloud)
2. Uptime requirements (24/7, market hours only)
3. Monitoring preference (simple logging, Prometheus+Grafana)

Note: "Number of bots to deploy" is no longer asked -- each `/bot-deploy` invocation deploys exactly one strategy. To deploy multiple strategies, invoke `/bot-deploy` once per `strategy_id`.

### Step 2: Dockerfile Generation
Using the **infra-ops** subagent, create (if not already present -- the Dockerfile is shared across strategies):
- Multi-stage Dockerfile (builder + runtime)
- `.dockerignore` file
- Non-root user configuration
- Health check endpoint
- The entrypoint accepts `STRATEGY_ID` as an environment variable

### Step 3: Docker Compose Configuration (Per-Strategy)
Generate a per-strategy Docker Compose file at `docker/{strategy_id_safe_svc}/docker-compose.yml`:
- Service name: `bot-{strategy_id_safe_svc}` (per `deployment.md` naming convention)
- `STRATEGY_ID` environment variable set to `{strategy_id}`
- Per-strategy `.env` file path: `docker/{strategy_id_safe_svc}/.env`
- Volume mounts for:
  - `config/` (read-only)
  - `state/strategies/{strategy_id}/` (read-write, persistent)
  - `logs/strategies/{strategy_id}/` (read-write)
- Restart policy: `unless-stopped`
- Health check configuration
- Log driver configuration (JSON, max-size per `monitoring.md`)
- Network configuration

Do NOT generate a single shared `docker-compose.yml` for all strategies. Each strategy has its own deployment unit.

### Step 4: Environment Setup (Per-Strategy)
- Generate `docker/{strategy_id_safe_svc}/.env` from a template
- Configure secrets (API keys, webhook URLs) -- remind the user to fill in actual values
- Set `STRATEGY_ID={strategy_id}`
- Reference the per-strategy config path
- Configure log level and output

### Step 5: Health Check Implementation
Add to bot (if not already implemented by `/bot-develop`):
```python
# GET /health → 200 OK
{
    "status": "healthy|degraded|unhealthy",
    "strategy_id": "{strategy_id}",
    "uptime_seconds": N,
    "exchange_connected": true|false,
    "last_heartbeat": "ISO8601",
    "open_positions": N,
    "daily_pnl": X.XX
}
```

### Step 6: systemd Service (VPS) -- Per-Strategy
Generate a per-strategy systemd unit file `bot-{strategy_id_safe_svc}.service`:
- `Description=Trading Bot - {strategy_id}`
- `EnvironmentFile` pointing to the per-strategy `.env`
- `ExecStart` referencing the per-strategy `docker-compose.yml`
- Restart on failure with backoff
- Log to journald

### Step 7: Risk Aggregator Deployment
Check whether a risk aggregator service is already deployed for this strategy's `risk_group`:
- If not deployed, generate and deploy `risk-aggregator-{risk_group}` as a separate container/service.
- The aggregator discovers strategies in its group by reading `config/registry.toml`.
- See `multi-strategy.md` section 6 for aggregator requirements.

### Step 8: Live Promotion Checklist

**This step applies only when transitioning from `testnet` to `live`.** If re-deploying an already `live` strategy, skip to Step 9.

Before transitioning to `live`, verify ALL six preconditions from `multi-strategy.md` section 4. Present as a checklist:

```
Live Promotion Checklist for {strategy_id}:
[ ] 1. Testnet validation evidence present (within last 7 days)
[ ] 2. MAX_POSITION_SIZE set in per-strategy config ({config_path})
     MAX_DAILY_LOSS set in per-strategy config ({config_path})
[ ] 3. Stop loss implementation verified (in strategy code or via /team-review)
[ ] 4. KillSwitch end-to-end test passed (touch data/KILL -> bot exits cleanly)
[ ] 5. Notification webhook smoke test passed (test alert reached channel)
[ ] 6. /risk-report generated within last 7 days for {strategy_id}
```

For each item, check programmatically where possible (e.g., parse config for risk limits, check report timestamps). Mark `[x]` for verified, `[ ]` for unverified.

If ANY item is `[ ]`, refuse the transition and report which items failed.

If ALL items are `[x]`, call `/strategy-register transition {strategy_id} live`. This skill is the ONLY authorized caller of the `testnet -> live` transition.

### Step 9: Live-Trading Acknowledgment

Remind the operator about the daily live-trading acknowledgment gate from `security.md`:
```bash
mkdir -p .claude/state
touch .claude/state/live-trading-$(date +%Y-%m-%d).ack
```
This is separate from the registry transition. The acknowledgment is valid for 24 hours and must be re-created daily. Without it, the `live-trading-gate.py` hook will block live commands.

### Step 10: Deploy
1. Build image: `docker compose -f docker/{strategy_id_safe_svc}/docker-compose.yml build`
2. Start in detached mode: `docker compose -f docker/{strategy_id_safe_svc}/docker-compose.yml up -d`
3. Verify health: `curl localhost:{port}/health`
4. Check logs: `docker compose -f docker/{strategy_id_safe_svc}/docker-compose.yml logs -f`
5. Verify log output at `logs/strategies/{strategy_id}/bot.jsonl`

### Step 11: Post-Deploy Verification
- Health check passing (includes `strategy_id` in response)
- Exchange connected
- Orders executing (testnet first for new deployments)
- Logs flowing to `logs/strategies/{strategy_id}/bot.jsonl`
- `strategy_id` present in every log event
- Alerts configured and tested
- Risk aggregator for `{risk_group}` is healthy and monitoring this strategy
