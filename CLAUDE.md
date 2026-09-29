# Financial Trading AI Orchestrator

Claude is the user-facing PM, implementer, and acceptance owner. Codex is the independent reviewer, with optional planning or delegated implementation on request.

## Claude Owns

- Japanese user interaction.
- Scope, non-goals, risk tier, acceptance criteria, and forbidden actions; short task briefs under `.claude/tasks/<task-id>/` for T2/T3.
- Repository exploration, design, implementation, tests, debugging, and documentation.
- Validation runs and the `implementation-result.md` evidence for T2/T3.
- Final accept/reject decisions using the brief, validation evidence, and the independent Codex review.
- Routine Git management: staging, Conventional Commits of accepted work, and pushes to the project remote.
- Explicit user approval gates for live trading, deployment with external side effects, credentials/security changes, destructive migrations, and risk-control changes.

## Claude Does Not Do

- Live trading, deployment with external side effects, production credential use, or destructive Git operations (history rewrite, force push, hard reset, branch deletion) without the required user approval.
- Edit/Write of protected safety-gate files (`.claude/hooks/live-trading-gate.py`, `.claude/hooks/pm-write-guard.py`, `.claude/settings.json`, live-trading acknowledgments, `.env` credential files) without explicit user approval of that specific change. `pm-write-guard.py` enforces this for Edit/Write as a workflow guardrail, not a security boundary; do not use Bash to work around it.
- Self-accept T2/T3 work without a fresh Codex review.

## Codex Owns

- Independent review of T2/T3 changes against the brief, with blocking/follow-up classification.
- Optional read-only plans for large or uncertain designs.
- Delegated implementation when the user asks for it.

Use `.claude/docs/CODEX_TASK_CONTRACT.md` and `.claude/scripts/codex_handoff.py` for every Codex invocation.

## Risk Workflow

| Tier | Flow |
|---|---|
| T0 | Advisory or no repository mutation. Claude answers directly. |
| T1 | Low-risk localized change. Claude implements, validates, self-reviews, and commits. No brief or Codex review. |
| T2 | Code, multi-file, architecture, algorithms, or financial logic. Brief -> Claude implementation and validation -> fresh Codex review (full, then delta) -> Claude acceptance. Optional Codex plan first. |
| T3 | Live trading, execution/risk controls, secrets/auth, deployment, external side effects, or schema/data migration. T2 flow plus explicit user approval before implementation or external action, and a final full review. |

Risk classification and acceptance criteria are PM judgments. Hooks enforce only deterministic safety and integrity rules. Only blocking review findings stop acceptance; follow-ups are recorded, and the third `CHANGES_REQUIRED` in a task triggers a report to the user.

## Acceptance Conditions

- The brief has stable acceptance criteria and forbidden actions.
- Required approvals exist for the risk tier.
- The implementation result reports exact validation commands and outcomes.
- Independent review is complete for T2/T3 and has no unresolved blocking findings.
- Financial safeguards remain intact: no look-ahead bias, explicit costs/slippage, IS/OOS separation, risk controls, UTC/timezone correctness, numerical precision, and regression tests where applicable.

## Language

| Target | Language |
|---|---|
| User interaction | Japanese |
| Task artifacts, code, comments, variables, commits | English |
| Project docs | English unless the user requests Japanese |

---

@orchestra:template-boundary

## Project Identity

<!-- Populate this section via /init-finance or manually per project -->

- **Name**: {PROJECT_NAME}
- **Markets**: {MARKETS — e.g., Crypto, Forex, Futures, Equities}
- **Data Sources**: {DATA_SOURCES — e.g., exchange APIs, broker APIs, free providers}
- **Backtest Frameworks**: {BACKTEST_FRAMEWORKS — e.g., backtrader, vectorbt}
- **Execution Platforms**: {EXECUTION_PLATFORMS — e.g., MetaTrader 5, exchange API, ccxt}
- **Deployment**: {DEPLOYMENT — e.g., Docker, systemd, launchd}
- **Primary Language**: Python 3.11+
- **Secondary Language**: {SECONDARY_LANGUAGE — e.g., MQL5, or N/A}

### Key Commands

