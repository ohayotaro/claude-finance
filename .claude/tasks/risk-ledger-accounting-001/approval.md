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
