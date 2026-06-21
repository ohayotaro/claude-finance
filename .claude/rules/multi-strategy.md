# Multi-Strategy Management Rules

This file defines the contract for running **many strategies in parallel** inside a single project. The orchestrator's skills MUST treat strategies as first-class, isolated, registry-managed units. Switching strategies MUST NOT require rewriting shared files — every strategy has its own config / state / logs / process unit, addressed by a stable `strategy_id`.

## 1. First Principles

1. **Identity is permanent**: every live or runnable strategy has a `strategy_id` registered in `config/registry.toml`. Code, logs, state, and reports refer to strategies only by `strategy_id`.
2. **Isolation by default**: per-strategy config file, per-strategy SQLite DB, per-strategy log file, one process / container per strategy in production.
3. **Aggregation by design**: all logs include `strategy_id`. A separate risk aggregator service enforces account- or `risk_group`-level limits across strategies.
4. **Registry is the source of truth**: skills MUST NOT invent ad-hoc identifiers. New strategies are created by `/strategy-register`. Lifecycle transitions are gated by registry state.
5. **Adding a strategy never modifies another strategy's files.** If a skill needs to touch a file shared between strategies, that file is a bug — split it.

## 2. `strategy_id` Schema

### Format
```
<venue>.<market>.<logic_slug>.<symbol>.<timeframe>.v<major>
```

Regex (canonical):
```
^[a-z0-9]+(?:-[a-z0-9]+)*\.[a-z0-9]+(?:-[a-z0-9]+)*\.[a-z0-9]+(?:-[a-z0-9]+)*\.[a-z0-9]+(?:-[a-z0-9]+)*\.[1-9][0-9]*[smhdw]\.v[1-9][0-9]*$
```

### Components

| Component | Meaning | Examples |
|---|---|---|
| `venue` | Exchange / broker identifier | `binance`, `bybit`, `oanda`, `ibkr`, `tse` |
| `market` | Market segment | `spot`, `swap`, `future`, `option`, `fx`, `cash` |
| `logic_slug` | Strategy family name | `mean-revert`, `ma-cross`, `breakout`, `pairs` |
| `symbol` | Canonical lowercase instrument code | `btcusdt`, `usdjpy`, `7203t` |
| `timeframe` | Bar interval | `1m`, `5m`, `1h`, `4h`, `1d`, `1w` |
| `v<major>` | Compatibility-major version | `v1`, `v2`, `v3` |

### Rules
- **Lowercase only**, components joined by `.`, intra-component words by `-`.
- **Same logic on a different symbol → different `strategy_id`**. Do not multiplex.
- **`v<major>` bumps only when changes break state/risk/backtest comparability** (e.g. signal logic change, position-sizing semantic change). Bug fixes and parameter tuning do NOT bump major — they live in `logic_version` (semver string in the registry).
- **Symbol canonicalization is mandatory**: `BTC/USDT` → `btcusdt`, `7203.T` → `7203t`. The orchestrator MUST refuse to register two strategies whose symbols differ only by formatting.

### Examples
```
binance.swap.mean-revert.btcusdt.5m.v1
oanda.fx.ma-cross.usdjpy.1h.v2
ibkr.cash.pairs.spy-iwm.1d.v1
tse.cash.breakout.7203t.4h.v1
```

### Derived safe-name forms

The dot-separated `strategy_id` is unsuitable as-is for some filesystems and service-name conventions. Two derived forms are defined:

| Name | Derivation | Used by | Example |
|---|---|---|---|
| `strategy_id_safe_svc` | replace `.` with `-` | Docker container names, systemd unit names, launchd Label, logger tags | `binance-swap-mean-revert-btcusdt-5m-v1` |
| `strategy_id_safe_fs` | replace `.` with `_` | MQL5 source/preset filenames (MetaEditor rejects dots in identifiers) | `binance_swap_mean_revert_btcusdt_5m_v1` |

Consumers MUST use these explicit names. When you read `{strategy_id_safe}` in any older doc, it refers to whichever variant fits the domain (filesystem -> `_fs`, service -> `_svc`); update on contact.

## 3. MagicNumber Allocation (MQL5)

### Reserved range
- **Orchestrator-managed**: `20_000_000` – `89_999_999` (70M values).
- Values outside this range are treated as external / manual / legacy. The orchestrator MUST NOT issue them and MUST NOT assume ownership.

