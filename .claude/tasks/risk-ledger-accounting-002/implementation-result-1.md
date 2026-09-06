Status: PASS

## Summary

Implemented all approved Part A fixes and decomposed the aggregator without weakening existing assertions.

- Checkpoints now validate ledger timestamp, recomputed realized/pending PnL, and current-config cap flags using staged restoration.
- Adapter, registry-load, and registry-path startup refusals replace prior healthy state with fail-closed state.
- Malformed-log warnings include absolute byte offsets.
- `aggregator.py` is now a 553-line orchestration/CLI compatibility facade.
- Final inventory: 346 fast tests and 177 risk tests, up from 332 and 163.
- Full evidence and old/new test mapping: [implementation-result.md](/Users/ohayotaro/claude-finance/.claude/tasks/risk-ledger-accounting-002/implementation-result.md:1)

## Files changed

- Risk runtime: [aggregator.py](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:1), [ledger.py](/Users/ohayotaro/claude-finance/src/risk/ledger.py:1), [config.py](/Users/ohayotaro/claude-finance/src/risk/config.py:1), [observations.py](/Users/ohayotaro/claude-finance/src/risk/observations.py:1), [accounting.py](/Users/ohayotaro/claude-finance/src/risk/accounting.py:1), [persistence.py](/Users/ohayotaro/claude-finance/src/risk/persistence.py:1), [publication.py](/Users/ohayotaro/claude-finance/src/risk/publication.py:1)
- Split tests and shared support under [tests/test_risk](/Users/ohayotaro/claude-finance/tests/test_risk)
- ADR-005 module map in [DESIGN.md](/Users/ohayotaro/claude-finance/.claude/docs/DESIGN.md:44)
- Implementation evidence linked above

## Material design decisions

- `LedgerBinding` atomically exposes cursor, generation, and `as_of`.
- Matching checkpoints recompute ledger PnL before mutating live state.
- Ledger-ahead recovery remains intentionally fail closed while preserving cached caps and high-water mark.
- Cap flags are compared with independently recomputed values rather than silently corrected.
- Explicit compatibility aliases preserve existing imports and dynamic adapter specifications.
- No extracted module imports `aggregator.py`.

Module sizes:

- `aggregator.py`: 553
- `config.py`: 216
- `observations.py`: 758
- `accounting.py`: 390
- `persistence.py`: 898
- `publication.py`: 336
- `ledger.py`: 757

## Validation

All `uv` commands used `UV_OFFLINE=1` and a sandbox-writable temporary cache.

```text
uv run --extra dev pytest <six targeted Part A functions> -v
11 passed in 0.07s

uv run --extra dev pytest tests/test_risk/ -v
177 passed in 0.69s

uv run --extra dev pytest tests/test_risk/ --collect-only -q
177 tests collected in 0.03s

uv run --extra dev pytest -m "not integration and not slow"
346 passed in 6.72s

uv run --extra dev ruff check src/ tests/ .claude/hooks/ .claude/scripts/
All checks passed!

uv run --extra dev mypy src/ .claude/scripts/
Success: no issues found in 19 source files

uv run python -m src.orchestrator.registry audit
audit: ok (0 strategies, 0 accounts)

uv run python -m src.risk.aggregator --help
PASS, exit 0

git diff --check
PASS, exit 0, no output; run last
```

The pre-decomposition assertion audit found zero assertion-count decreases across all 97 baseline aggregator test functions. The implementation artifact is plain ASCII.

## Acceptance criteria

| AC | Result |
|---|---|
| AC1 | PASS — checkpoint PnL, cap consistency, consistent restore, and atomic metadata tests pass |
| AC2 | PASS — adapter and parameterized registry refusal publication tests pass |
| AC3 | PASS — exact malformed-line byte offset test passes |
| AC4 | PASS — facade and module budgets pass; inward dependency search has no matches |
| AC5 | PASS — 332 to 346 fast cases, 163 to 177 risk cases; no renamed or weakened tests |
| AC6 | PASS — all required offline commands and final diff check pass |
| AC7 | PASS — ADR module map, compatibility, ASCII artifact, and exact AC test-name mapping completed |

## Residual risks and debt

- `persistence.py` has only two lines of budget headroom; its structural regression prevents unnoticed growth.
- The accepted ledger-ahead path cannot reconstruct prior-generation metadata and therefore remains fail closed until fresh reconciliation.
- No real venue adapter was added, so production venue normalization and cursor behavior remain unvalidated.
- Previously deferred exposure pricing, compaction, multi-currency, shared cash allocation, and cross-machine locking remain out of scope.