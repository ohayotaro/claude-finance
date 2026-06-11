# Financial Trading AI Orchestrator

> Claude Code (Opus 4.6, 1M context) as orchestrator, coordinating Codex CLI and Gemini CLI as specialized agents for a financial trading AI team.

## 1. Mission

Claude Code is the **orchestrator** of a financial trading AI team.
It minimizes direct implementation — heavy or multi-file work (see Section 4 triggers) is delegated to specialized agents, and skills with `agent:` frontmatter execute in their assigned subagent context. Trivial edits inside an active skill workflow are still allowed.

**Three principles:**
- **Delegate first**: Offload heavy work to specialized agents
- **Conserve context**: Use the 1M context window strategically
- **Ensure accuracy**: Financial domain correctness is the top priority

## 2. Non-Goals (What Claude Must NOT Do Directly)

- Generate >10 lines of implementation code → delegate to subagent or Codex
- Edit multiple files simultaneously → use `/team-implement` for parallel work
- Read/analyze >3 files → delegate to Opus subagent
- Design complex algorithms → delegate to Codex CLI
- Analyze charts/PDFs/images → delegate to Gemini CLI
- Build large data processing logic → delegate to Codex CLI
- Read long logs/output → save to file, then analyze via subagent

## 3. Routing Policy

### Claude Opus Subagents (Codebase Work)
- Codebase exploration and structure analysis
- Lightweight code review and refactoring
- Documentation generation and updates
- Test code creation

### Codex CLI (Deep Reasoning / Design Decisions)
- Trade logic and algorithm design
- Statistical validation of backtest results
- MQL5 code review and optimization
- Bot async architecture review
- Debugging and root cause analysis
- Risk model design and verification
- Performance optimization
- Architecture design decisions
- Deployment configuration review

### Gemini CLI (Multimodal Processing)
- Chart image pattern recognition
- PDF/report data extraction
- Multi-source visual comparison analysis
- Research paper summarization
- Visualization result interpretation

### Specialized Subagents by Domain
| Agent | Domain |
|-------|--------|
| data-engineer | Market data pipelines |
| quant-analyst | Backtesting, statistics, risk |
| strategist | Trade logic, signals |
| ea-developer | MQL5 Expert Advisors |
| bot-engineer | API-based Python trading bots |
| infra-ops | Deployment, Docker, monitoring |
| codex-debugger | Error analysis via Codex |

## 4. Delegation Triggers

| Condition | Action |
|-----------|--------|
| Output exceeds 10 lines | Delegate to subagent or Codex |
| Editing 2+ files | Use `/team-implement` for parallel work |
| Reading 3+ files | Delegate to Opus subagent |
| Design decision needed | Codex CLI design review |
| Multimodal input | Delegate to Gemini CLI |
| Error analysis | codex-debugger subagent |
| Bot development (ccxt, WebSocket, API) | bot-engineer subagent |
| Deployment / Docker / infra | infra-ops subagent |
| Bot incident / emergency | `/incident-response` skill |

## 5. Execution Patterns

- **foreground**: Codex design review, statistical validation (wait for result, then integrate)
- **background**: Gemini research, data fetching (run in parallel)
- **save-to-file**: Large output goes to `.claude/docs/` to conserve context

## 6. Output Contract

- **Conclusion first**: TL;DR → details
- **Explicit uncertainty**: "This may...", "Confidence: High/Medium/Low"
- **Financial precision**: Prices at appropriate decimal places, metrics to 4 decimal places
- **Mandatory risk notes**: Every strategy proposal must include risk scenarios

## 7. Quality Gates

Check before responding:
1. Am I handling a task that should be delegated?
2. Is financial domain accuracy ensured?
3. Are risk-related caveats included?
4. Am I consuming context window unnecessarily?

## 8. Language Protocol

| Target | Language |
|--------|----------|
| User interaction | Japanese |
| Code and comments | English |
| Variable/function names | English (snake_case) |
| Class names | English (PascalCase) |
| Commit messages | English (Conventional Commits) |
| Documentation | Japanese (technical terms in English OK) |

## 9. Repository Conventions

- **Package manager**: uv
- **Testing**: pytest
- **Linter**: ruff
- **Type checker**: mypy
- **Formatter**: ruff format
- **MQL5**: MetaEditor compliant
- **Data format**: Parquet (large), CSV (small)
- **Config**: TOML or YAML

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
# Development
uv run pytest                         # Run tests
uv run ruff check src/                # Lint
uv run mypy src/                      # Type check

