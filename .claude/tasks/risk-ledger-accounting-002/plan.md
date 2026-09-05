Plan status: READY FOR PM REVIEW. Read-only inspection is complete; no repository files were edited, no network access was used, and all existing dirty-worktree changes remain untouched. Implementation is gated on explicit T3 approval for task 002.

## Recommended design and rationale

### 1. Implement Part A before decomposition

Apply the three runtime fixes to the current monolith first and run their targeted tests before moving code. This keeps behavioral changes distinguishable from the later mechanical refactor.

#### Checkpoint semantic integrity

Keep checkpoint schema version 3 because all required fields already exist. Strengthen restoration as follows:

1. Require `load_checkpoint` to receive the current `AggregatorConfig`.
2. Add an atomic ledger metadata snapshot containing cursor, generation, and `as_of`. Read these values from one SQLite snapshot.
3. Parse the checkpoint into staged state so malformed input cannot partially mutate live state.
4. Recompute the persisted day's realized PnL:
   - Enforcement cut: `min(positions_as_of_ts, ledger_as_of_ts)`.
   - Realized: ledger total through the enforcement cut.
   - Pending: full persisted-day ledger total minus realized through the cut.
   - Perform subtraction and comparisons inside `decimal_arithmetic_context()`.
5. When checkpoint cursor and generation match the current ledger:
   - Require checkpoint `ledger_as_of_ts` to equal ledger metadata `as_of`.
   - Compare recomputed realized and pending PnL with persisted values.
   - Read ledger metadata again after the queries and reject a concurrent change.
6. Recompute `soft_cap`, `hard_cap`, and `margin_emergency` from cached group PnL, snapshot balance/margin, and current configuration. Compare rather than silently overwrite.
7. Treat any semantic mismatch as checkpoint corruption. Startup must publish fail-closed state and return non-zero.
8. Preserve the accepted ledger-ahead recovery path: if cursor or generation has advanced since the checkpoint, retain cached HWM and caps but mark the baseline unverified and remain fail closed. Historical totals for the old generation cannot safely be reconstructed from current metadata.
9. Audit every checkpoint fixture. In particular:
   - Give `test_checkpoint_save_load_roundtrip` real ledger events matching its realized and pending values.
   - Give `test_restart_then_venue_failure_retains_cached_state` a ledger-backed `-500` realized loss and make both soft and hard cap assertions consistent with its `-5.5%` group loss.
   - Populate correct ledger timestamps and bindings in crash/concurrency fixtures.

Add:

- `test_checkpoint_pnl_inconsistent_with_ledger_is_rejected`, parameterized over realized PnL, pending PnL, and ledger timestamp tampering while preserving the checkpoint's existing internal arithmetic invariants.
- `test_checkpoint_cap_flags_inconsistent_with_pnl_are_rejected`, covering independent soft-cap, hard-cap, and margin-emergency inconsistencies.
- Keep and strengthen `test_checkpoint_save_load_roundtrip` as the consistent-restore proof.
- Add `test_ledger_metadata_snapshot_binds_cursor_generation_and_as_of` in the ledger suite.

#### Definitive startup refusal publication

Use the existing NullVenue startup publication helper for every refusal that occurs after configuration and the state path have been validated:

- Venue adapter load or protocol failure.
- Registry load/schema failure.
- Registry-derived path validation failure.

Each path must attempt an atomic fail-closed state replacement before returning `ExitCode.INVARIANT_VIOLATION`. Publication failure itself remains a critical error and non-zero exit; it must never fall back to a healthy or log-derived state.

Add:

- `test_adapter_load_failure_publishes_fail_closed_state`.
- `test_registry_failure_publishes_fail_closed_state`, parameterized over registry load failure and registry path failure.

Both tests will seed an earlier healthy state and prove it is replaced by schema-v2 state with `healthy=false`, `fail_closed=true`, and non-authoritative metric provenance.

#### Malformed-log offsets

Iterate complete log bytes with `splitlines(keepends=True)` and maintain the absolute byte offset from the descriptor's selected start offset. Every malformed-line warning will include:

- The expected strategy ID.
- A heuristically extracted strategy ID when JSON parsing got far enough.
- `offset=<absolute byte offset>` for the first byte of the offending line.

Byte offsets will advance using raw byte lengths, not decoded character counts. Existing quarantine counting and malformed-line continuation behavior remain unchanged.

Add `test_malformed_log_warning_includes_offset` with a valid prefix line followed by a malformed line so the asserted offset is non-zero and exact.

### 2. Decompose around one-way dependency boundaries

