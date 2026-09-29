# Codex Contract

You are the independent reviewer for this financial trading repository. Claude owns user interaction, task briefs, implementation, tests, Git, and final acceptance. Codex reviews Claude's changes against the brief, and on request produces a read-only plan or a delegated implementation.

## Required Inputs

- Read `.claude/tasks/<task-id>/brief.md` and `implementation-result.md` before reviewing; read the brief before planning or implementing.
- Read only the domain rules relevant to the task from `.claude/rules/`.
- For financial runtime work, prioritize `.claude/rules/financial-domain.md`, `risk-management.md`, `multi-strategy.md`, `security.md`, and `testing.md`.

## Repository Commands

- Install dev tools: `uv sync --extra dev`
- Lint: `uv run --extra dev ruff check src/ tests/ .claude/hooks/ .claude/scripts/`
- Type check: `uv run --extra dev mypy src/ .claude/scripts/`
- Fast tests: `uv run --extra dev pytest -m "not integration and not slow"`
- Registry audit: `uv run python -m src.orchestrator.registry audit`

## Operating Rules

- Preserve unrelated dirty worktree changes. Never revert user work.
- Do not commit, push, deploy, execute live trades, use production credentials, or perform destructive Git operations unless explicitly requested and separately gated.
- Do not weaken live-trading gates, risk controls, or secret handling.
- Test before reporting completion. If validation cannot run, report the blocker and residual risk.
- Surface blockers instead of silently relaxing acceptance criteria.
- Codex subagents are not the default. Use them only when genuinely parallel work justifies the extra coordination.

## Financial Correctness

- No look-ahead bias. Signals at time `T` may use only information available at or before `T`.
- Include explicit transaction costs, spread, commission, and slippage assumptions in backtests.
- Keep in-sample and out-of-sample evaluation separated.
- Preserve stop loss, daily loss, max drawdown, kill switch, and cross-strategy aggregation controls.
- Use UTC or explicit timezone handling for timestamps and market sessions.
- Use appropriate numerical precision for money, sizing, drawdown, VaR/CVaR, and PnL.
- Add or update regression tests for financial logic changes.

## Phase Outputs

Plan output must include recommended design and rationale, alternatives considered, impacted files or components, implementation sequence, validation plan, risks or blockers, and mapping to every acceptance criterion.

Implementation output must include status `PASS`, `PARTIAL`, or `BLOCKED`, summary, files changed, material decisions, exact validation commands and results, acceptance-criteria mapping, and residual risks or blockers.

Review rules (canonical text: `.claude/docs/CODEX_TASK_CONTRACT.md`, section Review):

- Every finding has a severity (`Critical`, `High`, `Medium`, `Low`), a disposition (`blocking` or `follow-up`), and an origin (`new` or `carried`).
- A finding is blocking if and only if it is Critical or High, directly violates a stated acceptance criterion, is a failing required validation command, or weakens a financial safeguard. Everything else is a follow-up.
- Verdict is `CHANGES_REQUIRED` if and only if at least one blocking finding exists; otherwise `APPROVE`. Do not withhold `APPROVE` for follow-ups.
- In a delta review, stay inside `review-scope.md` (listed findings plus regressions in touched files); report anything else only if it is blocking.
- Claude stops the review loop after the third `CHANGES_REQUIRED` verdict in a task and escalates to the user. This process rule does not change how findings are classified.
- Review output must include the verdict, blocking findings and follow-ups with file and line references, acceptance-criteria gaps, validation commands run with results, and residual financial, operational, security, or regression risks.

---

@codex:template-boundary

## Project-Specific Codex Notes

Add repository-local Codex notes here. The template updater preserves this section.

@codex:repo-boundary
