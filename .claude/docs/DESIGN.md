# Architecture Design Record

## Current Architecture

This repository uses a two-provider architecture:

```text
Claude Opus  -> PM, Japanese user interaction, neutral task brief, risk tier, approvals, acceptance
Codex        -> technical lead, repository exploration, design, implementation, tests, independent review
```

Substantial work is represented by `.claude/tasks/<task-id>/brief.md` and executed through `.claude/scripts/codex_handoff.py`. Planning and review use read-only Codex invocations. Implementation uses workspace-write. The runner centralizes Codex flags, phase prompts, result artifacts, JSONL event logs, and Git metadata.

## Current Decisions

### ADR-001: Claude PM + Codex Engineering

- **Status**: Accepted
- **Decision**: Claude owns PM/change-control duties; Codex owns technical work.
- **Rationale**: The previous orchestration split created duplicate ownership, high PM context consumption, and non-deterministic delegation. A neutral brief plus phase artifacts makes the handoff auditable and keeps technical decisions in the engineering context.
- **Consequences**: Claude writes only approved local orchestration artifacts. Codex receives the brief, relevant rules, and phase prerequisites through the central runner.

### ADR-002: Risk-Tier Gates

- **Status**: Accepted
- **Decision**: Work is classified T0-T3. T2 requires plan, Claude approval, implementation, and fresh review. T3 adds explicit user approval before implementation or external action.
- **Rationale**: Financial trading tasks have materially different risk profiles. Tiered gates prevent low-risk documentation work from carrying heavyweight process while keeping live trading, credentials, deployment, migrations, and risk controls fail-closed.
- **Consequences**: Risk classification is a PM judgment, not a keyword route. Hooks only enforce deterministic constraints.

### ADR-003: Fresh Review Separation

- **Status**: Accepted
- **Decision**: Medium- and high-risk changes receive a fresh read-only Codex review that does not receive the implementation transcript.
- **Rationale**: Independent review catches gaps hidden by implementation context and keeps acceptance evidence auditable.
- **Consequences**: Review may read only the brief, approved plan, implementation result artifact, repository, and diff.

### ADR-004: Multi-Strategy As First-Class Runtime

- **Status**: Accepted
- **Decision**: Strategies are registry-managed, isolated units. `config/registry.toml` owns `strategy_id`, lifecycle state, runtime, paths, risk group, account scope, and MQL5 MagicNumber allocation.
- **Rationale**: One project may host multiple strategies without rewriting shared files. Registry isolation enables per-strategy configs/state/logs/reports and cross-strategy risk aggregation.
- **Consequences**: `src/orchestrator/registry.py` and `src/risk/aggregator.py` are financial runtime code with tests and must not be changed unless a task explicitly requires it.

## Superseded History

### ADR-S1: Three-Provider Orchestration

- **Status**: Superseded
- **Former decision**: Claude coordinated Codex CLI, Gemini CLI, and role-based Opus agents.
- **Reason superseded**: The architecture duplicated ownership, increased always-loaded context, and made responsibility boundaries unclear. Multimodal extraction and role-agent coordination are no longer active architecture.

### ADR-S2: Hook Keyword Routing

- **Status**: Superseded
- **Former decision**: Prompt and tool hooks used keyword routing to suggest provider or role assignment.
- **Reason superseded**: Risk tier and acceptance criteria are PM judgments. Deterministic hooks should enforce safety and integrity only, not infer technical ownership.

### ADR-S3: Inline Codex Prompt Templates

- **Status**: Superseded
- **Former decision**: Skills and documents embedded many one-off Codex command templates.
- **Reason superseded**: Centralizing prompt assembly in `.claude/scripts/codex_handoff.py` prevents drift, allows tests for safe flags, and preserves phase isolation.

## Financial Safety Contracts

- No look-ahead bias.
- Explicit transaction costs, spread, commission, and slippage.
- In-sample and out-of-sample separation.
- Stop loss, daily loss, drawdown, kill switch, and cross-strategy risk controls.
- UTC/timezone correctness.
- Appropriate numerical precision for financial calculations.
- Regression tests for financial logic changes.

## Deterministic Hooks

- `pm-write-guard.py`: blocks Claude source/config writes outside allowed PM artifact paths.
- `live-trading-gate.py`: blocks live-trading Bash commands unless kill switch is clear and a fresh acknowledgment exists.
- `post-bash-dispatcher.py`: runs concise post-command detectors and telemetry.
- `error-to-codex.py`: points failures to the canonical task/debug flow.
- `post-backtest-analysis.py`: detects real backtest failures and metric threshold warnings.
- `post-bot-execution.py`: detects bot execution and connectivity incidents.
- `log-cli-tools.py`: logs minimal Codex metadata without raw prompts or command bodies.