The proposed final dependency direction is:

```text
ledger.py       config.py
    \             /
     observations.py
            |
       accounting.py
        /         \
persistence.py  publication.py
        \         /
         aggregator.py
```

No extracted module may import `aggregator.py`.

| Module | Responsibility | Planned limit |
|---|---|---:|
| `src/risk/config.py` | `AggregatorConfig`, config parsing, risk-group validation, safe aggregator paths, raw group-block loading, lifecycle constants | Under 300 lines |
| `src/risk/observations.py` | Venue DTOs and protocol, NullVenue, adapter loading, strategy selection, log-tail parsing, collection materialization, timestamp/identity/currency/completeness validation | Under 850 lines |
| `src/risk/accounting.py` | `AggregatorState`, exact exposure/PnL/drawdown calculations, cap evaluation, UTC-day transition, residual strategy accounting, staged successful-cycle application and failure invalidation | Under 500 lines |
| `src/risk/persistence.py` | Checkpoint schema/migration, staged decoding, semantic ledger binding, save/load, atomic JSON primitive, portable writer lock | Under 900 lines, target under 875 |
| `src/risk/publication.py` | Health calculation, metric provenance, consumer validation, state serialization, atomic state publication, startup fail-closed publication | Under 450 lines |
| [aggregator.py](/Users/ohayotaro/claude-finance/src/risk/aggregator.py) | Reconciliation transaction orchestration, run loop, startup ordering, signal handling, CLI, explicit compatibility re-exports | Under 600 lines, target under 500 |
| [ledger.py](/Users/ohayotaro/claude-finance/src/risk/ledger.py) | Existing SQLite ledger plus atomic cursor/generation/as-of metadata snapshot | Remains bounded and independent |

`aggregator.py` will continue to support `python -m src.risk.aggregator`. Existing public names will be explicitly re-exported so current imports and dynamic specs such as `src.risk.aggregator:NullVenueClient` keep working. Tests for module-private helpers will switch to their owning modules.

Checkpoint parsing will use staged state and shared typed-field helpers. This both avoids partial restoration and keeps `persistence.py` below its hard line limit without deleting v1/v2 migration behavior.

### 3. Split tests along the same boundaries

The current 3,695-line [test_aggregator.py](/Users/ohayotaro/claude-finance/tests/test_risk/test_aggregator.py) will become:

- `tests/test_risk/test_config.py`
- `tests/test_risk/test_observations.py`
- `tests/test_risk/test_accounting.py`
- `tests/test_risk/test_persistence.py`
- `tests/test_risk/test_publication.py`
- `tests/test_risk/test_aggregator.py`, retaining only reconciliation/run-loop/CLI integration
- `tests/test_risk/_aggregator_support.py`, containing shared factories and the stub venue client

[test_ledger.py](/Users/ohayotaro/claude-finance/tests/test_risk/test_ledger.py) remains the ledger module's test file.

Existing test function names will not be renamed. Moves will therefore be recorded as old node path to new node path with the function name unchanged. Assertions will move verbatim except for:

- Ledger-consistent checkpoint fixture construction.
- Stronger cap assertions required by the corrected fixture.
- Import and monkeypatch targets updated to the new owning module.

Add structural regressions:

- `test_aggregator_module_boundaries_are_bounded_and_inward`
- `test_aggregator_public_reexports_remain_available`
- `test_adr_005_documents_aggregator_module_map`

### 4. Append the ADR-005 module map

Append a new `Module map (risk-ledger-accounting-002)` subsection to [DESIGN.md](/Users/ohayotaro/claude-finance/.claude/docs/DESIGN.md:44). It will document:

- Ownership of configuration, observations, accounting, checkpoint persistence, publication, and orchestration.
- The one-way dependency graph.
- `aggregator.py` as the stable CLI and compatibility facade.
- The hard line budgets.
- The rule that no extracted module imports the facade.

Existing ADR-005 history and task-001 decisions will not be rewritten.

### 5. Produce compliant implementation evidence

Create `.claude/tasks/risk-ledger-accounting-002/implementation-result.md` once, as a whole-file replacement, after implementation evidence has been assembled. It will be English, plain ASCII, and contain:

- Status `PASS`, `PARTIAL`, or `BLOCKED`.
- Files changed.
- Behavioral decisions and pure-move hunk groups.
- Exact validation commands and outputs.
- Before/after test counts and inventory.
- Every moved test as old path/name to new path/name.
- Line counts for every risk module.
- Residual risks.
- An AC table whose evidence cells contain only comma-separated exact test function names. Command and documentation evidence will be outside that table.

