# Finance AI Orchestrator

Financial-trading orchestration template with a two-provider operating model:

```text
Claude Opus  -> PM, user interaction, task brief, approval gates, acceptance
Codex        -> technical lead, repository exploration, design, implementation, tests, review
```

The project is markets-agnostic: crypto, FX, futures, equities, and optional MQL5 EA generation. Financial safeguards such as no look-ahead bias, explicit transaction costs, IS/OOS separation, risk controls, live-trading gates, and multi-strategy registry isolation are preserved.

## Quick Start

### New project (includes scaffold)

```bash
cd /path/to/your-trading-project
git clone --depth 1 https://github.com/ohayotaro/claude-finance.git .starter
cp -r .starter/.claude .starter/.codex .starter/AGENTS.md .starter/CLAUDE.md \
      .starter/pyproject.toml .starter/uv.lock .starter/.gitignore \
      .starter/.env.example .starter/.github \
      .starter/src .starter/tests .starter/config .starter/docker \
      .starter/mql5 .starter/reports .starter/scripts .
rm -rf .starter
git init
uv sync --extra dev
claude
```

### Existing project (orchestration layer only)

If `pyproject.toml`, `src/`, `tests/`, etc. already exist, copy only the orchestration files:

```bash
cd /path/to/your-trading-project
git clone --depth 1 https://github.com/ohayotaro/claude-finance.git .starter
cp -r .starter/.claude .starter/.codex .starter/AGENTS.md .starter/CLAUDE.md .
rm -rf .starter
```

Inside Claude Code:

```text
/init-finance
```

The wizard records project identity in `CLAUDE.md` Zone B. Substantial engineering tasks are converted into `.claude/tasks/<task-id>/brief.md` and delegated to Codex through `.claude/scripts/codex_handoff.py`.

## Prerequisites

| Tool | Purpose |
|---|---|
| Claude Code | PM and user-facing controller |
| Codex CLI | technical design, implementation, tests, review |
| Git | repository state and diffs |
| Python 3.11+ | hooks, runner, tests |
| uv | dependency and command runner |

Check local tools:

```bash
claude --version
codex --version
uv --version
```

## Development Commands

```bash
uv sync --extra dev
uv run --extra dev ruff check src/ tests/ .claude/hooks/ .claude/scripts/
uv run --extra dev mypy src/ .claude/scripts/
uv run --extra dev pytest -m "not integration and not slow"
```

Registry audit:

```bash
uv run python -m src.orchestrator.registry audit
```

## Task Workflow

All substantial work starts from a canonical task directory:

```text
.claude/tasks/<task-id>/
├── brief.md                  # Claude PM owns
├── plan.md                   # Codex plan output
├── approval.md               # Claude PM approval for T2/T3
├── implementation-result.md  # Codex implementation output
├── review.md                 # fresh Codex review output
├── state.json                # phase lifecycle, model/effort, git metadata
└── codex-events.jsonl        # local-only consolidated phase event log
```

Task artifacts, `.claude/checkpoints/`, and `.claude/plans/` are tracked in Git for auditability. Only `.claude/tasks/*/codex-events.jsonl` remains ignored because it is a large machine replay log. These artifacts must never contain secrets.

Run phases through the central runner:

```bash
uv run python .claude/scripts/codex_handoff.py plan <task-id>
uv run python .claude/scripts/codex_handoff.py implement <task-id>
uv run python .claude/scripts/codex_handoff.py review <task-id>
uv run python .claude/scripts/codex_handoff.py status <task-id>
uv run python .claude/scripts/codex_handoff.py collect <task-id>
uv run python .claude/scripts/codex_handoff.py cancel <task-id>
```

Risk tiers:

| Tier | Flow |
|---|---|
| T0 | Advisory or no repository mutation. |
| T1 | Low-risk localized change: one Codex implementation run with tests and self-review. |
| T2 | Code, multi-file, architecture, algorithms, or financial logic: plan, approval, implementation, independent review. |
| T3 | Live trading, execution/risk controls, secrets/auth, deployment, external effects, or migration: T2 plus explicit user approval before implementation or external action. |

## What Gets Copied

### Orchestration layer (always copied)

