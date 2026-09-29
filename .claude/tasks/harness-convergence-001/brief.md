# harness-convergence-001: Switch to Claude implementation + Codex review and make reviews converge

Revision: 2 (2026-09-29)

## Objective

Development under the Claude-PM / Codex-engineer relay became extremely slow (user feedback 2026-09-29). Evidence: `risk-ledger-accounting-001` ran nine full-scope `xhigh` reviews without acceptance; Low findings blocked; briefs accumulated superseded addenda; reviewers could not run tests in the read-only sandbox; one-line doc edits needed a Codex round trip. The user chose a new operating model: Claude implements and validates, Codex is the fresh independent reviewer for T2/T3, and reviews converge.

## Scope

1. Operating model: Claude implements; Codex reviews T2/T3 (optional plan, delegated implementation on request). T1 needs no brief or review. Update CLAUDE.md and AGENTS.md (Zone A only), `.claude/docs/CODEX_TASK_CONTRACT.md`, `.claude/rules/codex-delegation.md`, all skills' delegation text, README, DESIGN.md (ADR-006 superseding the old role ADR).
2. Review convergence: findings carry severity, `blocking`/`follow-up` disposition, and `new`/`carried` origin; `CHANGES_REQUIRED` iff a blocking finding exists (Critical/High, AC violation, failing required validation, weakened financial safeguard); `full` and `delta` scopes, delta requires `review-scope.md`; stop after the third `CHANGES_REQUIRED` and report to the user. Runner prompt, contract, AGENTS.md, rules, and skills agree.
3. Runner validation: before a review, the runner executes allowlisted commands from bash fences under the brief's `## Required Validation` (no shell, no env assignments, allowlist of pytest/ruff/mypy/registry audit/git diff/git status), writes `review-validation.md`, and passes it to the reviewer. Non-allowlisted commands fail the review closed before Codex starts. The review sandbox stays read-only (user decision 2026-09-29).
4. Runner mechanics: `review --scope full|delta`; plan no longer required for review; previous `review.md` archived to `review-<n>.md`; `review_scope` recorded in `state.json` and phase markers; T3 delta reviews default to and floor at `high`, while T3 plan, implement, and full review keep the `xhigh` fail-closed rule.
5. Brief hygiene: briefs are the current consolidated spec with a `Revision:` line; superseded decisions go to `approval.md`/`acceptance.md`.
6. `pm-write-guard.py` (user-approved rewrite 2026-09-29): Edit/Write is blocked only for `.claude/hooks/live-trading-gate.py`, `.claude/hooks/pm-write-guard.py`, `.claude/settings.json`, `.claude/state/live-trading-*.ack`, and `.env`/`.env.*` (not `*.example`); case-insensitive, symlink-resolving; documented as a guardrail, not a security boundary.
7. `error-to-codex` hook: silent for validation/runner commands (pytest, ruff, mypy, registry audit, `codex_handoff.py`); advisory text no longer routes work to Codex. `post-backtest-analysis` advisory text updated likewise.
8. Context load: `paths:` frontmatter on `bot-development.md`, `coding-principles.md`, `deployment.md`, `monitoring.md`, `testing.md`; body content unchanged.
9. Commit cadence documented: PM artifacts are committed at cycle boundaries only.

## Non-Goals

- No change to `.claude/hooks/live-trading-gate.py`, `.claude/settings.json`, `FORBIDDEN_FLAGS`, network fail-closed logic, or T3 user-approval requirements.
- No review-sandbox write access (rejected in favor of runner validation).
- No change to `src/`, `config/`, or historical task artifacts other than this task.
- No downstream repository sync; done separately after acceptance.
- No commits or pushes by the reviewer.

## Acceptance Criteria

- AC1: CLAUDE.md, AGENTS.md (Zone A), the contract, codex-delegation rules, skills, README, and DESIGN.md consistently describe Claude implementation + Codex review with the tier flows in Scope 1; no active document still instructs routing implementation to Codex by default.
- AC2: The review prompt, contract, AGENTS.md, rules, and codex-review skill state the same blocking definition, verdict semantics, origin marking, scopes, and stop rule.
- AC3: `review --scope delta` fails closed (state `blocked`, Codex not invoked) without `review-scope.md` and embeds it when present; `--scope` on a non-review phase or an unknown scope value is rejected. Tests cover these.
- AC4: Runner validation executes only allowlisted commands without a shell, records exit status and output tail in `review-validation.md` and the review prompt, scans every Required Validation section, and blocks the review before Codex for any non-allowlisted command, env assignment, or shell syntax (including live-trading forms). Tests cover these.
- AC5: T3 effort: delta review defaults to `high` and rejects env effort below `high`; plan and full review still default to and require `xhigh`. `review_scope` appears in `state.json` and phase markers. Tests cover these.
- AC6: The previous `review.md` is archived to the next free `review-<n>.md`; tests cover repeated reviews.
- AC7: `pm-write-guard.py` blocks exactly the Scope 6 paths (including case variants and symlinks to them) and allows everything else; tests cover allowed and blocked paths.
- AC8: `error-to-codex` is silent for Scope 7 commands and still reports other failing commands; tests cover both.
- AC9: The five Scope 8 rules files carry valid `paths:` frontmatter with unchanged bodies; other rules files have none.
- AC10: All required validation passes; `live-trading-gate.py` and `settings.json` are unchanged; no emojis are introduced.

## Constraints And Context

- Template origin repository: governance files are synced byte-identical to downstream repos after acceptance, so content must stay template-generic.
- Only Zone A of CLAUDE.md and AGENTS.md may change (above the template boundaries).
- Known failure classes to check: fail-closed inspections (validation parsing), boundary exactness (write-guard exact-path and case matching, allowlist prefix matching), duplicate keys (duplicate Required Validation sections).

## Risk Tier

T2 - Multi-file orchestration change (runner, hooks, contract, rules, skills). It relaxes the write guard (user-approved) and adds runner-executed commands outside the Codex sandbox, so it needs an independent review. Trading safety gates are unchanged.

## Required Validation

```bash
uv run --extra dev pytest -m "not integration and not slow" -q
uv run --extra dev ruff check src/ tests/ .claude/hooks/ .claude/scripts/
uv run --extra dev mypy src/ .claude/scripts/
uv run python -m src.orchestrator.registry audit
git diff --check
git diff --stat -- .claude/hooks/live-trading-gate.py .claude/settings.json
```

## Forbidden Actions

- Editing `.claude/hooks/live-trading-gate.py`, `.claude/settings.json`, `FORBIDDEN_FLAGS`, or network fail-closed logic.
- Enabling network access or sandbox-bypass flags.
- Git commits, pushes, or branch operations by the reviewer.

## Open Decisions Or Blockers

None.
