# risk-ledger-accounting-002: Close the remaining aggregator fail-closed gaps and decompose the aggregator

## Objective

Bring the venue-reconciled risk accounting started in
`risk-ledger-accounting-001` to an acceptable state. Task 001 ran nine
review rounds; each found real but progressively narrower fail-closed
defects, and `src/risk/aggregator.py` grew past 3,000 lines, which made
every full-scope review surface unbounded. This task (1) fixes the four
findings left open by the ninth review and (2) decomposes the aggregator
so that later reviews and changes are bounded.

## Base

The uncommitted working tree on `main` (HEAD `9f922b4` plus the 001
implementation: `src/risk/ledger.py`, `src/risk/aggregator.py`,
`tests/test_risk/test_ledger.py`, `tests/test_risk/test_aggregator.py`,
`config/risk_groups.toml`, `.claude/docs/DESIGN.md` ADR-005) is the base.
Do not revert it. Read `.claude/tasks/risk-ledger-accounting-001/`
(brief with Addenda 1-8, plan, approval, review-1..9, test-evidence) for
the full history; the accepted design decisions there remain binding.
Current PM-verified state: fast suite 332 passed, ruff, mypy, registry
audit, `git diff --check` clean.

## Scope

Part A - open findings from review-9 of task 001:

1. Checkpoint semantic integrity. On restore, recompute daily realized
   and pending PnL from the bound ledger for the persisted day and
   enforcement cut, verify the checkpoint ledger timestamp against ledger
   metadata, and recompute `soft_cap`, `hard_cap`, and `margin_emergency`
   from cached PnL, balance, margin, and current configuration. Any
   mismatch is a corrupt checkpoint (fail closed). Fix the fixtures that
   save PnL inconsistent with the ledger.
2. Fail-closed publication on every definitive startup refusal. Adapter
   load failure, registry load failure, and registry path failure must
   publish fail-closed unhealthy state (replacing any prior healthy file)
   once configuration and the state path are known, using the same
   publication path as the NullVenue refusal.
3. Malformed-log warnings include the byte offset of the offending line
   as required by `.claude/rules/multi-strategy.md` section 6.
4. Implementation-result evidence: every AC row lists only exact test
   function names; artifact is English and plain ASCII; written in one
   whole-file write.

Part B - decomposition:

5. Split `src/risk/aggregator.py` into cohesive modules under `src/risk/`
   with no behavior change beyond Part A. The plan must propose the cut;
   the PM expects roughly: observation validation (venue snapshot,
   positions, orders, freshness, cut), accounting (exposure, PnL, caps,
   drawdown, exact Decimal context), persistence (checkpoint, ledger
   binding, writer lock), publication (state file, provenance, consumer
   validation), and a thin `aggregator.py` orchestration and CLI. Public
   names used by tests and by the CLI keep working via re-exports or
   updated imports. Each module gets its own test file; the existing
   3,300-line test module is split along the same lines.
6. Document the module map in ADR-005 (append, do not rewrite history).

## Non-Goals

- No real venue adapter, no network client, no ccxt.
- No exposure mark-price change, ledger retention or compaction,
  multi-currency, or shared-account cash allocation (all recorded
  follow-ups).
- No changes to `src/orchestrator/registry.py`, `src/bot/`, hooks,
  runner scripts, updater, or `config/registry.toml`.
- No relaxation of any fail-closed behavior established in task 001.

## Acceptance Criteria

- AC1: `test_checkpoint_pnl_inconsistent_with_ledger_is_rejected` and
  `test_checkpoint_cap_flags_inconsistent_with_pnl_are_rejected` prove
  Part A item 1; a consistent checkpoint still restores.
- AC2: `test_adapter_load_failure_publishes_fail_closed_state`,
  `test_registry_failure_publishes_fail_closed_state` prove Part A item 2.
- AC3: `test_malformed_log_warning_includes_offset` proves Part A item 3.
- AC4: `src/risk/aggregator.py` is under 600 lines and contains only
  orchestration and CLI; each new module is under 900 lines; no module
  imports from `aggregator.py` (dependency direction is inward).
- AC5: The full pre-decomposition test inventory (332 fast tests, 163
  risk tests as recorded in 001 `test-evidence.md`) still passes, moved
  or renamed tests are listed with old and new names, and no test
  assertion is weakened.
- AC6: `uv run --extra dev pytest -m "not integration and not slow"`,
  `uv run --extra dev ruff check src/ tests/ .claude/hooks/ .claude/scripts/`,
  `uv run --extra dev mypy src/ .claude/scripts/`, and the registry audit
  pass; `git diff --check` is clean and run last.
- AC7: ADR-005 has an appended module-map section; the implementation
  result satisfies Part A item 4 and maps every AC to exact test names.

## Constraints And Context

- Financial safeguards and the known-failure-class checklist from the
  001 brief remain binding: identity binding, fail-closed inspections,
  TOCTOU, cache trust, boundary exactness, reserved names, duplicate keys,
  exact Decimal arithmetic, UTC.
- Decomposition is a refactor: keep the diff reviewable by moving code
  before changing it where possible, and state in the implementation
  result which hunks are pure moves.
- Plain ASCII, English artifacts. The implement phase must not write
  `review.md`.

## Risk Tier

