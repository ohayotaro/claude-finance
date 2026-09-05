# Verdict: CHANGES_REQUIRED

## Findings

### High

1. **The documented Decimal input domain is not closed under aggregation or checkpoint persistence.**  
   Individual values up to `1e40` pass validation, but two valid position inputs can produce `1e80` exposure, which is saved successfully and then rejected while loading the generated checkpoint by the original `1e40` bound. Likewise, ten valid `1e40` ledger entries produce `1e41`; the records commit, then the total query rejects the result, leaving the current day persistently fail-closed. This contradicts the documented accumulation headroom. See [ledger.py](/Users/ohayotaro/claude-finance/src/risk/ledger.py:129), [ledger.py](/Users/ohayotaro/claude-finance/src/risk/ledger.py:730), and [aggregator.py](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:1875).  
   **Maps to:** AC4, AC7/H2, AC8.

2. **Loss-limit decisions still depend on ambient Decimal rounding.**  
   `determine_signals` performs division and multiplication outside the isolated context. With valid PnL `-4.9999999999999999999999999999` and balance `100`, the exact loss is below 5%, but the current code rounds it to 5% and sets `hard_cap=True`, potentially triggering an unnecessary flatten. Drawdown calculations and checkpoint PnL-consistency arithmetic have the same ambient-context leak. See [aggregator.py](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:746), [aggregator.py](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:1315), and [aggregator.py](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:2275).  
   **Maps to:** AC7/H2 and the objective’s loss-limit correctness requirement.

### Medium

3. **Configured future-skew tolerance cannot produce a healthy consumable state.**  
   Venue timestamps up to `future_skew_tolerance_s` ahead are accepted during reconciliation, but `_is_healthy` and the consumer validator reject every negative age. An adapter consistently one second ahead with a configured two-second tolerance therefore reconciles successfully but publishes `healthy=false` every cycle. The D1 test checks reconciliation success but not published health or consumer validation. See [aggregator.py](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:857), [aggregator.py](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:1422), and [aggregator.py](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:1578).  
   **Maps to:** AC5 and corrections D1/E1.

4. **The CLI’s NullVenue refusal bypasses fail-closed state publication.**  
   `main` returns before `run_forever`, while only the latter publishes an unhealthy state for this condition. A recently published healthy state can therefore remain consumable until its health window expires after a misconfigured restart. See [aggregator.py](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:2805) versus [aggregator.py](/Users/ohayotaro/claude-finance/src/risk/aggregator.py:2669).  
   **Maps to:** AC5 and the explicit NullVenue fail-closed requirement.

### Low

5. **The implementation-result AC table still violates H3.**  
   AC4, AC6, AC7, and AC8 contain prose instead of only exact comma-separated test names, despite the evidence artifact claiming every row complies. See [implementation-result.md](/Users/ohayotaro/claude-finance/.claude/tasks/risk-ledger-accounting-001/implementation-result.md:63) and [test-evidence.md](/Users/ohayotaro/claude-finance/.claude/tasks/risk-ledger-accounting-001/test-evidence.md:319).  
   **Maps to:** AC7/H3.

6. **The example configuration documents accounting-cut skew as one-sided.**  
   Its comment only describes positions older than the ledger, while the implemented and approved rule is symmetric. See [risk_groups.toml](/Users/ohayotaro/claude-finance/config/risk_groups.toml:16).  
   **Maps to:** AC6/H1.

## Acceptance-criteria gaps

- **AC1–AC3:** No additional gap found in the reviewed code and tests.
- **AC4:** Valid computed values can generate a checkpoint that cannot be restored.
- **AC5:** Allowed clock skew remains unhealthy, and the `main` NullVenue path may leave prior healthy state behind.
- **AC6:** The example loads, but its skew documentation is inaccurate.
- **AC7:** Missing regressions for exact cap boundaries, derived-value checkpoint round trips, allowed-skew health, and CLI NullVenue publication; H3 evidence is also noncompliant.
- **AC8:** ADR-005 exists and records the exception, but its claimed Decimal accumulation headroom is not honored by runtime validation.

## Validation gaps

- Full required pytest execution was blocked by the read-only review sandbox: both `uv` cache initialization and pytest temporary-file creation require writes. No network was attempted.
- Collection succeeded: 156 risk tests and 325 fast-suite cases.
- Five write-free targeted tests passed.
- Ruff passed, mypy passed for 14 source files, registry audit passed, and `git diff --check` exited 0.
- Windows locking is covered only through mocked backend selection; no native Windows execution was independently reproduced.

## Residual risks

- **Financial:** Ambient rounding can emit a false hard-cap/flatten signal; exposure still uses entry price as explicitly deferred.
- **Operational:** Valid boundary values can poison same-day ledger calculation or make generated checkpoints unrestorable; SQLite growth remains unbounded.
- **Security:** No new credential or network issue found. Writer locking remains host-local and cooperative.
- **Regression:** No real venue validates cursor completeness or normalized venue PnL; shared-account cash allocation and currency conversion remain deferred.