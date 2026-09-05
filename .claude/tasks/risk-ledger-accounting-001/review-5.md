# Verdict: CHANGES_REQUIRED

## Findings

1. **High — PnL combines observations from different accounting cuts and can relax loss caps.**  
   Each position and ledger timestamp is checked only for individual freshness ([aggregator.py](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:928)), while realized PnL includes every ingested event for the day ([ledger.py](/Users/ohayotaro/claude-finance/src/risk/ledger.py:640)) and is added to unrealized PnL from the potentially older position observation ([aggregator.py](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:1225), [aggregator.py](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:1321)).  
   Example: positions at 12:00 show +100 unrealized; a 12:01 ledger batch contains the +100 closing realization plus -150 elsewhere. The aggregator reports +50 instead of the authoritative -50 because the closed position’s stale unrealized profit is counted again. Both observations can be under 120 seconds old, so the cycle remains healthy. This leaves the core objective and AC2/AC5 incomplete. A common-cut invariant or ledger cutoff tied to the position observation is required.

2. **High — A malformed schema-v3 checkpoint can be restored as healthy with caps cleared.**  
   Current-schema financial values and counts default to zero when absent ([aggregator.py](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:1893)); enforcement flags are accepted through unrestricted `bool(...)` coercion ([aggregator.py](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:1972)); and `"false"` would make `drawdown_baseline_verified` true ([aggregator.py](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:2067)). With matching ledger metadata and fresh timestamps, such a checkpoint can satisfy `_is_healthy`.  
   Schema-v3 fields need exact-type and required-field validation, plus cap/baseline invariants. This is a cache-trust and fail-closed gap in AC4.

3. **High — `run_forever` still has an uncontained startup failure path contrary to F4.**  
   `load_checkpoint` reads `ledger.binding`, which can raise `LedgerError` ([aggregator.py](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:2062)), but its handler does not catch that class ([aggregator.py](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:2082)). `_run_forever_locked` calls it without protection ([aggregator.py](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:2300)), while `run_forever` catches only writer-lock errors ([aggregator.py](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:2251)). A transient ledger read failure can therefore escape without publishing fail-closed state, leaving the prior state file temporarily usable. This is an AC4/AC7 and F4 gap.

4. **Medium — Corrupt ledger metadata is accepted as a valid schema.**  
   `generation` is optional during metadata validation ([ledger.py](/Users/ohayotaro/claude-finance/src/risk/ledger.py:321)), and binding reads silently default a missing generation to zero ([ledger.py](/Users/ohayotaro/claude-finance/src/risk/ledger.py:355)). Missing or inconsistent `cursor`/`as_of` metadata is also not rejected. A damaged existing ledger can consequently masquerade as a pristine generation-zero ledger, undermining checkpoint binding and AC4 recovery guarantees.

5. **Low — Recorded validation evidence is inaccurate.**  
   [implementation-result.md](/Users/ohayotaro/claude-finance/.claude/tasks/risk-ledger-accounting-001/implementation-result.md:51) contains trailing whitespace. `git diff --check` currently fails, despite the artifact recording exit code 0 at line 67.

## Acceptance-criteria gaps

| AC | Review status |
|---|---|
| AC1 | Core known-value, cost, replay, shuffle, and identity tests are present. |
| AC2 | Named zero/omission tests exist, but no test covers position/ledger observation-cut skew and resulting double counting. |
| AC3 | Disabled, deprecated, retired, failed-cycle, exposure, PnL, cap, and flat-removal coverage is present. |
| AC4 | Blocked by permissive checkpoint/ledger metadata restoration and the uncaught restart failure path. |
| AC5 | Required metadata is published, but freshness alone does not establish that composite PnL components describe a consistent cut. |
| AC6 | Example configuration exists and loads; slug, currency, thresholds, and non-finite values are covered. |
| AC7 | Not independently reproducible in this read-only sandbox; current `git diff --check` also contradicts the result artifact. |
| AC8 | ADR-005 documents the model and explicit ADR-004 exception. |

## Validation gaps

- The required offline `uv` test command could not start because the sandbox denied writes to `/private/tmp/risk-ledger-uv-cache`.
- Collection succeeded: 140 risk tests and 309 fast tests.
- Nine write-free targeted tests passed.
- Direct existing-environment checks passed:
  - Ruff: all checks passed.
  - mypy: 14 source files, no issues.
  - Registry audit: `audit: ok (0 strategies, 0 accounts)`.
- `git diff --check` failed on the implementation-result trailing whitespace.
- Missing regressions for:
  - mismatched position/ledger accounting cuts;
  - malformed-but-parseable schema-v3 checkpoints;
  - missing/inconsistent ledger metadata;
  - `LedgerError` during checkpoint loading through `run_forever`.

## Residual risks

- Financial: no real adapter validates venue-specific cursor or normalized realized-PnL semantics; exposure still uses entry price.
- Operational: the writer lock is host-local and cooperative; Windows behavior is tested through mocked backends only.
- Security/integrity: checkpoint and ledger metadata remain insufficiently strict against valid-JSON/valid-SQLite corruption.
- Regression: full pytest execution was not possible in this review environment.
- Deferred as approved: ledger compaction and cross-currency/account conversion.