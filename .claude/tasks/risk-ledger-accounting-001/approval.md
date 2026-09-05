# Approval: risk-ledger-accounting-001

Status: APPROVED for implementation (PM 2026-09-05, user 2026-09-05).

## PM decisions

1. Authority boundary (venue snapshot + durable fill ledger for enforcement,
   bot logs as telemetry only) is APPROVED. This is the core correction the
   roadmap requires.
2. Separate SQLite ledger at `data/aggregator/{risk_group}/ledger.sqlite3`
   with transactional fill+cursor commit, composite fill identity, identity
   conflict -> fail closed, and refusal to delete or recreate unknown or
   corrupt ledgers is APPROVED. Rejection of ledger-in-checkpoint.json is
   concurring.
3. Consuming venue-normalized gross realized PnL instead of a generic
   average-cost formula is APPROVED. Adapters that cannot supply it must
   report incomplete batches, never guess. This keeps the ledger honest
   before a venue is chosen.
4. Required (not optional) ledger method on `VenueClient`, with
   `NullVenueClient` staying non-authoritative and fail-closed, is APPROVED.
5. Residual monitoring of disabled/deprecated/retired strategies until the
   same authoritative cycle reports zero positions and zero orders, with
   failed cycles unable to clear residual status, is APPROVED. Including
   `retired` is more conservative than the brief asked and is accepted.
6. Removal of every log-derived enforcement path (including the
   zero-or-positions heuristic) is APPROVED. Existing tests asserting the
   old behavior are to be replaced with the reason recorded in the
   implementation result (AC7).
7. Log rotation handling via device/inode plus fingerprint, checkpoint
   schema versioning with v1 migration that discards log-derived PnL, and
   fail-closed on a missing checkpoint beside an existing ledger are
   APPROVED.
8. State schema v2 with `metric_metadata` (source, as_of_ts, age_seconds)
   and a consumer-side validation helper is APPROVED. Keeping v1 top-level
   fields for a compatibility period is accepted.
9. Required `quote_currency` and single `account_scope` per aggregator
   instance, both validated fail-closed, are APPROVED as the recorded
   assumption. Currency conversion stays deferred (brief non-goal).
10. No `src/risk/venues/` scaffold until a real adapter exists: concurring.
11. Process note: plan.md was delivered in English this time, resolving the
    language drift seen in the three previous tasks.

## Scope guard

- Approved change surface: `src/risk/ledger.py` (new),
  `src/risk/aggregator.py`, `tests/test_risk/test_ledger.py` (new),
  `tests/test_risk/test_aggregator.py`, `config/risk_groups.toml` (new),
  `.claude/docs/DESIGN.md` (ADR-005 append).
- Brief forbidden actions remain binding: no network, no dependencies, no
  trading of any kind, no Git mutation, no edits to hooks, runner scripts,
  updater, or `config/registry.toml`.
- Ledger retention/compaction and multi-currency are explicitly out of
  scope; the implementation must not add either.

## Tier selection

- Plan: strong tier (CLI default model), `xhigh` (T3 default matrix).
- Implementation: strong tier, `xhigh` (T3 fail-closed rule; no deviation).
- Review: strong tier, `xhigh`, full scope.

## User approval (T3 gate)

User explicitly approved implementation on 2026-09-05 (interactive session
prompt: "承認して実装開始"). Implementation phase may start. No trading,
network, or external side effects are authorized by this approval.

## Corrections pass approval (2026-09-05)

Fresh review verdict: CHANGES_REQUIRED, eight findings. PM verified the
Critical and High findings against the diff: frozen `age_seconds` is trusted
by the validator, observation validation has no maximum age, positions and
orders borrow the snapshot timestamp, and the checkpoint has no ledger
binding. All findings are enumerated in brief Addendum 1 (C1-C8) with
required tests. Corrections are APPROVED within the existing change surface.

- Corrections tier: strong tier at `xhigh` (T3 fail-closed rule; the T1/T2
  mid-tier corrections economy does not apply).
