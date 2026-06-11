# Codex Handoff Playbook

Templates for delegating tasks to Codex CLI.

## 1. Strategy Design Review

```bash
codex exec "
You are reviewing a trading strategy design for a financial trading system.

## Strategy
{paste strategy description}

## Review Checklist
1. Statistical edge validity — does the stated edge have theoretical/empirical support?
2. Overfitting risk — parameter count, IS/OOS gap, data snooping potential
3. Market regime dependency — will this fail in trending/ranging/volatile conditions?
4. Implementation feasibility — can this be implemented efficiently in Python and MQL5?
5. Risk controls — are stop loss, position sizing, and max drawdown properly defined?

Provide your assessment with confidence levels (High/Medium/Low) for each item.
"
```

## 2. Backtest Statistical Validation

```bash
codex exec "
Validate the statistical significance of these backtest results:

## Results
{paste backtest metrics}

## Validation Tasks
1. Calculate p-value for the Sharpe ratio (H0: Sharpe = 0)
2. Bootstrap 95% confidence interval for annual return
3. Run White's Reality Check for data snooping bias
4. Compare IS vs OOS performance gap
5. Assess parameter stability across sub-periods

Flag any signs of overfitting or look-ahead bias.
"
```

## 3. MQL5 EA Code Review

```bash
codex exec "
Review this MQL5 Expert Advisor code:

## Code
{paste EA code}

## Review Focus
1. Order management correctness — CTrade usage, OrderSend validation
2. Memory leak prevention — ArrayFree, indicator handle release
3. Error handling completeness — GetLastError after every operation
4. Slippage and spread handling — deviation parameters, spread checks
5. Magic number management — uniqueness, filtering
6. Risk control implementation — SL/TP, lot sizing, emergency stop

Provide specific line-by-line feedback.
"
```

## 4. Error Root Cause Analysis

```bash
codex exec --full-auto "
Analyze and fix this error in a financial trading system:

## Error
{paste error/traceback}

## Context
- File: {file path}
- Function: {function name}
- Last working state: {description}

Identify root cause, propose fix, and suggest a regression test.
"
```

## 5. Algorithm Optimization

```bash
codex exec "
Optimize this trading algorithm for performance:

## Current Implementation
{paste code}

## Requirements
- Must handle 1M+ rows of OHLCV data
- Must complete backtest in under 60 seconds
- Must maintain numerical precision for financial calculations
- Must be vectorized where possible (numpy/pandas/vectorbt)

Propose optimizations with expected speedup estimates.
"
```

## 6. Risk Model Design

```bash
codex exec "
Design a risk management model for this trading system:

## Portfolio
{describe portfolio composition}

## Requirements
1. VaR calculation (Historical, Parametric, Monte Carlo)
2. CVaR (Expected Shortfall)
3. Position sizing (Kelly criterion variant)
4. Correlation-adjusted risk
5. Stress testing framework

Provide mathematical formulation and Python implementation.
"
```

## 7. Team Review — Final Judgment

Used by `/team-review` after parallel specialist reviews complete.

```bash
codex exec "
You are the senior reviewer for a financial trading codebase. Four specialist reviews have been collected. Render a final verdict.

## Specialist findings (verbatim)
### Security review
{paste security reviewer output}

### Quant correctness review
{paste quant reviewer output}

### Live reproducibility review
{paste reproducibility reviewer output}

### Performance review
{paste performance reviewer output}

## Decision tasks
1. Cross-cut: Are any specialist findings in conflict, or does the same root cause show up in multiple reviews?
2. Severity ranking: Re-rank ALL findings into Critical / High / Medium / Low with justification.
3. Ship/no-ship recommendation, with the minimum set of fixes required to ship.
4. Risks of shipping with each High/Critical finding unresolved.

Output as Markdown with sections matching the four tasks above.
"
```

## 8. Incident Root Cause Analysis

