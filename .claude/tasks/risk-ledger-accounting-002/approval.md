# Approval: risk-ledger-accounting-002

Status: APPROVED for implementation (PM 2026-09-06, user 2026-09-06).

## PM decisions

1. Part A before decomposition, with Part A tests run failing-first on the
   unsplit module, is APPROVED. This keeps the financial behavior change
   attributable separately from the mechanical moves.
2. Checkpoint semantic integrity design is APPROVED: staged decode,
   atomic ledger metadata snapshot (cursor, generation, as_of) read
   before and after the PnL queries, recomputation of realized and
   pending PnL through the enforcement cut inside the exact Decimal
   context, recomputation of cap flags from cached PnL/balance/margin and
   current configuration, and any mismatch treated as corruption with
   fail-closed publication. Rejection of a checkpoint hash/HMAC as
   insufficient is concurring. Fixture corrections (ledger-backed PnL,
   consistent cap assertions) are required, not optional.
3. Routing adapter load, registry load, and registry path failures
   through the existing NullVenue fail-closed publication helper is
   APPROVED; publication failure stays a non-zero exit with no healthy
   fallback.
4. Byte-offset malformed-log warnings using raw byte lengths are
   APPROVED.
5. The five-module decomposition with the stated one-way dependency graph
   and line budgets (`aggregator.py` under 600 as facade plus CLI,
   `persistence.py` under 900) is APPROVED. Explicit compatibility
   re-exports so `src.risk.aggregator:NullVenueClient` style specs keep
   working are APPROVED. Structural tests
   (`test_aggregator_module_boundaries_are_bounded_and_inward`,
   `test_aggregator_public_reexports_remain_available`,
   `test_adr_005_documents_aggregator_module_map`) are APPROVED.
6. Test split preserving function names with an old-path to new-path
   inventory is APPROVED; assertion changes limited to ledger-consistent
   fixtures, stronger cap assertions, and import/monkeypatch targets.
7. Sequence step 2 (read-only snapshot outside the repository) is allowed
   only inside the sandbox temporary directory; nothing may be written
   elsewhere on the machine.
8. Process note: plan.md delivered in English with an exact AC map;
   no drift this time.

## Scope guard

- Approved change surface: `src/risk/aggregator.py`, `src/risk/ledger.py`,
  new `src/risk/{config,observations,accounting,persistence,publication}.py`,
  `tests/test_risk/` (existing two files, new split files, support module),
  `.claude/docs/DESIGN.md` (ADR-005 append), the 002 implementation result.
- `config/risk_groups.toml` unchanged.
- Brief forbidden actions remain binding, including: no `review.md`
  write by the implement phase, no Git mutation, no network, no new
  dependencies.

## Tier selection

- Plan: strong tier, `xhigh` (T3 default). Implementation and review:
  strong tier, `xhigh`. No deviation.

## User approval (T3 gate)

User explicitly approved implementation on 2026-09-06 (interactive
prompt: "approve and start implementation"). Loop policy agreed with the
user: at most one corrections pass after the first review, then report.
No trading, network, or external side effects are authorized.

## Corrections pass approval (2026-09-06)

First review (runner-tracked, finished 01:35:52 UTC) verdict:
CHANGES_REQUIRED, no High or Critical: Medium checkpoint exposure
invariant computed outside the exact Decimal context, Medium missing
inventory/move evidence, Low artifact format. PM verified the inventory
independently (all 70 task-001 tests present except the three
intentionally replaced in 001) and wrote `test-evidence.md`. Brief
Addendum 1 (K1-K3) is APPROVED as the single corrections pass agreed
with the user; strong tier at `xhigh`; a second fresh full-scope review
at `xhigh` follows, after which the PM reports regardless of verdict.

## Pause after second review (2026-09-06)

Second review (runner-tracked, finished 01:58:15 UTC) verdict:
CHANGES_REQUIRED: High null-day checkpoint bypass (a reconciled
checkpoint with `current_utc_date=null` and zero cached PnL skips ledger
recomputation; reproduced by the reviewer as a restored `-600` loss with
`hard_cap` cleared after one venue failure), Low implementation-result
lacks the AC table and module line counts.

Status: NOT ACCEPTED. Per the single-corrections-pass policy agreed with
the user, the PM stops and reports. Code remains uncommitted. PM
independent validation on the real machine after the corrections pass:
fast suite 358 passed, risk 189 passed, ruff, mypy, registry audit, git
diff --check clean; module budgets and inward dependency direction
verified; task-001 test inventory fully preserved.

PM assessment: the decomposition goal (AC4, AC5) is achieved and
verified. The remaining High is a single enumerated fix in
`src/risk/persistence.py` (require a persisted day for any checkpoint
whose ledger is already reconciled; null day only for bootstrap) plus one
regression test. The Low is an artifact rewrite. One targeted pass is the
recommended next step if the user agrees.

## Targeted corrections pass approval (2026-09-06)

User decision: run the recommended targeted pass. Brief Addendum 2
(L1-L2) APPROVED; strong tier at `xhigh`; a third fresh full-scope review
at `xhigh` follows. If that review returns APPROVE, the PM proceeds to
acceptance and commit; otherwise the PM reports and stops.

## Pause after third review (2026-09-06)

Third review (runner-tracked, finished 08:53:03 UTC) verdict:
CHANGES_REQUIRED with no High or Critical: Medium, the cap-flag
inconsistency regression (`test_checkpoint_cap_flags_inconsistent_with_pnl_are_rejected`)
now rejects because its undated fixture trips the new L1 bootstrap guard,
so it no longer proves semantic cap validation; Low, the implementation
result again lacks the AC table, line counts, and contains a non-ASCII
character. No runtime defect was identified. PM independent validation:
fast 372 passed, risk 203 passed, ruff, mypy, registry audit, git diff
--check clean, module budgets and inward dependencies verified.

Status: NOT ACCEPTED pending user decision. The remaining gap is
test-only (fixture must be a valid dated checkpoint restored successfully
before each isolated cap tamper) plus the artifact rewrite.