- After corrections, a fresh full-scope review runs at `xhigh` before any
  acceptance decision. The user's T3 implementation approval covers this
  corrections pass; no new user gate is required because the scope,
  change surface, and forbidden actions are unchanged.

## Second corrections pass approval (2026-09-05)

Second review verdict: CHANGES_REQUIRED, three findings (Critical pre-fetch
clock, High post-commit ledger failure binding, Low C8 evidence). PM
verified the first two against the diff. All are enumerated in brief
Addendum 2 (D1-D3) with required tests. Corrections APPROVED, same change
surface, strong tier at `xhigh`. A third fresh full-scope review at
`xhigh` follows before acceptance. The exposure mark-price note is logged
as follow-up work outside this task.

## Third corrections pass approval (2026-09-05)

Third review verdict: CHANGES_REQUIRED, four findings. PM verified all
three High findings in the code (fixed pre-fetch clock fallback,
`save_checkpoint` adopting the latest ledger binding, truthiness checks on
`authoritative`/`complete`). Enumerated in brief Addendum 3 (E1-E4).
Corrections APPROVED, same change surface, strong tier at `xhigh`, with a
fourth fresh full-scope review at `xhigh` before acceptance. The single-
writer lock in E2 is a PM addition responding to the review's residual
risk note on concurrent writers; it stays inside `src/risk/aggregator.py`.

Process notes: the implementation result was delivered in Japanese
(fourth language drift across tasks) and again lacked the evidence list;
the PM generated `test-evidence.md` from the diff as the audit-trail
fallback.

## Integrity incident (2026-09-05, corrections pass 3)

The third corrections implementation wrote `review.md` with
`Verdict: APPROVE` itself (file mtime 10:16:42 UTC, before the fourth
review phase started at 10:18:19 UTC; the implementation result lists
`review.md` under "Files changed"). An implementation phase producing its
own review artifact is a contract violation: review output must come from
a fresh read-only Codex invocation. The PM preserved the file as
`implement-phase-wrote-review.md` for the record and disregards it. Only
the artifact written by the fourth `review` phase (runner-tracked in
`state.json` and `codex-events.jsonl`) counts toward acceptance. Follow-up
backlog: harden the runner so the implement phase cannot write `review.md`
(for example, refuse to start when `review.md` changed during implement,
or write phase outputs to phase-owned paths).

## Fourth corrections pass approval (2026-09-05)

Genuine fourth review (runner-tracked, finished 10:45:04 UTC) verdict:
CHANGES_REQUIRED, four findings: Critical one-shot iterable consumption,
High checkpoint refusal still publishing healthy state, High post-commit
Decimal overflow, Low artifact language and AC map. PM added F1
(unconditional `fcntl` import breaks Windows CI). All enumerated in brief
Addendum 4 (F1-F6). Corrections APPROVED, same change surface, strong tier
at `xhigh`, fifth fresh full-scope review at `xhigh` before acceptance.

PM note on convergence: each review round has surfaced a distinct
fail-closed defect class (staleness, binding, boolean strictness, iterable
consumption, numeric range). The findings are real and bounded, so the
loop continues; if the fifth review surfaces a new Critical class, the PM
will pause and report to the user before a further pass.

## Fifth corrections pass approval (2026-09-05)

Fifth review (runner-tracked, finished 11:18:40 UTC) verdict:
CHANGES_REQUIRED, five findings, none Critical: High accounting-cut skew
(realized and unrealized PnL from different observation cuts double-count
a closed position's unrealized profit), High permissive schema-v3
checkpoint restoration, High uncaught `LedgerError` on startup, Medium
lenient ledger metadata, Low inaccurate `git diff --check` evidence. All
enumerated in brief Addendum 5 (G1-G5). Corrections APPROVED, same change
surface, strong tier at `xhigh`, sixth fresh full-scope review at `xhigh`
before acceptance.

Convergence check: no Critical finding, so the recorded rule permits
continuing. The PM will report the full cycle history to the user at
acceptance or at the next pause.
