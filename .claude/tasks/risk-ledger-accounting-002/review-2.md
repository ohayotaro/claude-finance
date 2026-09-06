Verdict: **CHANGES_REQUIRED**

1. **High - AC1: A null checkpoint day bypasses ledger PnL verification.**  
   [persistence.py:731](/Users/ohayotaro/claude-finance/src/risk/persistence.py:731) accepts `current_utc_date=null` when cached realized and pending PnL are zero, even for an already reconciled ledger. This skips recomputation.

   I reproduced this with SQLite in memory and mocked checkpoint I/O: a valid checkpoint restored a `-600` loss and `hard_cap=true`. After clearing its day, cached PnL, and caps, restoration succeeded. Following one venue failure, the serialized state reported `healthy=true`, `fail_closed=false`, and `hard_cap=false`, while the ledger still contained `-600`.

   Require a persisted day for reconciled checkpoints, reserving the null-day case for valid bootstrap state. Add a regression proving rejection and fail-closed startup publication.

2. **Low - AC7/K3: The implementation result lacks the required AC table.**  
   [implementation-result.md:23](/Users/ohayotaro/claude-finance/.claude/tasks/risk-ledger-accounting-002/implementation-result.md:23) claims an exact test-name mapping exists, but the file contains no AC table or test function names. It also omits the complete module line counts. Rewrite the artifact with the required evidence and reference `test-evidence.md` for the inventory.

| Criterion | Review conclusion |
|---|---|
| AC1 | Incomplete: null-day corruption bypass confirmed. Other requested semantic checks are present. |
| AC2 | Named startup refusals use fail-closed publication; regression tests are present. Execution remains unverified here. |
| AC3 | Malformed warnings include raw byte offsets; named regression is present. |
| AC4 | Verified: facade is 553 lines; extracted modules are 216, 758, 390, 899, and 336 lines. Structural and compatibility tests passed. |
| AC5 | All 358 collected cases match the evidence: 332 baseline plus 26 additions, including 189 risk cases. Full execution and assertion preservation remain independently unverified. |
| AC6 | Partially verified; full validation is blocked by filesystem permissions. |
| AC7 | Module map and ASCII checks pass; implementation evidence remains incomplete. |

K1's exact-context decorator and `copy_abs()` correction are present. K2's source-move ranges and failing-first results are recorded. The historical source snapshots and raw results referenced outside the working tree were not inspected.

Validation gaps and results:

- All four required offline `uv` commands exited 2 before execution because uv cache access was denied.
- Direct installed-tool runs passed: ruff with `--no-cache`, mypy with `--cache-dir=/dev/null` (19 files), and registry audit.
- Eight targeted accounting and structural tests passed.
- The direct fast-suite attempt stopped at **3 passed, 1 setup error** because no writable temporary directory was available.
- `git diff --check` ran last and exited 0 without whitespace findings; Git emitted sandbox-related cache diagnostics.

Residual financial risk is the demonstrated loss-cap bypass. Operational risks include unvalidated real venue integration and filesystem-dependent publication. Security review found no changes to the forbidden paths, but checkpoint trust remains defective. Regression risk remains from the blocked full suite and unavailable independent comparison against the pre-decomposition source snapshot.

No repository files were changed, no review artifact was written, and no network access was used.