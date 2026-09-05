# Verdict: CHANGES_REQUIRED

## Findings

1. **High — Checkpoint “binding” does not prove that cached PnL or cap state came from the bound ledger.**  
   [aggregator.py](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:1857) verifies only cursor/generation before serializing cached financial values. On restoration, [aggregator.py](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:2309) trusts checkpoint PnL, checks only realized-plus-unrealized consistency at [aggregator.py](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:2422), then accepts a matching cursor/generation at [aggregator.py](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:2541). It never:

   - Recomputes realized and pending PnL from the ledger for the persisted day/cut.
   - Verifies the checkpoint ledger timestamp against ledger metadata.
   - Verifies `soft_cap`, `hard_cap`, and `margin_emergency` against cached PnL, balance, margin, and current configuration.

   Consequently, a matching-generation checkpoint can state a ledger-derived loss of zero, or `hard_cap=false` for a 6% loss, and be accepted. If the first venue cycle after restart fails, that state remains enforced until fail-closed activates. Existing fixtures even save `daily_realized_pnl=-500` against a ledger containing no fills at [test_aggregator.py](/Users/ohayotaro/claude-finance/tests/test_risk/test_aggregator.py:2413). This violates checkpoint cache trust and AC4 recovery semantics.

2. **High — Explicit venue-client and other post-config startup failures leave an earlier healthy state file in place.**  
   Only the NullVenue refusal publishes an unhealthy replacement. An explicit adapter load failure returns immediately at [aggregator.py](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:2945), while registry and registry-path failures similarly return at [aggregator.py](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:2965) and [aggregator.py](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:2975). A previous `healthy=true` state therefore remains consumable until its freshness window expires even though the new process has definitively refused to start. These paths should publish fail-closed state once configuration and the state path are available. This is an AC5 fail-closed publication gap.

3. **Low — The implementation result still violates J2/H3.**  
   Its acceptance section contains prose rather than rows containing exact comma-separated test function names, and [implementation-result.md](/Users/ohayotaro/claude-finance/.claude/tasks/risk-ledger-accounting-001/implementation-result.md:63) circularly claims the mappings are in the same file. This directly contradicts Addendum 8 J2 and leaves AC7 evidence incomplete.

4. **Low — Malformed-log warnings omit the required byte offset.**  
   [aggregator.py](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:693) parses individual records, but its warning at [aggregator.py](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:722) reports only strategy and counts. `multi-strategy.md` section 6 requires the strategy ID and offset for malformed lines. No regression test covers this diagnostic requirement.

## Acceptance-criteria gaps

| AC | Review status |
|---|---|
| AC1 | No static implementation gap identified; execution was not independently completed. |
| AC2 | No static implementation gap identified; venue-only unrealized accounting and zero handling are present. |
| AC3 | No static implementation gap identified; disabled/deprecated/retired residual tests are present. |
| AC4 | **Not met:** checkpoint cursor/generation matching does not validate ledger-derived PnL or cap consistency. |
| AC5 | **Not fully met:** several definitive startup failures do not replace prior state with fail-closed publication. |
| AC6 | Example configuration exists and statically matches the loader. |
| AC7 | **Not met:** J2 evidence is malformed, new regressions are needed for findings 1–2, and the required pytest commands could not be independently completed. |
| AC8 | ADR-005 exists and records the ADR-004 exception and accounting model. |

## Validation gaps

The read-only review environment cannot create a uv cache or pytest temporary directory. No network access was attempted.

- Required offline `uv run ... pytest tests/test_risk/ -v` stopped before collection because uv could not initialize its cache.
- Direct collection succeeded: `332 tests collected`.
- Direct read-only checks succeeded:
  - Ruff: `All checks passed!`
  - mypy: `Success: no issues found in 14 source files`
  - Registry audit: `audit: ok (0 strategies, 0 accounts)`
  - `git diff --check`: exit 0
- A read-only subset produced `17 passed`; one additional test failed during fixture setup solely because no writable temporary directory existed.
- The full risk suite, full fast suite, and Windows locking behavior were therefore not independently executed.

## Residual risks

- **Financial:** A ledger-inconsistent or cap-inconsistent checkpoint can understate losses after restart; exposure still uses entry-price notional as explicitly deferred.
- **Operational:** Startup refusal can leave stale healthy state; locking is host-local/cooperative; ledger retention is unbounded.
- **Security:** Checkpoint financial/control contents have no semantic integrity check against the authoritative ledger.
- **Regression:** The aggregator is now over 3,000 lines, and the complete 332-test suite could not be rerun in this read-only review environment.