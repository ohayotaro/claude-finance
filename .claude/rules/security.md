# Security Rules

## API Key Management

### Mandatory Rules
- API keys MUST be loaded via **environment variables** (`.env` file + python-dotenv)
- Hardcoding keys in source code is **strictly prohibited**
- `.env` file MUST be in `.gitignore`
- Separate test and production keys

### Recommended .env Structure
```
# .env (gitignored)
BINANCE_API_KEY=xxx
BINANCE_SECRET_KEY=xxx
BYBIT_API_KEY=xxx
BYBIT_SECRET_KEY=xxx
MT5_LOGIN=xxx
MT5_PASSWORD=xxx
MT5_SERVER=xxx
```

## Exchange API Security

- **IP restriction**: Set IP whitelist on API keys (recommended)
- **Least privilege**: Grant only necessary permissions (read-only, trade, withdrawal separated)
- **No withdrawal permission**: Automated trading API keys MUST NOT have withdrawal rights
- **Rate limiting**: Implement logic to respect API rate limits

## Wallet / Address Management

- Hardcoding wallet addresses is **prohibited**
- Deposit/withdrawal addresses via config files only
- Implement address verification mechanism on change

## Test Environment

- **Testnet mandatory**: Always verify on testnet before production deployment
  - Binance Testnet
  - bybit Testnet
  - MT5 Demo account
- NEVER mix test and production API keys

## Live-trading acknowledgment

A PreToolUse hook (`.claude/hooks/live-trading-gate.py`) blocks Bash commands that initiate live trading unless a valid acknowledgment is on disk. This prevents the most common failure mode of an automated trading orchestrator: a live execution path running with the safety preconditions skipped.

### What counts as a live-trading command
- `BOT_MODE=live ...`
- `BOT_ENVIRONMENT=production ...`
- `--mode live` / `--mode=live`
- `--live` (standalone flag — `--live-stream` etc. do not match)
- `--env-file *.env.production` or `*.env.live`

### How the gate decides
1. If `data/KILL` exists, every live command is blocked. The KillSwitch is authoritative.
2. Otherwise the gate looks for a fresh acknowledgment file under `.claude/state/`. Any `live-trading-*.ack` whose mtime is within the last 24 hours unlocks live commands.
3. If no fresh acknowledgment is present, the command is blocked with the checklist below.

### Checklist before acknowledging

Confirm ALL of the following are true for the strategy / bot you are about to run live:

- [ ] Testnet validation passed within the last 7 days
- [ ] `MAX_POSITION_SIZE` and `MAX_DAILY_LOSS` environment variables are set
- [ ] Stop loss is implemented in the strategy code (no live trading without SL)
- [ ] KillSwitch verified end-to-end: `touch data/KILL` causes the bot to exit cleanly
- [ ] Notification webhook smoke-tested (a test alert reached the channel)
- [ ] Risk limits verified in per-strategy config

When everything above is true, acknowledge with:

```bash
mkdir -p .claude/state
touch .claude/state/live-trading-$(date +%Y-%m-%d).ack
```

The acknowledgment is valid for 24 hours from creation. Re-create it daily — the friction is intentional. `.claude/state/` is gitignored, so acknowledgments do not propagate across machines.

### Removing or bypassing the gate
The gate is a safety mechanism. Do not delete or disable the hook in `settings.json` to "unblock" a stuck workflow — that defeats the entire purpose. If a live command is incorrectly classified, fix the regex in `live-trading-gate.py` rather than disabling the gate.

## Code Security

- No sensitive information in log output
- No API keys/secrets in error messages
- Implement HTTP request signature verification
- Never disable SSL/TLS certificate verification
