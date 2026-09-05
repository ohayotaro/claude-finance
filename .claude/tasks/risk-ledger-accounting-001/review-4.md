# Verdict: CHANGES_REQUIRED

## Findings

1. Critical - One-shot venue collections can be consumed during validation and then silently disappear from accounting. [AC1, AC2, AC3, AC7]

   Position and order observations are iterated during validation at [aggregator.py:917](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:917), then iterated again for accounting at [aggregator.py:1076](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:1076). Ledger records have the same issue: validation consumes them at [ledger.py:457](/Users/ohayotaro/claude-finance/src/risk/ledger.py:457), followed by insertion at [ledger.py:387](/Users/ohayotaro/claude-finance/src/risk/ledger.py:387).

   Python does not enforce the annotated `tuple` types. A dynamically loaded adapter can return a generator or another one-shot iterable. I reproduced both position and fill cases: validation succeeded, but the second iteration was empty. Consequences include:

   - Positions and unrealized losses disappear.
   - Residual strategies can be cleared as flat.
   - Fills and cash events are omitted while the venue cursor still advances.
   - The cycle can publish healthy state with understated loss and exposure.

   Materialize each collection exactly once into immutable tuples before validation and reuse those tuples, or reject non-tuples fail-closed. Add regressions covering positions, orders, fills, and cash events.

2. High - A refused checkpoint save does not prevent publication of healthy stale state. [AC4, AC5, AC7]

   When the ledger binding has advanced, `save_checkpoint` only logs and returns at [aggregator.py:1503](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:1503). The loop then unconditionally publishes state at [aggregator.py:2103](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:2103). Nothing marks `fail_closed`, invalidates provenance, or makes `_is_healthy` false.

   A concurrently committed loss can therefore be absent from cached PnL while the state file still says `healthy: true`. The existing test at [test_aggregator.py:2492](/Users/ohayotaro/claude-finance/tests/test_risk/test_aggregator.py:2492) verifies only that the checkpoint remains unchanged and a log is emitted.

   `save_checkpoint` should return success or raise. A binding mismatch must prevent healthy publication and publish fail-closed state instead.

3. High - Accepted finite `Decimal` values can crash reconciliation after the ledger commits. [AC3, AC7]

   Validation checks only `Decimal.is_finite()` at [aggregator.py:817](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:817). The guarded reconciliation block ends at [aggregator.py:1074](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:1074), while exposure, PnL, drawdown, and cap arithmetic occurs afterward, beginning at [aggregator.py:1090](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:1090).

   I reproduced `decimal.Overflow` in `compute_group_metrics` using individually finite `Decimal("1e999999")` size and price values. In `run_forever`, this exception escapes, terminating the risk service after ledger mutation without publishing fail-closed state.

   Validate supported numeric magnitude/exponent ranges and treat all post-commit accounting failures like the D2 failure path.

4. Low - The implementation result still violates E4 and does not provide the required AC-to-test-name mapping. [AC7]

   [implementation-result.md:5](/Users/ohayotaro/claude-finance/.claude/tasks/risk-ledger-accounting-001/implementation-result.md:5) onward contains Japanese and non-ASCII text despite the English/plain-ASCII requirement. Its AC table at [implementation-result.md:54](/Users/ohayotaro/claude-finance/.claude/tasks/risk-ledger-accounting-001/implementation-result.md:54) lists test categories, not the named tests proving each AC. `test-evidence.md` contains names but no AC-to-test-name map.

## Acceptance-criteria gaps

| AC | Review status |
|---|---|
| AC1 | Gap: one-shot fill/cash collections can be discarded while advancing the cursor. |
| AC2 | Gap: one-shot position observations can become an authoritative zero after validation. |
| AC3 | Gap: one-shot positions/orders can clear residual strategies. The existing combined test also does not independently prove deprecated-position PnL/cap behavior or retired residual behavior. |
| AC4 | Gap: checkpoint refusal does not block healthy state publication. |
| AC5 | Gap: published health/provenance does not reflect a checkpoint/ledger binding refusal. |
| AC6 | Met by static inspection; the example matches the loader and its test was collected. |
| AC7 | Not met because of the findings above, incomplete independent test execution, and the result-artifact defects. |
| AC8 | Met by ADR-005 in `DESIGN.md`. |

## Validation gaps

- The required offline `uv` risk-suite command could not initialize its cache because this review sandbox is read-only: `Operation not permitted`.
- Full risk and fast suites were therefore not independently executed.
- `116` risk tests collected successfully.
- Five read-only selected tests passed.
- Direct installed-tool validation passed:
  - Ruff: `All checks passed!`
  - Mypy: `Success: no issues found in 14 source files`
  - Registry audit: `audit: ok (0 strategies, 0 accounts)`
  - `git diff --check`: exit 0

## Residual risks

- Financial: no real venue adapter validates venue cursor, timestamp, and normalized realized-PnL semantics. Exposure still uses entry-price notional.
- Operational: the advisory lock is host-local and relies on all ledger writers cooperating; `fcntl` is Unix-specific.
- Security: no new credential or network behavior was observed, but an in-process or non-cooperating ledger writer can bypass the lock contract.
- Regression: missing tests for one-shot/mutable adapter collections, post-validation extreme arithmetic, unhealthy publication after checkpoint refusal, and retired-strategy residual accounting.