No implementation phase action will create or modify `review.md`.

## Alternatives considered

| Alternative | Decision |
|---|---|
| Decompose before fixing Part A | Rejected. It would mix financial behavior changes with thousands of moved lines and make review attribution harder. |
| Keep configuration inside observations | Rejected. The combined venue, log, config, and validation surface would approach or exceed the 900-line limit. |
| Add checkpoint schema v4 with a new enforcement-cut field | Rejected. The cut can be derived from existing persisted provenance, so a migration is unnecessary. |
| Trust checkpoint values after validating only cursor/generation | Rejected. This is the open review-9 defect and does not prove ledger or cap semantics. |
| Recompute and silently replace inconsistent checkpoint cap flags | Rejected. The brief requires mismatches to be treated as corruption and fail closed. |
| Add a hash or HMAC over checkpoint values | Rejected. A hash would detect byte changes but would not prove agreement with authoritative ledger contents or current configuration. |
| Remove the old aggregator imports and update every caller | Rejected. Explicit re-exports provide a safer compatibility boundary while tests move to direct owning-module imports. |
| Split into additional model, numeric, lock, and checkpoint-codec modules | Deferred. The proposed five extracted modules fit the required limits without fragmenting the risk model further. |

## Impacted files and components

Modified:

- [src/risk/aggregator.py](/Users/ohayotaro/claude-finance/src/risk/aggregator.py)
- [src/risk/ledger.py](/Users/ohayotaro/claude-finance/src/risk/ledger.py)
- [tests/test_risk/test_aggregator.py](/Users/ohayotaro/claude-finance/tests/test_risk/test_aggregator.py)
- [tests/test_risk/test_ledger.py](/Users/ohayotaro/claude-finance/tests/test_risk/test_ledger.py)
- [.claude/docs/DESIGN.md](/Users/ohayotaro/claude-finance/.claude/docs/DESIGN.md)

Created during implementation:

- `src/risk/config.py`
- `src/risk/observations.py`
- `src/risk/accounting.py`
- `src/risk/persistence.py`
- `src/risk/publication.py`
- `tests/test_risk/_aggregator_support.py`
- `tests/test_risk/test_config.py`
- `tests/test_risk/test_observations.py`
- `tests/test_risk/test_accounting.py`
- `tests/test_risk/test_persistence.py`
- `tests/test_risk/test_publication.py`
- `.claude/tasks/risk-ledger-accounting-002/implementation-result.md`

No change is planned for `config/risk_groups.toml`; its task-001 contents remain binding.

Explicitly untouched:

- `src/orchestrator/registry.py`
- `src/bot/`
- `.claude/hooks/`
- `.claude/scripts/`
- `scripts/update.py`
- `config/registry.toml`
- `pyproject.toml`
- `uv.lock`
- Existing task state, review, stderr, and event artifacts

## Implementation sequence

1. Obtain explicit PM and user approval for this T3 implementation.
2. Recheck `git status` and preserve a read-only snapshot of the current test inventory and relevant source files outside the repository.
3. Export `UV_OFFLINE=1`. If the existing environment cannot run without downloading, stop and report `BLOCKED`.
4. Record the task-001 baseline: 332 fast cases and 163 risk cases, plus exact collected node IDs and function names.
5. Add the five Part A test functions to the unsplit suite and run them failing-first.
6. Implement atomic ledger metadata, staged checkpoint semantic validation, current-config cap validation, and fixture corrections.
7. Route all named startup refusals through the shared fail-closed publication path.
8. Add byte-offset logging for malformed records.
9. Run all Part A tests, the complete risk suite, and the fast suite before decomposition.
10. Extract `config.py`, then `observations.py`, `accounting.py`, `persistence.py`, and `publication.py` in dependency order. Leave only orchestration, CLI, and compatibility re-exports in `aggregator.py`.
11. After each extraction, run the owning targeted test group and verify that no extracted module imports `aggregator.py`.
12. Split the test module mechanically, retaining function names and assertions. Record every old and new node path.
13. Add structural, compatibility, and ADR tests.
14. Append the ADR-005 module-map subsection.
15. Run the complete offline validation set and collect final module line counts.
16. Write the implementation result once as a complete English ASCII artifact.
17. Run `git diff --check` last and report its exact exit code and output in the phase handoff.

## Test and validation plan

All `uv` commands will run with `UV_OFFLINE=1` already exported. No dependency installation or network fallback is allowed.

Targeted Part A tests:

