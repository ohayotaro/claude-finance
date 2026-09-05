## Verdict: CHANGES_REQUIRED

### Findings

High

1. The common accounting cut is still one-sided. [aggregator.py:992](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:992) rejects positions that are too old relative to the ledger, but accepts positions newer than the ledger watermark. The realized query then cuts at the newer position timestamp [aggregator.py:1171](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:1171), although the ledger is only complete through `batch.as_of`.

   Example: ledger complete through 12:00, positions flat at 12:01, and a loss-closing fill at 12:00:30 not yet present in ledger history. The cycle publishes zero realized and unrealized PnL, resets `fail_closed`, and may clear caps even though the loss occurred. This violates Addendum G1’s common-cut invariant. The existing regression only tests positions older than the ledger [test_aggregator.py:3179](/Users/ohayotaro/claude-finance/tests/test_risk/test_aggregator.py:3179).

   Add a regression proving a position cut newer than the ledger cut fails closed and preserves caps/residual state.

2. Accepted `Decimal` values are not guaranteed to be calculated exactly. Validation bounds exponent and scale [ledger.py:113](/Users/ohayotaro/claude-finance/src/risk/ledger.py:113), but permits more significant digits than Python’s default 28-digit context. Ledger accumulation [ledger.py:691](/Users/ohayotaro/claude-finance/src/risk/ledger.py:691), exposure multiplication [aggregator.py:728](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:728), and unrealized summation [aggregator.py:1285](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:1285) therefore round silently.

   An accepted example produced `0.02` through sequential ledger-style accumulation where the exact result is `0.01`. Arithmetic also depends on any ambient change to the process-global decimal context. Use an isolated sufficiently precise context or exact mantissa accumulation, and add high-precision/order-independence regressions. This affects AC1 and Addendum F4.

Low

3. The implementation result still does not satisfy F6’s requirement that its AC table name the proving tests. Most rows use descriptions such as “Venue-zero” or “residual-retention” rather than exact test names [implementation-result.md:61](/Users/ohayotaro/claude-finance/.claude/tasks/risk-ledger-accounting-001/implementation-result.md:61). `test-evidence.md` contains the names, but F6 explicitly requires them in this table.

### Acceptance-criteria gaps

- AC1: Not met for the documented supported Decimal domain because ledger totals can round.
- AC2: Original venue-zero/log-omission behavior is covered, but the G1 common-cut correction mapped to AC2 remains incomplete.
- AC5: Provenance fields exist, but a position snapshot newer than ledger completeness can still be published as an authoritative composite metric.
- AC7: Blocked by the correctness findings and the incomplete implementation-result mapping.
- AC3, AC4, AC6, and AC8: No additional code gap found, subject to the validation limitation below.

### Validation gaps

- Direct Ruff: passed.
- Direct strict mypy: passed, 14 source files.
- Direct registry audit: passed.
- `git diff --check`: exit 0.
- Pytest collection: 152 risk tests and 321 fast tests collected.
- Six read-only-compatible unit tests passed.
- Full pytest execution and the exact `uv run` commands could not run because the enforced read-only environment provides no writable UV cache or temporary directory. No network access was attempted. The implementation artifact reports 152 risk and 321 fast tests passing, but that was not independently reproduced here.
- The real Windows import/locking path was not independently executed.

### Residual risks

- No real venue adapter validates cursor completeness or normalized venue PnL semantics.
- Exposure still uses entry price rather than current venue notional, as already deferred.
- The single-writer lock is host-local and cooperative.
- Allocation of unattributed account cash events across multiple risk groups sharing an account remains undefined.
- Ledger growth, cross-account conversion, and multi-currency accounting remain deferred.
- No new credential, network, dependency, or forbidden-file change was found.