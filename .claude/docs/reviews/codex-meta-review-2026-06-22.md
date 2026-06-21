# Meta-Review 2026-06-22

## Overview

Second meta-review of the ai-orchestra framework, assessing the refactoring from three-provider orchestration (Claude + Codex CLI + Gemini CLI) to Claude PM + Codex engineering (commit 97f391d).

Reviewer: Codex (read-only plan phase)
Scope: CLAUDE.md, AGENTS.md, DESIGN.md, CODEX_TASK_CONTRACT.md, codex_handoff.py, 10 rule files, 7 hooks, 22 skills, settings.json, registry.py, aggregator.py, tests, config/registry.toml, CI

## Verdict: CHANGES_REQUIRED

The old three-provider/router architecture is fully removed. The refactoring successfully resolved most Critical/High issues from the 2026-05-09 review. However, the new multi-strategy runtime and PM/Codex control surface introduced or left several operational gaps.

## Critical Findings

### C1: Aggregator can report healthy without authoritative venue reconciliation

- Contract: exchange/broker reconciliation at least every 60s (multi-strategy.md:243, risk-management.md:115)
- Actual: `main()` falls back to `NullVenueClient` when unconfigured (aggregator.py:965). NullVenueClient returns empty successful snapshots (aggregator.py:122), making `healthy=true` through `last_success_ts` (aggregator.py:632)
- Fix: refuse startup without an explicit real `venue_client` for live-capable risk groups, or make null mode explicit/test-only and always publish `healthy=false`/`fail_closed=true`

### C2: Per-strategy KillSwitch documented but not enforced by hook

- Contract: `data/KILL` and `data/KILL.{strategy_id}` handling including hook awareness (multi-strategy.md:329)
- Actual: `live-trading-gate.py` checks only `data/KILL` (live-trading-gate.py:125)
- Fix: parse `STRATEGY_ID` / `--strategy-id` from command, block on matching per-strategy kill file

### C3: MQL5 netting-account safeguards can be bypassed

- Contract: `[[accounts]]` metadata required for MQL5 account scopes; refuse duplicate netting `(venue, account_scope, symbol)` registrations (multi-strategy.md:86, 112)
- Actual: registration does not require a matching account entry; compares raw symbols exactly (registry.py:546, 553). Tests register MQL5 strategies with `accounts=[]` (test_registry.py:403)
- Fix: require account metadata for every MQL5 registration/audit; compare canonical symbols in netting checks

### C4: codex_handoff.py uses deprecated Codex CLI flag (PM addition)

- Contract: runner must work with current Codex CLI
- Actual: `build_codex_command()` passes `--ask-for-approval never`, which was removed from Codex CLI. Runner fails with exit status 2 on all phases
- Fix: remove `--ask-for-approval` flag from `build_codex_command()`; approval is no longer configurable via CLI (exec mode is inherently non-interactive)

## High Findings

### H1: `testnet -> live` registry transition has no precondition enforcement

- Contract: 6 preconditions required before live promotion (multi-strategy.md:165)
- Actual: `cmd_transition()` only checks state transition matrix (registry.py:677)
- Fix: make `transition live` refuse without precondition evidence, or route live promotion exclusively through `/bot-deploy`

### H2: Document lifecycle vs write guard contradiction

- Contract: lifecycle rules require Claude to edit CLAUDE.md Zone B/C and DESIGN.md (document-lifecycle.md:12, 17)
- Actual: `pm-write-guard.py` allows only `.claude/tasks`, checkpoints, plans, state, reviews (pm-write-guard.py:11)
- Fix: allow section-scoped PM doc writes for `CLAUDE.md`/`AGENTS.md`/`DESIGN.md`, or delegate those edits through Codex tasks

### H3: Settings do not cover tools skills declare

- Contract: skills declare `Write`/`Edit` in frontmatter (e.g., codex-task/SKILL.md:4)
- Actual: settings.json allows only `Read`, `Glob`, `Grep` among file tools (settings.json:18)
- Fix: add `Write` and `Edit` to project permissions (pm-write-guard.py provides path-level enforcement), or remove from skill frontmatter

## Medium Findings

### M1: Aggregator omits margin usage/leverage publication

- Contract: margin usage/leverage per account (risk-management.md:96)
- Actual: `state_to_dict()` publishes flags and PnL/exposure but not margin fields (aggregator.py:639)

### M2: Aggregator poll interval configurable above 60s maximum

- Contract: venue query at least every 60s (multi-strategy.md:244)
- Actual: loader accepts arbitrary `poll_interval_s` (aggregator.py:290)

### M3: `config/risk_groups.toml` not seeded

- Contract: `/init-finance` creates it (multi-strategy.md:283); runtime fails without it (aggregator.py:277)
- Actual: `config/` only has `registry.toml`

### M4: Document lifecycle report paths stale

- Contract: `reports/strategies/{strategy_id}/` (multi-strategy.md:195, backtest/SKILL.md:24)
- Actual: lifecycle lists flat `reports/backtest_*.html` (document-lifecycle.md:52)

### M5: CI does not match deployment rule claims

- Contract: testnet integration on PR, Docker build on merge, staged deployment (deployment.md:117)
- Actual: CI runs lint, mypy, fast tests, conditional registry audit only

## Low Findings

### L1: Stale reference to removed CODEX_HANDOFF_PLAYBOOK.md in document-lifecycle.md:76
### L2: Generic `strategy_id_safe` in deployment.md:73 (should be `strategy_id_safe_svc`)
### L3: Language policy inconsistency between CLAUDE.md ("English unless requested Japanese") and language.md ("Japanese for user-facing docs")

## Previous Review (2026-05-09) Resolution Status

| Finding | Status | Evidence |
|---------|--------|----------|
| DESIGN agent contradictions | RESOLVED | ADRs rewritten; old agents removed |
| /team-implement coverage gap | RESOLVED | Skill removed entirely |
| Checkpointing vs .gitignore | RESOLVED | Checkpointing no longer commits |
| Skill/tool mismatches | RESOLVED | Old commands fixed; new Write/Edit gap remains (H3) |
| Agent-router ambiguity | RESOLVED | Router removed; risk-tier PM judgment |
| Codex prompt duplication | RESOLVED | Centralized in CODEX_TASK_CONTRACT.md + codex_handoff.py |
| Document lifecycle overclaim | RESOLVED | Now says manual discipline |
| Handoff playbook coverage gap | PARTIALLY_RESOLVED | Playbook gone; one stale reference (L1) |
| Direct implementation ambiguity | RESOLVED | Skills converted to PM intake |
| Live-trading safety gates | PARTIALLY_RESOLVED | Global gate exists; per-strategy kill gap (C2), live transition gap (H1) |
