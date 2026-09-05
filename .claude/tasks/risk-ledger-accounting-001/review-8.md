# Verdict: CHANGES_REQUIRED

## Findings

### High - A newer position snapshot can hide a realized loss

[aggregator.py](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:1219) cuts ledger PnL at `min(position_cut, batch_cut)`, but [aggregator.py](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:1339) sums unrealized PnL from the unadjusted, later position snapshot.

For example:

- Ledger is complete through 12:00.
- A position realizes a large loss at 12:00:20.
- The 12:00:30 position snapshot is flat.
- The default 60-second skew permits this combination.

The loss is absent from ledger PnL because it occurred after 12:00, and absent from unrealized PnL because the later position snapshot is flat. The aggregator can therefore publish zero PnL, clear caps, and report healthy until the next ledger batch.

[aggregator.py](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:1550) also labels the later unrealized value with the older ledger timestamp, making the provenance timestamp inaccurate. The existing test at [test_aggregator.py](/Users/ohayotaro/claude-finance/tests/test_risk/test_aggregator.py:3284) uses a position unchanged across the gap and does not cover an intervening close.

This violates the common-cut and fail-closed intent of H1 and leaves AC2/AC5 incomplete. A position cut newer than the ledger completeness watermark should fail closed unless the adapter can supply positions as of the enforcement cut.

### Low - The implementation result still violates I5/F6 evidence requirements

The acceptance table in [implementation-result.md](/Users/ohayotaro/claude-finance/.claude/tasks/risk-ledger-accounting-001/implementation-result.md:62):

- Omits the required rotation, truncation, and late-precheckpoint tests from AC4.
- Omits the log-source/stale-metric consumer test from AC5.
- Uses prose rather than exact test names for AC7 at [line 65](/Users/ohayotaro/claude-finance/.claude/tasks/risk-ledger-accounting-001/implementation-result.md:65).

The linked `test-evidence.md` is more complete, but I5 specifically requires every implementation-result AC row to contain exact comma-separated test function names. This is an AC7 evidence gap.

## Acceptance-criteria gaps

| AC | Review status |
|---|---|
| AC1 | Met by code and test inspection. |
| AC2 | Not met fully because the positive-skew common-cut path can omit losses. |
| AC3 | Met by code and test inspection. |
| AC4 | Functional tests exist, but the implementation-result mapping is incomplete. |
| AC5 | Not met fully because unrealized provenance can claim an earlier cut than the value represents. |
| AC6 | Met by code and test inspection. |
| AC7 | Not fully verified in this review, and the I5 evidence format is noncompliant. |
| AC8 | Met; ADR-005 records the model and ADR-004 exception. |

## Validation gaps

The read-only review sandbox has no writable temporary directory:

- The required offline `uv run` command failed while initializing its cache with `Operation not permitted`.
- Direct full pytest startup failed with `No usable temporary directory found`.
- No network access was attempted.

Independent checks completed:

- Risk-test collection: 161 tests collected.
- Six pure aggregator tests: passed.
- Ruff: passed.
- Mypy: passed, 14 source files.
- Registry audit: passed.
- `git diff --check`: exit code 0.

The reported `161 passed` risk suite and `330 passed` fast suite therefore remain artifact claims rather than independently reproduced results.

## Residual risks

- Financial: losses can be understated during the allowed position-newer-than-ledger skew.
- Operational: no real venue adapter validates cursor completeness or normalized realized PnL.
- Security/operations: writer locking remains host-local and cooperative.
- Regression: full tests and an actual Windows import/locking run were not independently executed.
- Deferred by scope: mark-price exposure, ledger compaction, currency conversion, and shared-account cash allocation remain unresolved.