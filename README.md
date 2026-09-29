# Finance AI Orchestrator

Financial-trading orchestration template with a two-provider operating model:

```text
Claude Opus  -> PM, user interaction, implementation, tests, Git, approval gates, acceptance
Codex        -> independent review (optional plan or delegated implementation on request)
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

The wizard records project identity in `CLAUDE.md` Zone B. Claude implements changes directly; T2/T3 work gets a short `.claude/tasks/<task-id>/brief.md` and a fresh Codex review through `.claude/scripts/codex_handoff.py`.

## Prerequisites

| Tool | Purpose |
|---|---|
| Claude Code | PM, implementer, and user-facing controller |
| Codex CLI | independent review, optional planning |
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

T2/T3 work uses a canonical task directory (T0/T1 work needs none):

```text
.claude/tasks/<task-id>/
├── brief.md                  # current consolidated spec (Claude)
├── plan.md                   # optional Codex plan output
├── approval.md               # T3 user approval, superseded decisions
├── implementation-result.md  # validation evidence (Claude)
├── review-scope.md           # delta review scope (Claude)
├── review-validation.md      # runner-executed validation evidence
├── review.md                 # latest fresh Codex review; older rounds kept as review-<n>.md
├── acceptance.md             # acceptance note and follow-ups (Claude)
├── state.json                # phase lifecycle, review scope, model/effort, git metadata
└── codex-events.jsonl        # local-only consolidated phase event log
```

Task artifacts, `.claude/checkpoints/`, and `.claude/plans/` are tracked in Git for auditability. Only `.claude/tasks/*/codex-events.jsonl` remains ignored because it is a large machine replay log. These artifacts must never contain secrets.

Run Codex through the central runner:

```bash
uv run python .claude/scripts/codex_handoff.py review <task-id>
uv run python .claude/scripts/codex_handoff.py review <task-id> --scope delta
uv run python .claude/scripts/codex_handoff.py plan <task-id>
uv run python .claude/scripts/codex_handoff.py implement <task-id>
uv run python .claude/scripts/codex_handoff.py status <task-id>
uv run python .claude/scripts/codex_handoff.py collect <task-id>
uv run python .claude/scripts/codex_handoff.py cancel <task-id>
```

Risk tiers:

| Tier | Flow |
|---|---|
| T0 | Advisory or no repository mutation. |
| T1 | Low-risk localized change: Claude implements, validates, self-reviews, commits. |
| T2 | Code, multi-file, architecture, algorithms, or financial logic: brief, Claude implementation and validation, fresh Codex review (full, then delta), acceptance. Optional Codex plan. |
| T3 | Live trading, execution/risk controls, secrets/auth, deployment, external effects, or migration: T2 plus explicit user approval before implementation or external action, and a final full review. |

Only blocking review findings (Critical/High, AC violation, failing validation, weakened financial safeguard) stop acceptance; the third `CHANGES_REQUIRED` in a task triggers a report to the user.

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

For existing projects that already have their own `pyproject.toml` and source layout, copy only the orchestration layer. The template updater is implemented in `scripts/update.py`; `scripts/update.sh` is a stable delegating entry point. It preserves project code and only refreshes orchestration files.

## Skill Pipelines

```text
Strategy:    /data-pipeline -> /strategy-design -> /backtest -> /optimize
EA:          /strategy-design -> /backtest -> /optimize -> /ea-generate
Bot:         /data-pipeline -> /strategy-design -> /backtest -> /optimize -> /bot-develop -> /bot-deploy -> /bot-monitor
ML:          /data-pipeline -> /ml-pipeline -> /backtest
Operations:  /incident-response, /checkpointing, /codex-task, /codex-review
```

Skills are intake workflows. They gather domain inputs, set the risk tier, and add acceptance criteria and checklists to the brief; Claude then implements and requests the Codex review.

## Architecture

Claude keeps the conversation with the user, classifies risk, implements and validates changes, and accepts or rejects based on evidence. Codex supplies the independent check: a fresh, ephemeral reviewer that never sees the implementation transcript.

Planning and review run read-only; delegated implementation runs workspace-write. The runner tracks phase state in `state.json`, emits consolidated events to `codex-events.jsonl`, runs the brief's allowlisted validation commands before each review so the read-only reviewer sees runner-executed evidence, archives earlier reviews, and supports lifecycle commands (status, collect, cancel). Reviews run as background processes via Claude Code `run_in_background`.

Model and reasoning effort are phase-aware with four-level precedence: CLI flag, phase-specific env var (`CODEX_PLAN_MODEL`, `CODEX_PLAN_EFFORT`, etc.), general env var (`CODEX_MODEL`, `CODEX_EFFORT`), or built-in defaults. T3 phases fail closed below `xhigh`, except delta reviews, which fail closed below `high`.

Hooks are deterministic only:

- `pm-write-guard.py` blocks Claude Edit/Write on safety-gate files (live-trading gate, the guard itself, `settings.json`, live-trading acknowledgments, `.env` credentials) unless the user explicitly approves the change.
- `live-trading-gate.py` keeps live execution fail-closed without a fresh acknowledgment and enforces per-strategy KillSwitch (`data/KILL.{strategy_id}`).
- `post-bash-dispatcher.py` runs concise Bash telemetry and error/backtest/bot incident detectors (validation commands such as pytest/ruff/mypy are exempt from the error advisory).

## Updating The Template

From an installed project:

```bash
./scripts/update.sh
```

The shell entry point resolves Python 3.11 or newer and delegates to the single Python implementation. It tries `UPDATER_PYTHON` first, then standard and versioned Python commands, then `uv python find '>=3.11'` to discover an already-installed interpreter without downloading or synchronizing an environment. You can invoke that implementation directly instead:

```bash
python3 scripts/update.py
# or with the project interpreter
uv run python scripts/update.py
```

Set `UPDATER_PYTHON` to select a specific interpreter when needed:

```bash
UPDATER_PYTHON=/path/to/python3.11 ./scripts/update.sh
```

On Windows, invoke `scripts/update.py` directly; the shell entry point and preservation validator require Bash.

For an offline update or a locally checked-out template, set `TEMPLATE_SOURCE_DIR` for either entry point:

```bash
TEMPLATE_SOURCE_DIR=/path/to/claude-finance ./scripts/update.sh
```

Preserved:

- `CLAUDE.md` Zone B and post-boundary Zone C
- `AGENTS.md` project-specific and post-boundary sections
- An existing local `.claude/docs/DESIGN.md`; the template copy is used only
  when the file is absent
- Downstream-only `.codex` content, including `.codex/plans/`; template
  `.codex` files are replaced individually, and a template without `.codex`
  leaves the downstream tree untouched
- `.claude/tasks/`, `.claude/checkpoints/`, `.claude/plans/`, `.claude/logs/`, `.claude/state/`
- `.claude/docs/incidents/`, `.claude/docs/reviews/`, `.claude/settings.local.json`
- Project code and data outside template-managed paths

Each successful update also refreshes exactly these four updater support files
from the template, without replacing the rest of `scripts/` or `tests/`:

- `scripts/update.py`
- `scripts/validate_update_preservation.sh`
- `tests/test_orchestration/test_update_script.py`
- `scripts/update.sh`

Migrated away:

- Legacy provider directories
- Legacy role-agent directories
- Keyword routing configuration

## Provenance

Financial-trading specialization. Structural inspiration comes from multi-agent development templates and Claude Code rules-layout patterns, but this repository now uses Claude implementation plus fresh Codex review.

## License

MIT