### Allocation algorithm
```
candidate = 20_000_000 + (hash32(strategy_id) mod 70_000_000)
while candidate is taken in registry:
    magic_salt += 1
    candidate = 20_000_000 + (hash32(strategy_id + "#" + str(magic_salt)) mod 70_000_000)
magic_number = candidate
```

- `hash32` is a stable 32-bit hash (CRC32 or xxhash32). Implementation MUST be deterministic across machines.
- The final `magic_number` and `magic_salt` are **frozen** in `config/registry.toml`. Runtime code reads the assigned value; it does NOT re-derive.
- The EA template MUST read `MagicNumber` from the per-strategy config file, not hardcode it.

### Account-type caveats
- **Hedging account**: per-strategy MagicNumber gives clean position attribution. Default assumption.
- **Netting account**: positions are aggregated at the symbol level regardless of MagicNumber. MagicNumber still works for order tagging and history filtering, but position state cannot be attributed back to one strategy from the aggregated position alone.

### Shared-symbol rule on netting accounts

On netting accounts, two strategies running on the SAME `(venue, account_scope, symbol)` cannot be reconciled from venue state alone. To prevent reconciliation false-positives and silent position contamination:

- `/strategy-register register` MUST refuse a second strategy whose `(venue, account_scope, symbol)` triple already exists with `runtime = "mql5"` AND a hedging-vs-netting flag indicating netting (project-defined in `config/registry.toml` `[accounts]` block, see section 4).
- The refusal can be overridden ONLY by registering an explicit netting coordinator module (currently out of scope -- a future addition). Without the coordinator, the contract is "one strategy per symbol per netting account".
- Bots and EAs operating on netting accounts MUST reconcile against their strategy's own expected contribution (computed from their order history), NOT against the raw venue position.

Hedging accounts are unaffected: multiple strategies on the same symbol are allowed and distinguished by MagicNumber.

## 4. `config/registry.toml`

### Location and ownership
- Path: `config/registry.toml` (repo-tracked).
- Schema version: declared at top, currently `1`.
- Secrets MUST NOT live here. Credentials remain in env vars / `.env`.

### Schema
```toml
schema_version = 1

[defaults]
state_dir = "state/strategies"
log_dir = "logs/strategies"
config_dir = "config/strategies"
magic_range_start = 20_000_000
magic_range_end = 89_999_999

# Per-account metadata. Required when account_scope is referenced by an MQL5
# strategy entry. Drives the netting shared-symbol rule (section 3).
[[accounts]]
name = "broker-prop-1"                              # required, matches account_scope on strategies
position_mode = "netting"                           # required for mql5, enum: netting | hedging
notes = ""                                          # optional

[[strategies]]
id = "binance.swap.mean-revert.btcusdt.5m.v1"      # required, must match strategy_id regex
family_id = "mean-revert"                          # required, free-form slug
logic_version = "1.2.0"                            # required, semver
runtime = "python"                                 # required, enum: python | mql5
venue = "binance"                                  # required
market = "swap"                                    # required
symbol = "BTCUSDT"                                 # required, exchange-native form
timeframe = "5m"                                   # required
account_scope = "binance-main"                     # required, project-defined account label
risk_group = "crypto-main"                         # required, project-defined risk bucket
state = "draft"                                    # required, enum: draft | testnet | live | deprecated | retired
enabled = false                                    # required, bool — runtime gate independent of state
config_path = "config/strategies/binance.swap.mean-revert.btcusdt.5m.v1.toml"  # required
state_path = "state/strategies/binance.swap.mean-revert.btcusdt.5m.v1"          # required
log_path  = "logs/strategies/binance.swap.mean-revert.btcusdt.5m.v1"            # required
db_path   = "state/strategies/binance.swap.mean-revert.btcusdt.5m.v1/state.db"  # optional
magic_number = 24561783                            # required when runtime = "mql5"
magic_salt = 0                                     # optional, default 0
created_at = "2026-05-14T00:00:00Z"                # required, RFC3339
updated_at = "2026-05-14T00:00:00Z"                # required, RFC3339
owner = "bot-engineer"                             # optional
notes = ""                                         # optional
```

### Lifecycle states
```
draft  →  testnet  →  live  →  deprecated  →  retired
   │         │
   └─────────┴───→ deprecated   (skip allowed)
```

