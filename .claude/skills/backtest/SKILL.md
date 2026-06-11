---
name: backtest
description: Execute trading strategy backtests with performance metrics, statistical validation via Codex, and optional Gemini chart interpretation.
agent: quant-analyst
allowed-tools: "Bash(python *) Bash(pytest *) Bash(codex *) Bash(gemini *) Read Write Edit Glob Grep"
---

# Backtest Execution

Run backtests and generate comprehensive performance reports.

## Workflow

### Step 0: Validate Strategy is Registered

**Required argument**: `strategy_id` (named parameter, e.g., `/backtest strategy_id=binance.swap.mean-revert.btcusdt.5m.v1`).

If `strategy_id` is not provided, refuse with:

```
Error: strategy_id is required.
Usage: /backtest strategy_id={strategy_id}

Register a strategy first: /strategy-register register
```

Validation steps:
1. Read `config/registry.toml` and confirm the `strategy_id` entry exists.
2. If the entry does not exist, refuse with: "Strategy `{strategy_id}` not found in registry. Run `/strategy-register register` first."
3. Extract `config_path`, `state_path`, `log_path`, `logic_version`, and other relevant fields from the registry entry.
4. All generated artifacts in this workflow MUST be tagged with `strategy_id` and `logic_version`.

### Step 1: Strategy Identification
- Identify target strategy in `src/strategies/`
- Load strategy parameters from the per-strategy config at `{config_path}` (resolved from registry)
- Confirm data requirements
- Verify data availability in `data/`

### Step 2: Backtest Configuration
Using the **quant-analyst** subagent:
- Define IS/OOS split (minimum 70:30)
- Set transaction cost model (spread + commission + slippage)
- Configure initial capital and position sizing

### Step 3: Execute Backtest
Run via backtrader or vectorbt:
```bash
uv run python src/backtesting/runner.py --strategy {name} --data {path}
```

### Step 4: Performance Metrics
Calculate and report:
- **Returns**: Annual return, cumulative return, monthly returns
- **Risk**: Max Drawdown (amount, %, duration), Sharpe, Sortino, Calmar
- **Trades**: Win rate, Profit Factor, avg risk-reward ratio, max consecutive losses
- **Recovery**: Recovery Factor, time to recovery

### Step 5: Visualization

Generate a multi-panel backtest chart. All panels share the same time axis for alignment.

**Panel layout** (top to bottom):

```
┌─────────────────────────────────────────────────┐
│ Panel 1: Price + Entry/Exit Markers              │
│   - Candlestick or line chart of price           │
│   - ▲ markers at long entry, ▼ at short entry    │
│   - × markers at exit (color: green=profit,      │
│     red=loss)                                    │
│   - Shaded regions for position holding periods  │
├─────────────────────────────────────────────────┤
│ Panel 2: Signal Values                           │
│   - Plot each signal/indicator used by strategy  │
│   - Entry/exit threshold lines (dashed)          │
│   - Examples: RSI with 30/70 bands, MACD with    │
│     signal line, z-score with ±2 bands           │
├─────────────────────────────────────────────────┤
│ Panel 3: Cumulative PnL                          │
│   - Cumulative return curve (strategy vs         │
│     buy-and-hold benchmark)                      │
│   - IS/OOS boundary marked (vertical dashed line)│
├─────────────────────────────────────────────────┤
│ Panel 4: Drawdown                                │
│   - Underwater chart (% drawdown from peak)      │
│   - Max drawdown period highlighted              │
├─────────────────────────────────────────────────┤
│ Panel 5: Trade Statistics                        │
│   - Bar chart or histogram of individual trade   │
│     returns (PnL per trade)                      │
│   - Win/loss color coding                        │
│   - Optional: holding period distribution        │
└─────────────────────────────────────────────────┘
```

**Implementation notes:**
- Use matplotlib (static, publication-quality) or Plotly (interactive HTML)
- Save to `reports/strategies/{strategy_id}/chart_{timestamp}.html` (Plotly) or `chart_{timestamp}.png` (matplotlib)
- Panels 1-4 must share x-axis for time alignment
- Panel 5 can be a separate figure
- If data exceeds 50,000 bars, downsample for rendering (full data kept in CSV)

**Summary statistics table** (render below charts or as separate panel):

```
| Metric            | IS        | OOS       | Full      |
|-------------------|-----------|-----------|-----------|
| Total Return      | {value}%  | {value}%  | {value}%  |
| Annual Return     | {value}%  | {value}%  | {value}%  |
| Sharpe Ratio      | {value}   | {value}   | {value}   |
| Sortino Ratio     | {value}   | {value}   | {value}   |
| Max Drawdown      | {value}%  | {value}%  | {value}%  |
| Win Rate          | {value}%  | {value}%  | {value}%  |
| Profit Factor     | {value}   | {value}   | {value}   |
| Total Trades      | {value}   | {value}   | {value}   |
| Avg Trade Return  | {value}%  | {value}%  | {value}%  |
| Max Consec. Loss  | {value}   | {value}   | {value}   |
```

### Step 6: Statistical Validation via Codex
Delegate to Codex for rigorous validation:
```bash
codex exec "Validate backtest results:
- Sharpe: {value}, Annual Return: {value}, Max DD: {value}
- Calculate p-value (H0: Sharpe=0)
- Bootstrap 95% CI for annual return
- Check for look-ahead bias indicators
- Compare IS vs OOS performance gap"
```

### Step 7: Generate Report
Save to `reports/strategies/{strategy_id}/`:
- `chart.html` or `chart.png` — multi-panel visualization from Step 5
- `trades.csv` — trade-by-trade details (entry time, exit time, side, PnL, holding period)
- `metrics.json` — summary metrics (IS, OOS, full period)
- `equity_curve.csv` — timestamped cumulative PnL series (for downstream analysis)

### Step 8: Gemini Chart Interpretation (Optional)
Send the Step 5 visualization to Gemini for pattern recognition:
```bash
gemini -p "Analyze this backtest result chart:
1. Equity curve shape — steady growth, regime-dependent, or curve-fitted?
2. Drawdown patterns — clustered or distributed? Recovery speed?
3. Entry/exit timing — are trades concentrated in specific periods?
4. Signal behavior — do signal values show predictive pattern or noise?
5. IS vs OOS boundary — does performance degrade after the boundary?
Flag any signs of overfitting or data-specific artifacts." -f reports/strategies/{strategy_id}/chart.png
```

### Step 9: Risk Threshold Check
Compare results against thresholds in `risk-management.md`:
- Warn if Sharpe < 1.0
- Warn if Max DD > 20%
- Warn if Win Rate < 40%
- Warn if Profit Factor < 1.5