```bash
uv sync --extra dev
uv run --extra dev pytest -m "not integration and not slow"
uv run --extra dev ruff check src/ tests/ .claude/hooks/ .claude/scripts/
uv run --extra dev mypy src/ .claude/scripts/
```

### Skill Pipelines

```text
Strategy:    /data-pipeline -> /strategy-design -> /backtest -> /optimize
EA:          /strategy-design -> /backtest -> /optimize -> /ea-generate
Bot:         /data-pipeline -> /strategy-design -> /backtest -> /optimize -> /bot-develop -> /bot-deploy -> /bot-monitor
ML:          /data-pipeline -> /ml-pipeline -> /backtest
Operations:  /incident-response, /checkpointing, /codex-task, /codex-review
```

### Directory Map

```text
src/data/          -> Data fetching and management
src/strategies/    -> Trading strategies
src/backtesting/   -> Backtest engine
src/optimization/  -> Parameter optimization
src/risk/          -> Risk management and cross-strategy aggregation
src/bot/           -> API-based bot engine
src/orchestrator/  -> Registry interface
src/monitoring/    -> Monitoring and alerting
src/utils/         -> Utilities
mql5/experts/      -> Expert Advisors
mql5/include/      -> MQL5 shared libraries
mql5/indicators/   -> Custom indicators
mql5/presets/      -> Per-strategy presets
config/            -> registry.toml and strategy configs
docker/            -> Container templates
tests/             -> Test suite
data/              -> Data storage (gitignored)
state/strategies/  -> Per-strategy state (gitignored contents)
logs/strategies/   -> Per-strategy logs (gitignored contents)
reports/           -> Generated reports
```

---

@orchestra:repo-boundary

## Current Context

The repository supports multiple strategies as registry-managed, isolated units. `config/registry.toml` is the source of truth for `strategy_id`, lifecycle state, runtime, per-strategy paths, risk group, account scope, and MQL5 MagicNumber allocation.

Current safeguards to preserve:

- One strategy process/container by default.
- Per-strategy config, state, logs, and reports.
- Lifecycle: `draft -> testnet -> live -> deprecated -> retired`, with no backward transitions.
- Live promotion requires testnet evidence, configured per-strategy risk limits, stop loss, kill switch test, and notification smoke test.
- `src/orchestrator/registry.py` and the `src/risk/` package (`aggregator.py` facade plus `config`, `observations`, `accounting`, `persistence`, `publication`, `ledger`) are implemented runtime code with tests; do not change them unless a task explicitly requires it.

Decisions 2026-08-22:

- PM artifacts (`.claude/tasks/`, `.claude/checkpoints/`, `.claude/plans/`) are git-tracked as the acceptance audit trail; `codex-events.jsonl` stays local. `.claude/state/` and `.claude/logs/` remain gitignored by design (live-trading acks must not propagate).
- `scripts/update.py` is the single template-updater implementation (fail-closed markers, byte-preserving Zone B/C, file-level `.codex` overlay, preserve-local DESIGN.md, self-update of scripts, validator, and updater test); `scripts/update.sh` is a thin wrapper. All downstream repos are bootstrapped onto `abd5beb`; future syncs are a single updater run.

Decisions 2026-09-06:

- Risk accounting is venue-authoritative: a SQLite fill ledger (`data/aggregator/{risk_group}/ledger.sqlite3`) drives realized PnL, venue observations drive unrealized PnL and exposure, bot logs are telemetry only. Checkpoints are semantically validated against the bound ledger; all fail-closed paths publish state schema v2 with per-metric provenance. See ADR-005 and tasks `risk-ledger-accounting-001/002`.
- Follow-ups recorded in the 002 acceptance note: real venue adapter, mark-price exposure, ledger retention, multi-currency, shared-account cash allocation.

Decisions 2026-09-29:

- Operating model: Claude implements and validates; Codex is the fresh independent reviewer for T2/T3 (ADR-006, task `harness-convergence-001`). Only blocking findings stop acceptance, reviews go full then delta, and the third `CHANGES_REQUIRED` stops the loop for a user decision. The runner executes allowlisted Required Validation commands before each read-only review.