- **No backward transitions.** Once a strategy reaches `deprecated`, it cannot return to `live` — register a new major version (`v2`) instead.
- `enabled` is an orthogonal runtime switch. `state = live` AND `enabled = false` means "registered for production but currently paused".

### Skill write permissions

| Skill | Allowed registry writes |
|---|---|
| `/strategy-register` | Create entries, transition `draft ↔ deprecated`, edit `notes` / `owner` |
| `/strategy-design` | Create `draft` entries; never transitions |
| `/bot-develop` | Fill runtime-specific fields for the registered strategy (e.g., `db_path`); never transitions |
| `/ea-generate` | Allocate `magic_number` / `magic_salt`; fill EA-specific fields; never transitions |
| `/bot-deploy` | `testnet → live` (after preconditions); `live → deprecated`; toggle `enabled` |
| All other skills | Read-only |

### Preconditions for `live` promotion
`/bot-deploy` MUST verify ALL of the following before transitioning a strategy to `live`:
1. Testnet validation evidence present (e.g., last 7 days of `/backtest` or testnet logs).
2. `MAX_POSITION_SIZE`, `MAX_DAILY_LOSS` set in the per-strategy config.
3. Stop loss implemented (verified by `/codex-review` or equivalent evidence).
4. KillSwitch end-to-end test passed.
5. Notification webhook smoke test passed.
6. `/risk-report` generated within last 7 days for this `strategy_id`.

These mirror the existing live-trading gate (`security.md`), but are now per-strategy.

## 5. Isolation Requirements

### Per-strategy directory layout
```
config/
├── registry.toml                               # single source of truth
└── strategies/
    └── {strategy_id}.toml                      # per-strategy params, risk limits

state/strategies/
└── {strategy_id}/
    ├── state.db                                # SQLite (per-strategy)
    └── checkpoints/

logs/strategies/
└── {strategy_id}/
    ├── bot.jsonl
    └── bot.jsonl.{N}.gz                        # rotated

reports/
└── strategies/
    └── {strategy_id}/
        ├── backtest_{timestamp}.html
        └── risk_{timestamp}.md
```

### Per-strategy config TOML (minimum schema)
```toml
strategy_id = "binance.swap.mean-revert.btcusdt.5m.v1"

[runtime]
mode = "testnet"            # testnet | live | dry-run
symbol = "BTCUSDT"
timeframe = "5m"

[risk]
max_position_size = 0.01
max_daily_loss_pct = 2.0
stop_loss_pct = 1.0

[params]
# strategy-specific parameters

[notifications]
# Optional. Per-strategy alert routing. If absent, alerts fall back to the
# project-default channel. Risk-group aggregate alerts use risk_groups.toml,
# not this section.
# channel = "slack://#bot-alerts"
# severity_floor = "WARNING"   # only forward events >= this level
```

### Process / container model
- **Default**: 1 strategy = 1 process = 1 container.
- Docker Compose / systemd unit / launchd plist is generated per strategy by `/bot-deploy`.
- Shared-process multi-strategy mode is an **explicit opt-in** for non-live or tightly-coupled bundles; it MUST be documented in the project's `CLAUDE.md` Zone C with justification. The orchestrator MUST NOT default to it.

### Log isolation
- One JSONL file per strategy. Every event includes `strategy_id` (also when stored separately, for safe later concatenation).
- Aggregators MUST treat `strategy_id` as the partition key.

### State store abstraction (forward-compatible)
- Default backend: SQLite per strategy at `state_path/state.db` (WAL mode).
- The `StateStore` protocol (see `bot-development.md`) MUST be the only interface the bot uses. This preserves the option to swap to a central PostgreSQL / Redis backend later **without changing skill contracts**. Skills MUST NOT bypass `StateStore` to touch SQLite directly.

## 6. Risk Aggregation

### Aggregator service
- A separate process (`src/risk/aggregator.py`) reads logs / state of all strategies in a given `account_scope` and `risk_group`.
- Authoritative reconciliation source is the exchange / broker, not self-reported bot state. The aggregator MUST query the venue at least every 60 seconds.
- The aggregator publishes a soft-cap / hard-cap signal (file flag, IPC, or webhook) consumed by every bot in the group.