```bash
uv run --extra dev pytest \
  tests/test_risk/test_persistence.py::test_checkpoint_pnl_inconsistent_with_ledger_is_rejected \
  tests/test_risk/test_persistence.py::test_checkpoint_cap_flags_inconsistent_with_pnl_are_rejected \
  tests/test_risk/test_persistence.py::test_checkpoint_save_load_roundtrip \
  tests/test_risk/test_aggregator.py::test_adapter_load_failure_publishes_fail_closed_state \
  tests/test_risk/test_aggregator.py::test_registry_failure_publishes_fail_closed_state \
  tests/test_risk/test_observations.py::test_malformed_log_warning_includes_offset -v
```

Inventory and risk tests:

```bash
uv run --extra dev pytest tests/test_risk/ --collect-only -q
uv run --extra dev pytest tests/test_risk/ -v
uv run --extra dev pytest -m "not integration and not slow"
```

Required quality gates:

```bash
uv run --extra dev ruff check src/ tests/ .claude/hooks/ .claude/scripts/
uv run --extra dev mypy src/ .claude/scripts/
uv run python -m src.orchestrator.registry audit
```

Structural checks:

```bash
wc -l src/risk/aggregator.py src/risk/config.py src/risk/observations.py src/risk/accounting.py src/risk/persistence.py src/risk/publication.py src/risk/ledger.py
rg -n 'from .*aggregator import|import src\\.risk\\.aggregator' src/risk/ --glob '*.py' --glob '!aggregator.py'
uv run python -m src.risk.aggregator --help
rg -n '[^\\x00-\\x7F]' .claude/tasks/risk-ledger-accounting-002/implementation-result.md
```

The dependency search must produce no matches. The ASCII search must also produce no matches. Review of the test diff must show only moves, import/monkeypatch target changes, ledger-consistent fixture changes, and newly added assertions.

Final command:

```bash
git diff --check
```

## Risks and blockers

- T3 implementation approval is the current blocker. Task-001 approval does not authorize task-002 implementation.
- A configuration threshold change can make old persisted cap flags semantically inconsistent. Per the brief, this intentionally rejects the checkpoint and starts fail closed.
- Semantic recomputation is possible only when the checkpoint cursor/generation still matches the ledger. The accepted ledger-ahead crash path remains fail closed because historical generation metadata is unavailable.
- Ledger mutation during restoration is guarded by the writer lock and by metadata reads before and after PnL queries. A detected change is a startup refusal.
- Refactoring may break monkeypatches that target `src.risk.aggregator` globals. Tests will target the owning module while compatibility re-exports preserve public imports.
- A filesystem failure may prevent replacement of an earlier state file. The process will log CRITICAL and exit non-zero; it will not claim a successful fail-closed publication.
- The persistence module has the tightest line budget. Staged decoding and removal of partial-state reset duplication are required to keep it below 900 lines without deleting migration behavior.
- No real venue adapter validates normalized venue PnL, cursor completeness, or timestamp behavior. This remains an accepted residual risk.
- Mark-price exposure, ledger retention/compaction, multi-currency conversion, shared-account cash allocation, and cross-machine locking remain out of scope.
- No network access or new dependency is required. If the existing local tool environment is incomplete, implementation must report `BLOCKED`.

## Acceptance-criteria mapping

| AC | Planned evidence |
|---|---|
| AC1 | `test_checkpoint_pnl_inconsistent_with_ledger_is_rejected`, `test_checkpoint_cap_flags_inconsistent_with_pnl_are_rejected`, `test_checkpoint_save_load_roundtrip`, and `test_ledger_metadata_snapshot_binds_cursor_generation_and_as_of`. |
| AC2 | `test_adapter_load_failure_publishes_fail_closed_state` and parameterized `test_registry_failure_publishes_fail_closed_state`, with prior healthy-file replacement asserted. |
| AC3 | `test_malformed_log_warning_includes_offset`, asserting an exact absolute byte offset and strategy ID. |
| AC4 | `test_aggregator_module_boundaries_are_bounded_and_inward`, `test_aggregator_public_reexports_remain_available`, recorded `wc -l` output, and a zero-match inward-dependency search. |
| AC5 | Baseline 332 fast/163 risk inventory, pre/post collection output, a complete old-path to new-path list, unchanged function names, assertion-diff review, and full risk/fast suite results. |
| AC6 | The four exact required `uv` commands, registry audit, and final `git diff --check`, all offline. |
| AC7 | `test_adr_005_documents_aggregator_module_map`, the appended ADR-005 section, ASCII verification, one whole-file implementation-result write, exact line counts, and an AC table containing only exact test function names. |