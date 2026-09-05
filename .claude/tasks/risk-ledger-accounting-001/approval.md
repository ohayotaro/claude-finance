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

## Sixth corrections pass approval (2026-09-05)

Sixth review (runner-tracked, finished 11:51:53 UTC) verdict:
CHANGES_REQUIRED, three findings, none Critical: High one-sided accounting
cut, High Decimal context rounding, Low AC-table naming. Enumerated in
brief Addendum 6 (H1-H3). Corrections APPROVED, same change surface,
strong tier at `xhigh`, seventh fresh full-scope review at `xhigh` before
acceptance. Finding count and severity are decreasing (8 -> 3 -> 4 -> 4 ->
5 -> 3, no Critical since round 4), which the PM reads as convergence.

## Seventh corrections pass approval and stop rule (2026-09-05)

Seventh review (runner-tracked, finished 12:16:13 UTC) verdict:
CHANGES_REQUIRED, six findings, none Critical: High derived-value domain
closure, High ambient rounding in cap decisions, Medium allowed-skew
health mismatch, Medium CLI NullVenue publication gap, Low AC-table
naming, Low config comment. Enumerated in brief Addendum 7 (I1-I6).
Corrections APPROVED, same change surface, strong tier at `xhigh`, eighth
fresh full-scope review at `xhigh` before acceptance.

Stop rule: if the eighth review returns CHANGES_REQUIRED, the PM pauses
the loop and reports the full cycle history and options to the user
before any further pass, regardless of severity.

## Pause after eighth review (2026-09-05)

Eighth review (runner-tracked, finished 12:43:39 UTC) verdict:
CHANGES_REQUIRED with one High and one Low finding. Per the recorded stop
rule the PM paused the loop and is reporting to the user.

Remaining High: when the position snapshot is newer than the ledger
completeness watermark (within the allowed skew), a loss realized in the
gap is absent from both ledger PnL (cut at the watermark) and unrealized
PnL (the later snapshot is flat). Root cause is the Addendum 6 H1 wording
that allowed a within-skew newer position cut; the reviewer's proposed
fix is to fail closed whenever the position cut is newer than the ledger
watermark unless the adapter supplies positions as of the enforcement
cut. Remaining Low: implementation-result AC table still not test-names
only.

Status: NOT ACCEPTED. Code remains uncommitted in the working tree. PM
independent validation on the real machine after corrections pass 7:
fast suite 330 passed, ruff, mypy, registry audit, git diff --check all
clean.

## Eighth corrections pass approval (2026-09-05)

User decision (interactive prompt): run one more corrections pass. Brief
Addendum 8 (J1-J2) supersedes the H1 within-skew allowance with a strict
ledger-watermark enforcement cut. Corrections APPROVED, same change
surface, strong tier at `xhigh`, ninth fresh full-scope review at `xhigh`.
After the ninth review the PM reports to the user regardless of verdict.

## Pause after ninth review (2026-09-05)

Ninth review (runner-tracked, finished 14:03:09 UTC) verdict:
CHANGES_REQUIRED: High checkpoint semantic trust (cached PnL and cap
flags are not recomputed against the bound ledger on restore), High
startup refusals other than NullVenue leave a prior healthy state file in
place, Low J2 evidence format, Low malformed-log warning lacks the byte
offset required by multi-strategy.md section 6.

Status: NOT ACCEPTED. Per the user-approved single extra pass, the PM
stops here and reports. Code remains uncommitted in the working tree; PM
independent validation after corrections pass 8: fast suite 332 passed,
ruff, mypy, registry audit, git diff --check all clean.

PM assessment: nine review rounds each found real but progressively
narrower fail-closed gaps in a module that has grown past 3,000 lines.
Recommended next step is a bounded T3 follow-up task
(`risk-ledger-accounting-002`) that (1) enumerates the four open
findings, (2) adds a checkpoint semantic-integrity check by recomputing
ledger totals and cap flags on restore, (3) publishes fail-closed state on
every definitive startup refusal, and (4) asks the plan phase for a
decomposition of `src/risk/aggregator.py` into observation validation,
accounting, persistence, and publication modules so review surfaces
become bounded. The current working tree is the base for that task.