### Reconciliation failure behavior (fail-closed)
When the venue query fails (network error, rate-limit, venue maintenance):
1. Continue enforcing using the last-known venue state (cached). Do NOT silently switch to self-reported bot state.
2. Emit WARNING after 1 missed cycle (60s), CRITICAL after 3 (180s).
3. After 5 consecutive failures (5 minutes), the aggregator enters **fail-closed** mode: block new entries across the entire `risk_group` until reconciliation recovers. Existing positions are NOT auto-flattened on reconciliation failure alone (that requires an actual breach signal, not absence of signal).
4. Recovery: once a venue query succeeds, the failure counter resets and enforcement resumes from the fresh snapshot.

### Malformed log handling
If a strategy emits invalid JSON or an event missing required fields (`strategy_id`, `event`, `ts`):
- The aggregator MUST skip the line, emit a WARNING log with the strategy_id (extracted heuristically if possible) and the offset, and continue.
- The aggregator MUST NEVER crash on parse errors. A single misbehaving strategy log MUST NOT take down aggregate enforcement for the rest of the group.
- If a strategy emits >100 malformed lines per minute, the aggregator emits CRITICAL and quarantines that strategy from contribution calculations (still counted in position reconciliation via venue).

### Metrics aggregated (minimum)
- Net exposure (per-symbol, per-asset, group total)
- Gross exposure (sum of absolute notional)
- Daily realized + unrealized PnL (per strategy, group total)
- Drawdown vs. start-of-day and high-water mark (group total)
- Open position count, open order count
- Margin usage / leverage (per `account_scope`)

### Enforcement
| Breach | Action |
|---|---|
| Soft cap (e.g. group daily loss > 3%) | All strategies in `risk_group` block new entries |
| Hard cap (e.g. group daily loss > 5%) | All strategies in `risk_group` block new entries AND flatten existing positions |
| Margin / emergency (e.g. margin ratio > 95%) | Flatten-and-halt for all strategies in `account_scope` |
| Per-strategy breach (existing rules) | Only that strategy stops; aggregator unaffected |

Thresholds are project-configurable; defaults match `risk-management.md` warning levels.

### `risk_group` scope
- Project-defined label. Common patterns:
  - Single account: `risk_group = account_scope` (one bucket per account)
  - Cross-venue hedged book: shared `risk_group` across multiple `account_scope`s
  - Strategy family isolation: separate `risk_group` per family
- The aggregator config (`config/risk_groups.toml` — created by `/init-finance`) maps groups → strategies → thresholds.

## 7. Skill Contract

All trading skills that operate on a strategy MUST:
1. Accept `strategy_id` as a required parameter (named arg, not positional inference).
2. Resolve all paths via `config/registry.toml` lookup. Never hardcode `config/strategies/foo.toml`.
3. Refuse to act on `strategy_id`s not present in the registry (with a hint to run `/strategy-register`).
4. Refuse `live`-mode actions if `state != "live"` OR `enabled == false`.
5. Tag all generated artifacts (logs, reports, code) with `strategy_id` and `logic_version`.

## 8. Anti-Patterns (Forbidden)

- Editing a shared file when adding a strategy ("just bump the strategy in main.py").
- Reusing a `strategy_id` across symbols ("BTC and ETH on the same id, with a symbol flag").
- Hardcoding MagicNumber in EA source.
- Bypassing `StateStore` to read another strategy's SQLite directly.
- Letting `bot-develop` allocate `strategy_id` ad-hoc. Allocation is `/strategy-register`'s job.
- Manual edits to `registry.toml` outside the orchestrator skills (loses audit trail and risks invariant violations).
- Skipping registry lookup ("I know the path, I'll write it directly"). The point of the registry is that paths can move.

## 9. Migration Note

When importing an existing single-strategy project:
1. Run `/strategy-register` to mint a `strategy_id` for the current code.
2. Move config / state / logs into the per-strategy directories.
3. Wrap existing state access through `StateStore`.
4. Update deployment to per-strategy container.
5. Verify with `/codex-review` before promoting to `live`.

## 10. Runtime Control-Plane Semantics

The registry is a control plane consumed by long-running bots / EAs / aggregators. This section defines what happens when control-plane state changes while consumers are running.

### Runtime detection of registry changes
- Bots MUST re-read their registry entry at every heartbeat (default 60 seconds; see `monitoring.md`).
- If `enabled == false` OR `state` is not `live`, the bot enters **graceful shutdown**: stop accepting new entries, await fills/cancels on open orders, close or hand off positions per the bot's configured exit policy, emit `bot_stopped { reason: "registry_disabled" }`, exit cleanly (exit code 0 — does NOT trigger restart).
- If `state` transitions backward (forbidden — should never happen), the bot MUST emit `safety_triggered { gate: "registry_invariant_violation" }` and shut down.
- Path fields (`config_path`, `state_path`, `log_path`, `db_path`) MUST NOT be re-resolved at runtime. They are bound at startup. A registry edit that changes paths takes effect only after restart.

