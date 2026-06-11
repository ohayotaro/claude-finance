# Codex Delegation Rules

## When to Delegate to Codex CLI

### Design & Architecture
- New class/module design decisions
- Trade logic algorithm design
- Risk model mathematical design
- Data pipeline architecture decisions
- Strategy optimization algorithms

### Code Review
- Strategy code statistical correctness
- MQL5 EA order management logic
- Risk calculation numerical precision
- Performance-critical code paths

### Debugging & Analysis
- Python traceback root cause analysis
- MQL5 compilation error resolution
- Backtest result anomaly analysis
- Data quality issue diagnosis

### Statistical Validation
- Backtest result significance testing
- Overfitting risk quantitative assessment
- Parameter stability analysis
- Walk-forward validation

## Command Templates

**Canonical location**: `.claude/docs/CODEX_HANDOFF_PLAYBOOK.md`. All Codex prompt templates live there with their full structured form. Reference by section number when invoking — do not copy template bodies into skills or rules (avoids drift).

| Use case | Playbook section |
|---|---|
| Strategy design review | §1 Strategy Design Review |
| Backtest statistical validation | §2 Backtest Statistical Validation |
| MQL5 EA code review | §3 MQL5 EA Code Review |
| Error root cause analysis (auto-fix) | §4 Error Root Cause Analysis |
| Algorithm / performance optimization | §5 Algorithm Optimization |
| Risk model design | §6 Risk Model Design |
| Team-review final judgment | §7 Team Review — Final Judgment |
| Incident postmortem | §8 Incident Root Cause Analysis |
| IR analysis synthesis | §9 IR Analysis Synthesis |
| Equity screener validation | §10 Equity Screener Criteria Validation |
| Sector rotation review | §11 Sector Rotation Logic Review |
| Optimization result validation | §12 Optimization Result Validation |
| ML pipeline validation | §13 ML Pipeline Validation |
| Risk report validation | §14 Risk Report Validation |

For one-off consultations that do not match any section, use `/codex-system` skill (it wraps `codex exec` with the standard invocation flags).

## Failure Handling

When a Codex CLI call fails (non-zero exit code, timeout, or empty output):

1. **Notify the user immediately** with:
   - What was being delegated (task description)
   - The error (exit code, stderr, or "empty response")
   - Which skill step was affected
2. **Do NOT silently skip the step** — the delegation was requested because the task requires deep reasoning. Skipping it degrades quality.
3. **Offer alternatives:**
   - Retry the same command
   - Proceed without Codex but flag the result as **unvalidated** (mark clearly in output)
   - User runs Codex interactively in a separate terminal (`! codex "..."`)
4. **Log the failure** — if `/bot-monitor` or structured logging is active, emit a log event.

**Example notification:**
```
Codex delegation failed:
  Task: "Validate backtest results (Sharpe significance)"
  Error: exit code 1 — "rate limit exceeded"
  Skill: /backtest Step 6
  
  Options:
  1. Retry
  2. Continue without Codex validation (result will be marked as unvalidated)
  3. Run manually: ! codex exec "Validate backtest results: ..."
```

## Response Requirements

Codex responses must follow this structure:
1. TL;DR (3 lines max)
2. Analysis (detailed)
3. Plan (implementation steps)
4. Code (if applicable)
5. Validation (verification method)
6. Risks (mandatory)