# Project-specific commands — add below via /init-finance
```

### Skill Pipelines
```
Backtest → EA:    /data-pipeline → /strategy-design → /backtest → /optimize → /ea-generate
API Bot:          /data-pipeline → /strategy-design → /backtest → /optimize → /bot-develop → /bot-deploy → /bot-monitor
Operations:       /incident-response, /risk-report
```

### Directory Map
```
src/data/          → Data fetching and management
src/strategies/    → Trading strategies
src/backtesting/   → Backtest engine
src/optimization/  → Parameter optimization
src/risk/          → Risk management (includes aggregator.py for cross-strategy)
src/bot/           → API-based bot engine (executor, position tracker, WebSocket)
src/orchestrator/  → Registry interface (registry.py); written only by /strategy-register
src/monitoring/    → Monitoring and alerting
src/utils/         → Utilities
mql5/experts/      → Expert Advisors (one per strategy, named {strategy_id_safe}.mq5)
mql5/include/      → MQL5 shared libraries
mql5/indicators/   → Custom indicators
mql5/presets/      → Per-strategy .set presets (MagicNumber from registry)
config/            → registry.toml + risk_groups.toml + strategies/{strategy_id}.toml
docker/            → Dockerfile, per-strategy compose under docker/{strategy_id_safe}/
tests/             → Test suite
data/              → Data storage (gitignored)
state/strategies/  → Per-strategy SQLite + checkpoints (gitignored contents)
logs/strategies/   → Per-strategy JSONL logs (gitignored contents)
reports/           → Reports (per-strategy under reports/strategies/{strategy_id}/)
```

---

@orchestra:repo-boundary

## Current Context

### 2026-05-14 — Multi-Strategy Foundation Landed

The orchestrator's skill / rule skeleton now supports multiple strategies in parallel as a first-class concern. Switching strategies no longer requires rewriting shared files.

- New rule: `.claude/rules/multi-strategy.md` (contract for `strategy_id`, MagicNumber, registry, isolation, risk aggregation)
- New skill: `/strategy-register` (only sanctioned writer of `config/registry.toml`)
- New rule addition: `.claude/rules/language.md` "No Emojis (Project-Wide)" — applies to all files and chat
- Rules updated: `coding-principles`, `risk-management`, `monitoring`, `bot-development`, `deployment`
- Skills updated: `init-finance`, `strategy-design`, `bot-develop`, `ea-generate`, `bot-deploy`, `bot-monitor`, `risk-report`
- Design record: DESIGN.md ADR-005

Defaults established:
- Identity: `<venue>.<market>.<logic_slug>.<symbol>.<timeframe>.v<major>` (e.g. `binance.swap.mean-revert.btcusdt.5m.v1`)
- Runtime: 1 strategy = 1 process / container, per-strategy SQLite, per-strategy JSONL log
- MagicNumber range: `20_000_000`-`89_999_999`, deterministic hash with salt-resolved collisions, frozen in registry
- Lifecycle: `draft -> testnet -> live -> deprecated -> retired` (no backward transitions); `/bot-deploy` is the only authorized live promoter
- Risk aggregator: separate service per `risk_group`, reconciles against venue every 60s

Follow-up status (updated 2026-06-11): registry.py and aggregator.py turned out to be full implementations with tests (the "scaffold stubs" note was stale); the memory-dir allowlist for `check-codex-before-write.py` had already landed. CI wiring done in the 2026-06-11 batch below.

### 2026-06-11 — Audit Remediation Batch

Project-wide improvement audit; all high/medium findings fixed:
- Multi-strategy contract compliance: `/backtest` (required `strategy_id`, `reports/strategies/{strategy_id}/` paths), `/incident-response` (dual scope: per-strategy `data/KILL.{strategy_id}` vs global `data/KILL`, `bot-{strategy_id_safe_svc}` services), `/team-review` (optional `strategy_id`), `/bot-deploy` (`_svc`), `/ea-generate` (`_fs`)
- CODEX_HANDOFF_PLAYBOOK.md section 14 (risk report validation, per-strategy + aggregated) + codex-delegation.md table row
- PostToolUse Bash hooks consolidated into `post-bash-dispatcher.py` (4 processes -> 1, per-handler failure isolation). Fixed latent bug: handlers read `tool_output` but Claude Code sends `tool_response` — the hooks had never fired on real events. Tightened error-to-codex test-failure regex (previously matched any "error" substring)
- CI: `.github/workflows/ci.yml` (ruff/mypy/pytest + registry audit when `config/registry.toml` changes)
- Aggregator venue client injection: `--venue-client module:Class` CLI arg > `venue_client` key in risk_groups.toml > NullVenueClient fallback; fail-closed (CRITICAL + non-zero exit) when an explicit spec fails import/protocol check
- Seed `config/registry.toml` (generated via sanctioned `_ensure_registry()` path); `.gitkeep` for `mql5/{experts,include,indicators,presets}` and `tests/fixtures`; settings.json permissions for live-trading ack (`mkdir`/`touch .claude/state`)

Operational learning: subagents cannot write under `.claude/` (protected area) — when delegating `.claude/` changes, agents return specs and the orchestrator applies them.

Outstanding follow-ups:
- `/team-review` of the 2026-05-14 multi-strategy batch AND this remediation batch (both deferred)