### Aggregator health gate
- A strategy bot MUST NOT start trading (place orders) until the risk aggregator for its `risk_group` reports healthy.
- "Healthy" means: the aggregator has completed at least one successful venue reconciliation cycle in the last 120 seconds AND is not in fail-closed mode (see section 6).
- On startup, the bot polls the aggregator health endpoint / status file every 5 seconds for up to 60 seconds. If still unhealthy, the bot emits `safety_triggered { gate: "aggregator_unhealthy" }` and refuses to start order placement (heartbeat continues so monitoring sees the bot alive).
- This rule applies to live mode only. Testnet and dry-run modes log an INFO event but do not block.

### Per-strategy KillSwitch
The existing global KillSwitch (`data/KILL`, see `security.md`) halts all strategies. Multi-strategy projects also support per-strategy halts:
- Per-strategy KillSwitch file: `data/KILL.{strategy_id}` (any non-empty file is a kill).
- Each bot checks BOTH `data/KILL` AND `data/KILL.{strategy_id}` at every safety-check cycle (existing 1-second cadence per `bot-development.md`).
- Either kill triggers immediate full stop of that strategy (exit code 0). The global kill stops all; the per-strategy kill stops only the matching one.
- The live-trading gate hook (`.claude/hooks/live-trading-gate.py`) MUST treat any `data/KILL*` file as a kill signal when matching the global-kill behavior; the per-strategy variant only stops the matching `STRATEGY_ID` invocation.

### Reader-side path validation
Every consumer that resolves a path from the registry MUST validate it before use:
- The resolved path MUST be relative (or, after joining with the project root, MUST resolve via `os.path.commonpath` to remain inside the project root).
- The resolved path MUST NOT contain `..` segments after normalization.
- The resolved path MUST match the prefix declared in `[defaults]` for that path kind (`config_path` under `config_dir`, `state_path` under `state_dir`, `log_path` under `log_dir`).
- On violation, the consumer MUST refuse to open the file, emit a CRITICAL log, and exit. Do NOT silently fall back to a default.

This protects against a malformed or maliciously-edited registry entry pointing at `/etc/passwd` or `../../sensitive`. The `audit` workflow checks the same invariants at registry-write time; reader-side validation is defense in depth.

### Schema version and migration
- `schema_version` at the top of `registry.toml` is currently `1`.
- Consumers MUST refuse to operate on an unknown future `schema_version` (fail-closed). They emit CRITICAL and exit.
- Migration when bumping `schema_version`:
  1. Single writer (`/strategy-register migrate`) is the ONLY sanctioned migration path. Manual TOML edits across versions are forbidden.
  2. Before migration: write a timestamped backup at `config/registry.toml.bak.{from_version}.{rfc3339}`.
  3. After migration: bump `schema_version` atomically with the schema changes (same temp-file + os.replace).
  4. Forward compatibility is best-effort, not contractual. A `v1` consumer is allowed to refuse a `v2` registry.
  5. Backward compatibility is NOT supported: once migrated, the registry cannot be downgraded.

### Cross-machine and multi-developer safety
`fcntl.flock` only protects against concurrent registrations on a single host. In a multi-developer / multi-machine workflow:
- The repository's main branch is the **single authoritative registrar**. PRs that modify `config/registry.toml` MUST trigger CI to run `/strategy-register audit` AND check for MagicNumber uniqueness, regex compliance, and lifecycle-state validity against the merge base.
- Merge conflicts in `registry.toml` MUST be resolved by re-running `/strategy-register register` for any newly-registered strategies (which will reallocate MagicNumber if it collides with main). Manual conflict resolution is forbidden — the salt-collision algorithm may need to re-run.
- Two developers registering the same `strategy_id` (same venue/market/logic/symbol/timeframe/major) at the same time is a project-design error: the canonicalization rule in section 2 ensures the second registration is rejected on merge regardless of which branch landed first.
- CI MUST emit a clear error if a merge would introduce duplicate `magic_number` or duplicate `id`. The orchestrator does not auto-resolve these — they require human review (typically: bump one of the strategies' major version).
