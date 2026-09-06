Status: **PASS**

Implemented L1/L2. Null-day checkpoints now require an initial ledger binding, zero cached PnL, and no cap flags. Invalid checkpoints publish fail-closed state and exit before contacting the venue.

Files changed:

- [persistence.py](/Users/ohayotaro/claude-finance/src/risk/persistence.py:726)
- [test_persistence.py](/Users/ohayotaro/claude-finance/tests/test_risk/test_persistence.py:257)
- [implementation-result.md](/Users/ohayotaro/claude-finance/.claude/tasks/risk-ledger-accounting-002/implementation-result.md)

Validation ran offline:

| Command | Result |
|---|---|
| `uv run --extra dev pytest tests/test_risk/ -v` | 203 passed |
| `uv run --extra dev pytest -m "not integration and not slow"` | 372 passed |
| `uv run --extra dev ruff check src/ tests/ .claude/hooks/ .claude/scripts/` | Passed |
| `uv run --extra dev mypy src/ .claude/scripts/` | Passed, 19 files |
| `uv run python -m src.orchestrator.registry audit` | Passed |
| `git diff --check` | Exit 0, no output; run last |

The L1 regressions produced **10 failures and 4 passes before the fix**, then **14 passes afterward**.

AC1-AC7 pass: semantic and startup regressions pass; module boundaries remain valid; all baseline cases and assertions are preserved; required checks pass; the rewritten English ASCII artifact contains the exact test-name mapping, inventory reference, and every module’s line count.

Residual debt: `persistence.py` is 897 lines. Native Windows locking and real venue integration remain unverified. Independent review and PM acceptance are pending. Unrelated work and review artifacts were preserved.