```text
your-trading-project/
├── AGENTS.md                         # Codex project contract
├── CLAUDE.md                         # Claude PM contract and project identity
├── .claude/
│   ├── settings.json                 # deterministic hooks and permissions
│   ├── hooks/                        # safety and telemetry hooks
│   ├── rules/                        # financial, risk, testing, security rules
│   ├── scripts/codex_handoff.py      # central Codex handoff runner
│   ├── skills/                       # PM intake workflows
│   ├── backtest-thresholds.json      # backtest warning thresholds
│   └── docs/                         # task contract and design records
└── .codex/config.toml                # safe project Codex defaults
```

### Project scaffold (new projects only)

```text
your-trading-project/
├── pyproject.toml                    # uv project with dev extras
├── uv.lock                          # pinned dependencies
├── .gitignore                        # data, state, logs, .env excluded
├── .env.example                      # credential template
├── .github/                          # CI workflow
├── src/                              # source packages (data, strategies, bot, risk, ...)
├── tests/                            # pytest suite with fixtures
├── config/                           # registry.toml and strategy configs
├── docker/                           # container templates
├── mql5/                             # EA experts, includes, indicators, presets
├── reports/                          # generated backtest and risk reports
└── scripts/                          # update script and utilities
```

For existing projects that already have their own `pyproject.toml` and source layout, copy only the orchestration layer. The template updater (`scripts/update.sh`) preserves project code and only refreshes orchestration files.

## Skill Pipelines

```text
Strategy:    /data-pipeline -> /strategy-design -> /backtest -> /optimize
EA:          /strategy-design -> /backtest -> /optimize -> /ea-generate
Bot:         /data-pipeline -> /strategy-design -> /backtest -> /optimize -> /bot-develop -> /bot-deploy -> /bot-monitor
ML:          /data-pipeline -> /ml-pipeline -> /backtest
Operations:  /incident-response, /checkpointing, /codex-task, /codex-review
```

Skills are PM intake workflows. They gather domain inputs, add acceptance criteria and checklists to the canonical brief, invoke the central Codex runner, and perform acceptance. They do not own implementation.

## Architecture

Claude is intentionally not the engineering worker. It keeps the conversation with the user, classifies risk, creates neutral briefs, approves Codex plans, and accepts or rejects based on evidence.

Codex performs repository exploration, design, implementation, tests, debugging, and independent review. Planning and review run read-only. Implementation runs workspace-write. The runner tracks phase state in `state.json`, emits consolidated events to `codex-events.jsonl`, and supports lifecycle commands (status, collect, cancel). Plan runs foreground; implement and review run as background processes via Claude Code `run_in_background`.

Model and reasoning effort are phase-aware with four-level precedence: CLI flag, phase-specific env var (`CODEX_PLAN_MODEL`, `CODEX_PLAN_EFFORT`, etc.), general env var (`CODEX_MODEL`, `CODEX_EFFORT`), or built-in defaults. T3 tasks fail-closed at `xhigh` effort minimum.

Hooks are deterministic only:

- `pm-write-guard.py` blocks Claude source/config writes outside PM artifact paths.
- `live-trading-gate.py` keeps live execution fail-closed without a fresh acknowledgment and enforces per-strategy KillSwitch (`data/KILL.{strategy_id}`).
- `post-bash-dispatcher.py` runs concise Bash telemetry and error/backtest/bot incident detectors.

## Updating The Template

From an installed project:

```bash
./scripts/update.sh
```

Or from the remote template:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/ohayotaro/claude-finance/main/scripts/update.sh)
```

Preserved:

- `CLAUDE.md` Zone B
- `AGENTS.md` project-specific section
- `.claude/tasks/`, `.claude/checkpoints/`, `.claude/plans/`, `.claude/logs/`, `.claude/state/`
- `.claude/docs/incidents/`, `.claude/docs/reviews/`, `.claude/settings.local.json`
- Project code and data outside template-managed paths

Migrated away:

- Legacy provider directories
- Legacy role-agent directories
- Keyword routing configuration

## Provenance

Financial-trading specialization. Structural inspiration comes from multi-agent development templates and Claude Code rules-layout patterns, but this repository now uses a Claude PM plus Codex engineering architecture.

## License

MIT