Used by `/incident-response` after emergency stop / postmortem.

```bash
codex exec --full-auto "
Analyze a trading bot incident and produce a postmortem.

## Incident
- Severity: {P0|P1|P2}
- Symptom: {what was observed}
- First detected at: {timestamp UTC}
- Bot: {strategy / symbol / venue}
- Action already taken: {emergency stop / kill switch / manual close}

## Evidence
- Logs (last N lines): {paste}
- Recent trades: {paste}
- Config at time of incident: {paste}

## Required output
1. Timeline reconstruction (event-by-event with UTC timestamps)
2. Most-likely root cause + evidence supporting it
3. Alternative root causes considered and ruled out
4. Immediate remediation steps (before re-enabling the bot)
5. Permanent fix proposal (code, config, or process)
6. Detection gap: how could this have been caught earlier?
7. Regression test that would catch this class of failure

Be explicit about what is verified vs. inferred.
"
```

## 9. IR Analysis Synthesis

Used by `/ir-analysis` after Gemini extracts data from PDFs / earnings calls.

```bash
codex exec "
Synthesize an investor-focused report from extracted IR materials.

## Company
{ticker / name / sector}

## Inputs (already extracted by Gemini)
- Annual report key figures: {paste table}
- Earnings call sentiment / quotes: {paste}
- Disclosures and risk factors: {paste}
- ESG / governance data: {paste}

## Required output
1. Bull case (3 bullets, each with supporting figure)
2. Bear case (3 bullets, each with supporting figure)
3. Key financial metrics table (multi-period: revenue growth, margins, FCF, ROE, leverage)
4. Forward-looking risks not covered by management
5. Peer comparison snapshot (versus 2-3 sector peers)
6. Verdict (overweight / market-weight / underweight) with confidence (High/Medium/Low) and the single observation that would flip the call

Cite the source section for every numeric claim.
"
```

## 10. Equity Screener Criteria Validation

Used by `/equity-screener` to sanity-check screening logic before running.

```bash
codex exec "
Validate this equity screening configuration before it runs against a market universe.

## Screen
{paste screen criteria — fundamental thresholds, technical filters, sector limits}

## Universe
{describe — e.g., TSE Prime, S&P 500, custom watchlist}

## Validation tasks
1. Survivorship / look-ahead: are any of these criteria using point-in-time-incorrect data (e.g., current-year EPS for a 2018 backtest)?
2. Correlation traps: which criteria are functionally redundant (e.g., P/E + EV/EBITDA + P/B all measuring 'value')?
3. Sector skew: would this screen structurally over-weight or under-weight any sector? Quantify if possible.
4. Edge cases: how does the screen handle missing values, recent IPOs, dual-class shares, ADRs?
5. Threshold sensitivity: which 1-2 thresholds, if perturbed by 10%, would most change the result set size?

Recommend specific config changes, with rationale.
"
```

## 11. Sector Rotation Logic Review

Used by `/sector-analysis` when a rotation strategy is being designed.

```bash
codex exec "
Review this sector rotation strategy for statistical and economic soundness.

## Rotation rules
{paste signals, scoring, rebalance frequency, sector universe}

## Backtest summary (if available)
{paste metrics}

## Review checklist
1. Macro regime conditioning: does the strategy implicitly bet on a single regime (rates up/down, growth/value)?
2. Lookback length: is the momentum / mean-reversion lookback consistent with academic evidence and avoids in-sample tuning?
3. Turnover and cost: at the stated rebalance frequency, what is the round-trip cost drag, and does the alpha survive it?
4. Sector definition stability: are sectors GICS-stable across the backtest window, or does reclassification create false signals?
5. Capacity: what AUM does this strategy break at, given typical sector ETF or stock-basket liquidity?
6. Drawdown character: are drawdowns concentrated in specific macro events (e.g., 2008, 2020-Q1)?

Flag any look-ahead or survivorship issues. Output confidence per item.
"
```

