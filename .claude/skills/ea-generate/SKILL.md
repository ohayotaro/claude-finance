---
name: ea-generate
description: Convert Python trading strategies to MQL5 Expert Advisors with Codex code review, order management, and risk controls.
agent: ea-developer
context: fork
allowed-tools: "Bash(python *) Bash(codex *) Read Write Edit Glob Grep"
---

# MQL5 EA Generator

Convert Python strategies to MetaTrader 5 Expert Advisors.

## Workflow

### Step 0: Validate Strategy is Registered

**Required argument**: `strategy_id` (first positional argument, e.g., `/ea-generate binance.swap.mean-revert.btcusdt.5m.v1`).

If `strategy_id` is not provided, refuse with:
```
Error: strategy_id is required.
Usage: /ea-generate {strategy_id}

Register a strategy first: /strategy-register register
```

Validation steps:
1. Call `/strategy-register show {strategy_id}` to confirm the entry exists.
2. Verify `runtime == "mql5"`. If `runtime == "python"`, refuse with: "This strategy uses Python runtime. Use `/bot-develop {strategy_id}` instead."
3. If the entry does not exist, refuse with: "Strategy `{strategy_id}` not found in registry. Run `/strategy-register register` first."
4. Verify `magic_number` is present and > 0 in the registry entry. If missing or zero, refuse with: "MagicNumber not allocated for `{strategy_id}`. Re-register with `runtime = mql5` via `/strategy-register register`."
5. Extract `magic_number`, `config_path`, and all relevant fields from the registry entry.
6. Derive `strategy_id_safe_fs` by replacing all dots in `strategy_id` with underscores (MQL5 filename constraint).

### Step 1: Source Strategy Analysis
- Read target Python strategy from `src/strategies/`
- Extract signal logic, entry/exit rules, parameters
- Identify indicators and their MQL5 equivalents

### Step 2: EA Architecture Design
Using the **ea-developer** subagent, design:
- OnInit: Indicator handle creation, input parameter validation, MagicNumber loaded from the `.set` preset file (never hardcoded in source)
- OnTick: Signal generation, order management loop
- OnDeinit: Handle release, cleanup
- Input parameters mapping from Python strategy
- MagicNumber: use the value from the registry (frozen at registration). The EA template reads it as an `input` parameter, and the `.set` preset file provides the concrete value.

**Account-type caveat (netting vs hedging)**: On a hedging account, per-strategy MagicNumber gives clean position attribution. On a netting account, positions are aggregated at the symbol level regardless of MagicNumber. MagicNumber still works for order tagging and history filtering, but position state must reconcile against the aggregated position. If multiple strategies trade the same symbol on a netting account, they MUST coordinate. See `multi-strategy.md` section 3 for details. Flag this to the user if the registry shows multiple strategies on the same venue+symbol.

### Step 3: Implement Core Logic

**Assess scope**: If the EA requires multiple include files (shared library, custom indicators, utility modules), transition to `/team-implement` with the design from Step 2 as input, assigning `ea-developer` to each MQL5 file.

For single-file EAs, generate the EA at `mql5/experts/{strategy_id_safe_fs}.mq5` (where `strategy_id_safe_fs` is the `strategy_id` with dots replaced by underscores):
- Signal generation matching Python logic exactly
- CTrade order management (market orders, pending orders)
- Position tracking with magic number filtering
- MagicNumber declared as `input int InpMagicNumber` -- the concrete value is supplied via the `.set` preset, not hardcoded in source
- Do NOT assign a magic number internally in the code. The registry is the sole allocator.

### Step 4: Implement Risk Controls (Mandatory)
- Stop loss calculation and setting
- Take profit calculation and setting
- Lot size calculation (fixed or % of balance)
- Max spread check before entry
- Max concurrent positions check
- Daily loss limit check
- Emergency stop mechanism

### Step 5: Generate Preset File

Generate the `.set` preset file at `mql5/presets/{strategy_id_safe_fs}.set` containing:
- `InpMagicNumber={magic_number}` (the value frozen in the registry)
- All `input` parameters from the EA, with defaults matching the per-strategy config (`config/strategies/{strategy_id}.toml`)

The operator loads this preset in MetaTrader before running the EA. This ensures MagicNumber is always registry-sourced, never manually typed.

### Step 6: Parity Verification
Verify that the generated MQL5 logic matches the source Python strategy:
- Compare signal generation conditions side by side
- Verify parameter mapping (Python defaults from per-strategy config TOML match MQL5 input parameters in the `.set` preset)
- Check risk controls are equivalent (SL/TP, lot sizing, emergency stop)

For full code quality review (security, performance, correctness), run `/team-review`.

### Step 7: Test Configuration
Generate MetaTrader Strategy Tester config:
- Symbol, period, date range
- Spread model (every tick vs 1-minute OHLC)
- Initial deposit and leverage
- Optimization parameters (if applicable)
- Reference the generated `.set` preset for parameter initialization

### Step 8: Update Registry

After generating EA and preset files, update the registry entry with EA-specific fields via `/strategy-register`. Do NOT edit `config/registry.toml` directly from this skill.

### Step 9: Output
- EA file: `mql5/experts/{strategy_id_safe_fs}.mq5`
- Preset file: `mql5/presets/{strategy_id_safe_fs}.set` (contains MagicNumber from registry)
- Include file (if needed): `mql5/include/{strategy_id_safe_fs}_common.mqh`
- Test config documentation
- Deployment checklist (broker requirements, VPS setup, hedging vs netting account note)
