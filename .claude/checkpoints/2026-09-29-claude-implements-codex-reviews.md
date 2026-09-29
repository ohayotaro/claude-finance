# Checkpoint: operating model switched to Claude implementation + Codex review

Date: 2026-09-29

## Task state

| Task | Tier | Status | Artifacts |
|---|---|---|---|
| harness-convergence-001 | T2 | ACCEPTED 2026-09-29, committed `cec8ed6`, pushed to origin/main | `.claude/tasks/harness-convergence-001/` brief.md (Revision 2), approval.md (user decisions, superseded Revision 1), implementation-result.md, review-1.md, review-2.md, review.md (round 3), review-scope.md, review-validation.md, acceptance.md, state.json |

Validation at acceptance: fast suite 466 passed, ruff, mypy (19 files), registry audit, `git diff --check` clean; `live-trading-gate.py` and `settings.json` unchanged. Hooks verified on the system Python 3.9 that runs them. Runner-executed validation passed in all three review rounds.

Review history: full (6 blocking) -> delta (3 blocking) -> delta (1 Low blocking, advisory noise only). The third `CHANGES_REQUIRED` triggered the new stop rule; the user chose "fix and accept without another review".

## What changed (see ADR-006, CODEX_TASK_CONTRACT.md)

- Claude implements and validates; Codex is the fresh independent reviewer for T2/T3 (optional plan or delegated implementation on request). T1: no brief, no review.
- Only blocking findings stop acceptance; `full` then `delta` reviews; stop after the third `CHANGES_REQUIRED`.
- Runner executes allowlisted Required Validation commands (bash fences, no shell, per-command argument allowlist, fail-closed parsing) before the read-only review.
- `pm-write-guard.py` protects only safety-gate files and credentials (live-trading gate, the guard, `settings.json`, live acks, `.env`), including symlink and case-variant paths. Changing them needs explicit user approval per change; the auto-mode classifier also blocks hook self-modification and sandbox weakening without it.
- Codex tier mapping: strong `gpt-6-astra`, mid `gpt-6-sol`, light `gpt-6-luna` (verified against `~/.codex/models_cache.json`).

## Blockers

None.

## Next actions

1. Downstream sync of the template change to `~/btc-bbo-mm`, `~/reactvol-re`, `~/light-blue-cid`: awaiting user go-ahead; confirm before any downstream push.
2. Default effort matrix: user noted `gpt-6-astra` performs well at low effort. Claude proposed T2 `high` -> `medium`, T3 unchanged at `xhigh`. Awaiting user decision.
3. Roadmap Step 3 (research schemas, `research-schemas-001`, T2) from the 2026-09-06 checkpoint remains the next product task, now under the new operating model.

## Follow-ups recorded (not scheduled)

- `VALID_EFFORTS` still lists `minimal`, which current Codex models do not support; `max`/`ultra` intentionally not adopted.
- `pm-write-guard.py` exits 0 on malformed hook JSON (pre-existing).
- From the 2026-09-06 checkpoint, still open: real venue adapter, mark-price exposure, ledger retention, multi-currency, `persistence.py` at 897/900 lines. The runner-hardening item there (phase-owned outputs, Codex evidence tables) is largely obsolete: Claude now writes `implementation-result.md` and the runner produces validation evidence.

## Drift detection

- CLAUDE.md Zone C: 23 lines before this checkpoint; a 2026-09-29 decision entry added; under the 50-line limit.
- DESIGN.md: ADR-006 added, former ADR-001 moved to Superseded History (ADR-S4); no new `src/` module.
- CODEX_TASK_CONTRACT.md, codex-delegation.md, AGENTS.md, and all skills describe the same flow (checked in review rounds 1-3).
- No api_specs exist yet.
