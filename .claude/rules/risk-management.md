# Risk Management Rules

## Mandatory Requirements for Automated Trading Systems

All EAs and Bots MUST implement the following risk controls:

### Position Management
- **Max position size**: Must not exceed N% of account balance (default: 2%)
- **Max concurrent positions**: Must not exceed defined limit
- **Cross-pair correlation**: Limit same-direction positions on highly correlated pairs

### Loss Limits
- **Per-trade max loss**: 1-2% of account balance
- **Daily max loss**: 5% of account balance
- **Weekly max loss**: 10% of account balance
- **Monthly max loss**: 20% of account balance

### Emergency Stop Mechanism (Mandatory Implementation)
```
1. Daily loss limit reached    → Stop new positions for the day
2. Max drawdown reached        → Close all positions + stop EA
3. Abnormal spread detected    → Pause new entries
4. Consecutive API errors      → Alert + stop trading
5. Sudden account balance drop → Full stop + notification
```

### Per-Strategy Config Ownership
Per-strategy risk limits (max position size, daily loss, drawdown, stop loss) MUST live in the per-strategy TOML at `config/strategies/{strategy_id}.toml`, NOT in shared config files. This ensures adding or changing one strategy never affects another. See `multi-strategy.md` section 5 for the per-strategy config schema.

### Stop Loss
- **Mandatory**: Every position MUST have a stop loss
- Strategies without stop loss are NOT permitted
- Trailing stops recommended

## Backtest Risk Evaluation

### Mandatory Report Items
- Max drawdown (amount, ratio, duration)
- Sharpe Ratio / Sortino Ratio / Calmar Ratio
- Win rate / Profit Factor / Average risk-reward ratio
- Max consecutive losses
- Recovery Factor

### Warning Thresholds
| Metric | Warning | Danger |
|--------|---------|--------|
| Max Drawdown | > 20% | > 30% |
| Sharpe Ratio | < 1.0 | < 0.5 |
| Win Rate | < 40% | < 30% |
| Profit Factor | < 1.5 | < 1.2 |
| Recovery Factor | < 2.0 | < 1.0 |

## Multi-Layer Safety Gates (Production Bots)

Beyond basic risk limits, production bots MUST implement exchange-specific safety gates:

### Gate System
| Gate | Trigger | Action |
|------|---------|--------|
| **KillSwitch** | File-based (`data/KILL`) or signal | Immediate full stop, close all positions |
| **Exchange Penalty Gate** | Exchange-specific deviation/penalty mechanisms approach threshold (e.g., FX-Spot deviation on certain exchanges) | Block new entries |
| **Checkpoint Gate** | Approaching exchange-specific checkpoint (funding, settlement, maintenance, etc.) | Close positions before checkpoint |
| **Maintenance Gate** | Approaching exchange maintenance window | Close positions, pause bot |
| **Margin Monitor** | Margin ratio exceeds alert threshold (e.g., >80%) | Block entries; >95% → emergency close |
| **Daily Loss Limit** | Cumulative daily PnL exceeds threshold | Stop new entries for the day |

### Position Reconciliation
- Compare local position state with exchange state **every 30 seconds**
- Exchange state is always the source of truth
- If mismatch detected 3 consecutive times → emergency shutdown + alert
- On startup: always query exchange before resuming

### Safety Check Ordering
```
Pre-trade check sequence:
1. KillSwitch active?         → BLOCK (exit code 0, no restart)
2. Maintenance window?        → BLOCK (close positions)
3. Exchange checkpoint near?   → BLOCK (close positions)
4. Exchange penalty gate?      → BLOCK new entries
5. Margin ratio > threshold?  → BLOCK new entries
6. Daily loss limit hit?      → BLOCK new entries
7. Position size limit?       → BLOCK if exceeded
8. All clear                  → ALLOW trade
```

## Cross-Strategy Risk Aggregation

When multiple strategies run in parallel, per-strategy risk controls are necessary but not sufficient. A separate aggregator service enforces account- and group-level limits across all strategies. See `multi-strategy.md` section 6 for the full specification.

### Aggregator Service
- A dedicated process (`src/risk/aggregator.py`) monitors all strategies within a given `account_scope` and `risk_group`.
- `risk_group` is a project-defined label assigned per strategy in `config/registry.toml`. Common patterns: one bucket per account, one per strategy family, or a shared bucket for cross-venue hedged books.
- `account_scope` identifies the exchange/broker account. Multiple `account_scope` values may share a `risk_group` for cross-venue aggregation.
- The aggregator config (`config/risk_groups.toml`) maps groups to strategies and thresholds.

### Aggregated Metrics (Minimum)
The aggregator MUST track at least:
- Net exposure (per-symbol, per-asset, group total)
- Gross exposure (sum of absolute notional)
- Daily realized + unrealized PnL (per strategy, group total)
- Drawdown vs. start-of-day and high-water mark (group total)
- Open position count, open order count
- Margin usage / leverage (per `account_scope`)

### Enforcement: Soft Cap vs Hard Cap
| Breach | Action |
|---|---|
| Soft cap (e.g. group daily loss > 3%) | All strategies in `risk_group` block new entries |
| Hard cap (e.g. group daily loss > 5%) | All strategies in `risk_group` block new entries AND flatten existing positions |
| Margin / emergency (e.g. margin ratio > 95%) | Flatten-and-halt for all strategies in `account_scope` |
| Per-strategy breach (existing rules) | Only that strategy stops; aggregator unaffected |

Thresholds are project-configurable; defaults match the Warning Thresholds table above.

### Reconciliation Source
The aggregator MUST reconcile against exchange/broker state, NOT self-reported bot state. The aggregator queries the venue at least every 60 seconds. Self-reported metrics from bot logs are used for real-time approximation but never as the authoritative source for enforcement decisions.

Note the two reconciliation intervals defined in this document:
- **Per-bot reconciliation (every 30 seconds, see Position Reconciliation above)**: a single bot compares its local state against the venue for crash-recovery and divergence detection. Scope is one strategy.
- **Aggregator reconciliation (every 60 seconds)**: the cross-strategy aggregator queries the venue to refresh authoritative balances/positions for `risk_group`-level enforcement. Scope is all strategies in a `risk_group` / `account_scope`.

On aggregator reconciliation failure, fail-closed behavior is specified in `multi-strategy.md` section 6 ("Reconciliation failure behavior").
