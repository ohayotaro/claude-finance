---
name: team-review
description: Parallel code review with 4 specialist reviewers (Security, Quant, Live Reproducibility, Performance) and Codex final judgment.
allowed-tools: "Bash(python *) Bash(codex *) Bash(git *) Read Glob Grep"
---

# Team Code Review

Comprehensive parallel code review by specialized reviewers.

## Workflow

### Step 0: Strategy Context (Optional)

`strategy_id` is **optional** for this skill.

- **When reviewing strategy-specific code** (strategy logic, per-strategy config, bot code for a specific strategy): accept `strategy_id`, look it up in `config/registry.toml`, resolve paths from the registry entry, and tag the review report with `strategy_id` and `logic_version`.
- **When reviewing non-strategy code** (hooks, infra, shared libraries, rules): `strategy_id` is omitted. No registry lookup is needed.

If `strategy_id` is provided but not found in the registry, refuse with: "Strategy `{strategy_id}` not found in registry. Run `/strategy-register register` first."

### Step 1: Identify Review Scope
- List changed files (via `git diff` or explicit list)
- Categorize changes by domain
- If `strategy_id` was provided in Step 0, scope the review to files under the strategy's registered paths

### Step 2: Launch Parallel Reviewers

**Security Reviewer** (general-purpose):
- API key management (no hardcoded secrets)
- Input validation and sanitization
- Authentication and authorization patterns
- Injection vulnerabilities
- Sensitive data in logs or error messages

**Quant Reviewer** (quant-analyst):
- Calculation precision (floating-point issues)
- Statistical correctness (formula validation)
- **Look-ahead bias detection** (see checklist below)
- Edge cases (zero division, empty data, NaN handling)
- Risk management completeness

**Look-ahead bias checklist** (Quant Reviewer must verify each):
1. **Signal causality**: At decision time T, does the signal use only data available at or before T? Any computation that requires data after T is look-ahead.
2. **Indicator causality**: Are all indicators strictly causal? Indicators that use future data (e.g., centered windows, forward smoothing) must be flagged — they are valid only as oracle labels for training, never as live signals.
3. **Train/test separation**: Is there a sufficient gap between training and test periods to prevent information leakage? For ML models, this means purge and embargo buffers.
4. **Label isolation**: Are ground-truth or oracle labels (which intentionally use future data) inaccessible during test and live inference?
5. **Derived mapping isolation**: If model outputs are remapped to trading signals (e.g., cluster ID → regime label), is the mapping built exclusively from training data?
6. **Feature scope**: Does every feature computation at time T use only rows at or before T? Watch for operations that implicitly include future rows (centered windows, bilateral operations, full-dataset normalization).
7. **Multi-resolution alignment**: When combining data from different timeframes or sources, is each data point aligned to its availability time (not its label time)? Incomplete higher-timeframe bars must not be accessible to lower-timeframe logic.

**Live Reproducibility Reviewer** (quant-analyst or bot-engineer, depending on scope):
Applies to strategy code, backtest engine, data pipeline, AND bot code — not just bots.
- Backtest/live parity: will the same signal logic produce the same decisions with live data? (incomplete bars, delayed data, warm-up period)
- Execution assumptions: does the backtest assume instant fills, zero slippage, or unlimited liquidity that won't hold live?
- Non-determinism handling: network latency, partial fills, slippage, rate limit waits — are these accounted for or assumed away?
- Timestamp consistency: are all time comparisons using the same source (exchange time vs local time vs UTC)?
- Data source divergence: does the live system use the same data format and source as the backtest? (historical API vs WebSocket, adjusted vs raw prices)
- State recovery (bot code): if the process crashes mid-trade, does it restore correctly from persisted state?
- Logging contract compliance (bot code): are all mandatory events from `bot-development.md` Structured Logging Contract emitted?

**Performance Reviewer** (general-purpose):
- Execution efficiency (vectorization, unnecessary loops)
- Memory usage (large DataFrame operations)
- I/O optimization (Parquet read/write patterns)
- Scalability (will this work with 1M+ rows?)

### Step 3: Aggregate Findings
Collect and deduplicate issues from all three reviewers:
- Critical: Must fix before merge
- Warning: Should fix, but not blocking
- Info: Suggestions for improvement

### Step 4: Codex Final Judgment
Send aggregated findings to Codex for holistic assessment:
```bash
codex exec "Final code review judgment:
Changes: {file_list}
Security findings: {security_issues}
Quant findings: {quant_issues}
Live reproducibility findings: {repro_issues}
Performance findings: {perf_issues}

Provide: overall assessment, prioritized fix list, risk level (Low/Medium/High)"
```

### Step 5: Output
Generate review report:
- Issue count by severity (Critical/Warning/Info)
- Issue list with file, line, description, suggested fix
- Overall risk assessment
- Approval recommendation (Approve / Request Changes / Block)
