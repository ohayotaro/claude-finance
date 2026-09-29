# harness-convergence-001: Implementation result

Implemented by Claude (brief Revision 2).

## Status

PASS

## Summary

The operating model changes from a Claude-PM / Codex-engineer relay to Claude implementation plus a fresh Codex review for T2/T3. Reviews converge through a blocking/follow-up classification, full/delta scopes, and a three-round stop rule. Because the review sandbox stays read-only, the runner executes the brief's allowlisted validation commands before each review and hands the output to the reviewer. The write guard now protects only safety-gate files and credentials. The error hook no longer fires on validation commands. Five engineering-level rules files load by path.

## Files Changed

- `.claude/scripts/codex_handoff.py`: `--scope full|delta`, `review-scope.md` prerequisite for delta, plan optional for review, `review.md` archiving, `review_scope` in state and markers, T3 delta effort floor `high`, runner validation (`required_validation_commands`, `run_validation_commands`, `review-validation.md`), new review contract prompt.
- `.claude/hooks/pm-write-guard.py`: protected-path guard (user-approved rewrite).
- `.claude/hooks/error-to-codex.py`: validation/runner command exemption; new advisory text.
- `.claude/hooks/post-backtest-analysis.py`: advisory text.
- `.claude/docs/CODEX_TASK_CONTRACT.md`: rewritten for the new model (tiers, brief revisions, implementation result, runner validation, findings, verdict, scopes and rounds, effort table, artifacts).
- `.claude/docs/DESIGN.md`: ADR-006 added; former ADR-001 moved to Superseded History as ADR-S4; ADR-002/003 and hook list updated.
- `.claude/rules/codex-delegation.md`: rewritten (workflow, review convergence, runner, tier policy, Git cadence).
- `.claude/rules/{bot-development,coding-principles,deployment,monitoring,testing}.md`: `paths:` frontmatter only.
- `.claude/rules/document-lifecycle.md`: one wording change ("PM intake" -> "intake").
- `.claude/skills/codex-task/SKILL.md`, `.claude/skills/codex-review/SKILL.md`: rewritten.
- `.claude/skills/*/SKILL.md` (other 14): delegation sentence and, for four skills, description wording.
- `CLAUDE.md`, `AGENTS.md`: Zone A only.
- `README.md`: roles, task workflow, runner, tiers, architecture, hooks.
- `tests/test_orchestration/test_codex_handoff.py`, `tests/test_orchestration/test_pm_write_guard.py`, `tests/test_hooks/test_error_to_codex.py` (new).

## Material Design Decisions

- Runner validation instead of a writable review sandbox: the user chose it on 2026-09-29. It keeps the sandbox read-only and makes the evidence runner-executed rather than self-reported.
- Runner validation is an allowlist of token prefixes executed with `shell=False`. Any character in `;&|<>` backtick `$` or a newline rejects the command, so environment assignments such as the live-trading `BOT_MODE` form, chaining, pipes, and substitution cannot run outside the live-trading gate hook. Every `## Required Validation` section is scanned so a duplicate heading cannot hide a command. A non-allowlisted command blocks the review before Codex starts (state `blocked`).
- A failing validation command does not abort the review; its evidence goes to the reviewer, whose contract classifies it as blocking.
- For T2, a delta `APPROVE` is enough for acceptance when corrections stayed in scope; T3 requires a final full review.
- The `error-to-codex` hook was kept (the classifier denied deletion as audit tampering) and narrowed instead.
- The `implement` phase and its T2/T3 plan+approval prerequisite are kept for delegated implementation on user request.

## Validation

| Command | Result |
|---|---|
| `uv run --extra dev pytest -m "not integration and not slow" -q` | 464 passed (after round-2 corrections) |
| `uv run --extra dev ruff check src/ tests/ .claude/hooks/ .claude/scripts/` | All checks passed |
| `uv run --extra dev mypy src/ .claude/scripts/` | Success: no issues found in 19 source files |
| `uv run python -m src.orchestrator.registry audit` | audit: ok |
| `git diff --check` | clean |
| `git diff --stat -- .claude/hooks/live-trading-gate.py .claude/settings.json` | empty (unchanged) |

## Acceptance-Criteria Mapping

- AC1: CLAUDE.md, AGENTS.md, contract, codex-delegation.md, skills, README, DESIGN.md (ADR-006).
- AC2: `REVIEW_CONTRACT` in the runner; contract "Review" section; AGENTS.md "Review rules"; codex-delegation.md "Review Convergence"; codex-review skill.
- AC3: `test_delta_review_requires_scope_file`, `test_invalid_review_scope_is_rejected`, `test_parse_args_accepts_review_scope`.
- AC4: `test_required_validation_commands_parses_allowlisted_fence`, `test_required_validation_rejects_non_allowlisted_commands`, `test_review_runs_brief_validation_and_passes_evidence`, `test_review_with_disallowed_validation_is_blocked_before_codex`.
- AC5: `test_t3_delta_review_defaults_to_high_and_floors_at_high`, `test_t3_plan_and_full_review_still_require_xhigh`, `test_phase_runs_write_state_and_consolidated_events` (review_scope field).
- AC6: `test_review_archives_previous_review`.
- AC7: `test_pm_write_guard_allows_unprotected_paths`, `test_pm_write_guard_blocks_safety_gate_paths`, `test_pm_write_guard_blocks_symlink_to_protected_file`, `test_pm_write_guard_leaves_outside_project_to_permissions`.
- AC8: `tests/test_hooks/test_error_to_codex.py`.
- AC9: frontmatter diff on the five files.
- AC10: validation table above.

## Residual Risks

- Runner validation runs Claude-authored commands outside the Codex sandbox; the allowlist bounds this to test/lint/type/audit/git-read commands, but pytest executes repository test code by design.
- The write guard covers the Edit/Write tools only; Bash writes rely on the documented rule and Claude Code permissions.
- `paths:` frontmatter relies on Claude Code path-scoped rule loading; Codex reads these files directly and ignores the frontmatter.
- Downstream sync (btc-bbo-mm, reactvol-re, light-blue-cid) is pending until acceptance.

## Round 1 Corrections

All six blocking findings and the follow-up from `review-1.md` are addressed; details and touched files are in `review-scope.md`. The `pm-write-guard.py` change was explicitly approved by the user (see `approval.md`). New tests: argument allowlist accept/reject cases, heading-in-fence, indented fence, subheading scoping, fail-closed formatting, lifecycle `--scope` rejection, write-guard symlink cases, and error-hook argument-content cases.

## Round 2 Corrections

The three blocking findings from `review-2.md` are addressed; see `review-scope.md`. The write-guard change was explicitly approved by the user.

Residual note: `pm-write-guard.py` still exits 0 on malformed hook JSON (pre-existing behavior); Claude Code always sends valid JSON.