T3 - Live risk-control logic (loss caps, fail-closed inputs) plus a
structural refactor of that logic. Plan and review are read-only;
implementation requires explicit user approval after PM plan approval.
Effort `xhigh` for all phases.

## Required Validation

- Commands in AC6, run offline.
- Test inventory diff (before/after names) in the implementation result.
- Line counts per module in the implementation result.

## Forbidden Actions

- No network access, no new dependencies, no trading of any kind.
- Do not commit, push, stash, reset, or otherwise mutate Git state.
- Do not write `review.md`.
- Do not modify `.claude/hooks/`, `.claude/scripts/`, `scripts/update.py`,
  `config/registry.toml`, `pyproject.toml`, or `uv.lock`.

## Open Decisions Or Blockers

- Exact module boundaries are a plan decision within the PM sketch above.
- Whether Part A lands before or after the decomposition is a plan
  decision; the PM prefers Part A first on the unsplit module so the
  behavior change is reviewable separately from the moves, with the
  decomposition as a second implementation phase under the same approved
  plan.

## Addendum 1: Corrections for review findings (PM-approved, 2026-09-06)

The fresh review (`review-1.md`, CHANGES_REQUIRED) left three findings.
This is the single corrections pass agreed with the user; fix all three.
The implement phase must not write `review.md`.

- K1 (Medium, finding 1): In `src/risk/persistence.py` checkpoint
  validation, all Decimal comparisons and `abs` operations (net vs gross
  exposure and any similar invariant) must run inside the isolated exact
  arithmetic context (`copy_abs()` or the context). Tests:
  `test_checkpoint_exposure_invariant_is_exact_at_high_precision`
  (equal net/gross `1.2345678901234567890123456789` restores) and
  `test_checkpoint_net_exceeding_gross_is_rejected_without_rounding`.
- K2 (Medium, finding 2): The PM generated
  `.claude/tasks/risk-ledger-accounting-002/test-evidence.md` (moved-test
  mapping from the task-001 inventory to the owning file, and the list of
  tests new in 002). Codex must append to it: (a) a "Pure-move hunks"
  section identifying, per extracted module, which source ranges were
  moved verbatim from `aggregator.py` and which were edited (with the
  reason), and (b) the failing-first results for the K1 tests.
- K3 (Low, finding 3): Rewrite `implementation-result.md` in one
  whole-file write, English, plain ASCII (no em dashes), with an AC table
  whose evidence cells contain only exact comma-separated test function
  names, and reference `test-evidence.md` for the inventory instead of
  linking to itself.

## Addendum 2: Targeted corrections for second review findings (PM-approved, user-approved, 2026-09-06)

The second fresh review (`review-2.md`, CHANGES_REQUIRED) left two
findings. The user approved one targeted pass. Fix both; no other
changes. The implement phase must not write `review.md`.

- L1 (High, finding 1): In `src/risk/persistence.py`, a checkpoint whose
  bound ledger is already reconciled (any row, non-initial generation, or
  non-initial cursor) must have a persisted `current_utc_date`; a null
  day is accepted only for valid bootstrap state (empty ledger at
  generation zero with zero cached PnL and no cap flags). Violations are
  corrupt checkpoints: fail-closed publication and non-zero startup exit.
  Tests: `test_null_day_checkpoint_with_reconciled_ledger_is_rejected`
  (the reviewer's scenario: restore `-600` loss with `hard_cap`, clear
  day/PnL/caps, restart, one venue failure; published state must be
  `healthy=false`, `fail_closed=true`) and
  `test_null_day_checkpoint_is_accepted_only_for_bootstrap`.
- L2 (Low, finding 2): Rewrite `implementation-result.md` in one
  whole-file write, English, plain ASCII, containing: an AC table whose
  evidence cells hold only exact comma-separated test function names
  (AC1-AC7), the `wc -l` output for every `src/risk/*.py` module, the
  exact validation commands with results, and a reference to
  `test-evidence.md` for the inventory.

## Addendum 3: Test-only corrections for third review findings (PM-approved, user-approved, 2026-09-06)

The third fresh review (`review-3.md`, CHANGES_REQUIRED, no High) left
two findings. Fix both. Change surface is limited to
`tests/test_risk/test_persistence.py` and the implementation result; no
runtime source may change. The implement phase must not write `review.md`.

- M1 (Medium, finding 1): Rebuild
  `test_checkpoint_cap_flags_inconsistent_with_pnl_are_rejected` on a
  valid, dated, ledger-consistent checkpoint. The test must first assert
  that the untampered checkpoint restores successfully, then for each
  parameter case tamper exactly one of `soft_cap`, `hard_cap`, or
  `margin_emergency` so that rejection is attributable only to the cap
  mismatch (assert on the specific rejection reason or log message).
  Also apply the same valid-base-then-tamper structure to
  `test_checkpoint_pnl_inconsistent_with_ledger_is_rejected` if it shares
  the undated fixture.
- M2 (Low, finding 2): Rewrite `implementation-result.md` in one
  whole-file write, English, plain ASCII (verify with a non-ASCII grep
  before finishing), containing an AC1-AC7 table whose evidence cells hold
  only exact comma-separated test function names, the `wc -l` output for
  every `src/risk/*.py`, the exact validation commands with results, and a
  reference to `test-evidence.md` for the inventory.