## 12. Optimization Result Validation

Used by `/optimize` after walk-forward / hyperparameter tuning completes.

```bash
codex exec "
Validate the output of a parameter optimization run.

## Run summary
- Strategy: {name}
- Search space: {parameters and ranges}
- Trials run: {N}
- Walk-forward windows: {IS/OOS configuration}
- Best parameters: {paste}
- IS / OOS metrics per window: {paste table}

## Validation tasks
1. Overfitting evidence: gap between IS and OOS Sharpe, parameter cluster vs. isolated peak, # effective parameters vs. # trades.
2. Parameter stability: are best parameters similar across walk-forward windows, or do they jump around?
3. Robustness: which best parameters lie on a flat region of the objective surface vs. a sharp peak (sharp = fragile)?
4. Multiple-comparison correction: given N trials, is the best Sharpe statistically distinguishable from chance? (Deflated Sharpe / White's Reality Check.)
5. Recommended next step: deploy / re-run with constraints / reject. State the deciding evidence.

Be quantitative — do not rely on visual intuition.
"
```

## 13. ML Pipeline Validation

Used by `/ml-pipeline` after model training / evaluation completes.

```bash
codex exec "
Validate an ML pipeline for a financial time-series problem.

## Pipeline summary
- Target: {classification / regression / ranking; horizon}
- Features: {list, with leakage-relevant notes}
- Train/val/test split: {dates, with purge / embargo configuration}
- Model: {family + key hyperparameters}
- Metrics: {paste — train, val, test, walk-forward}

## Validation tasks
1. Leakage audit: enumerate every feature; for each, confirm it is point-in-time-correct relative to the prediction timestamp.
2. Purge / embargo correctness: is the gap between train and val sufficient given the target horizon and feature lookback?
3. Train/test distribution drift: are val and test sampled from the same regime as train? Quantify drift if possible (KS test on key features).
4. Performance gap: is the train-vs-test gap consistent with healthy generalization, or with overfit / regime change?
5. Feature importance sanity: do the top features make economic sense, or does the model rely on suspicious proxies (e.g., date features, ID-like columns)?
6. Production readiness: what would need to change for live inference (latency, missing-feature handling, retraining cadence)?

Output: pass / conditional pass (with required fixes) / fail.
"
```

## 14. Risk Report Validation

Used by `/risk-report` to validate risk model calculations and assumptions. Two modes: per-strategy and aggregated (risk-group / account-scope).

### Per-strategy mode

```bash
codex exec "
Validate the risk model for a single strategy.

## Strategy
- strategy_id: {strategy_id} (logic_version {logic_version})
- VaR (95%, 1d): {value}
- CVaR (95%, 1d): {value}
- Max strategy drawdown potential: {value}
- Correlation assumptions: {matrix or summary}

## Validation tasks
1. Are the distributional assumptions reasonable for this strategy's return profile?
2. Are tail risks adequately captured (fat tails, volatility clustering)?
3. Is the stress test scenario set comprehensive for this market and timeframe?
4. Are there hidden concentration risks within this strategy?
"
```

### Aggregated mode (risk-group / account-scope)

```bash
codex exec "
Validate the aggregated risk model across strategies.

## Scope
- Group: {risk_group or account_scope}
- Strategies included: {list of strategy_id with state and enabled flag}
- Aggregate VaR (95%, 1d): {value}
- Aggregate CVaR (95%, 1d): {value}
- Group drawdown vs high-water mark: {value}
- Net exposure: {value}, Gross exposure: {value}
- Margin utilization: {value} (account mode only)

## Validation tasks
1. Are cross-strategy correlations adequately modeled?
2. Is the net exposure after cross-strategy netting reasonable?
3. Are there hidden concentration risks across strategies (same symbol, same sector)?
4. Do the soft/hard cap thresholds from risk-management.md align with the observed risk?
"
```
