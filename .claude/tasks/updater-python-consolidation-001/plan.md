# Plan

## Recommended design and rationale

### 1. Make `update.py` the only updater implementation

Refactor [scripts/update.py](/Users/ohayotaro/claude-finance/scripts/update.py:1) into typed, standard-library-only components for:

- Path and regular-file safety validation.
- Exact marker parsing and byte-preserving contract composition.
- DESIGN archive planning and verification.
- Private staging and recovery management.
- Template-managed path replacement.
- Enumerated updater self-update.
- Best-effort executable permissions.
- CLI orchestration and consistent error reporting.

The module docstring will reproduce the safety contract currently documented in `update.sh`: local and template contracts require exactly one full-line boundary marker of each kind in correct order; all marker checks precede downstream mutation; post-mutation failure retains recovery copies and prints their location.

The updater will retain the caller's current working directory as the downstream project root. `TEMPLATE_SOURCE_DIR` will select an offline local template; otherwise `TEMPLATE_REPO_URL` will retain the existing clone behavior. No network path will be exercised during implementation or validation.

### 2. Preserve the accepted byte semantics exactly

For both `CLAUDE.md` and `AGENTS.md`, read with `Path.read_bytes()` and split with `splitlines(keepends=True)`.

A marker matches only when the line content, after removing one recognized `LF`, `CRLF`, or `CR` terminator, equals the ASCII marker bytes. Embedded marker text remains ordinary content.

Require exactly one start marker and one repository marker in both the local and template files, with the start marker before the repository marker. Errors will name:

- The local or template file.
- The offending marker.
- The occurrence count, or the ordering violation.

Compose the staged result as:

1. Template prefix through the template start-marker line.
2. Local content between local markers, including an empty byte slice.
3. Template repository-marker line.
4. Local content after the local repository marker.

This reproduces the accepted `e40f118` slicing behavior without text decoding, newline insertion, stripping, or normalization.

### 3. Complete all preflight and staging before mutation

Use `tempfile.mkdtemp(prefix="claude-finance-update-")` and a private recovery subdirectory. Apply restrictive permissions where supported, without depending on POSIX APIs.

Before setting the mutation-started flag:

- Validate the project root, `.claude`, `CLAUDE.md`, and `AGENTS.md`.
- Resolve and validate the template root and ensure it differs from the project root.
- Validate and stage both composed contracts.
- Stage a safe local `backtest-thresholds.json`, if present.
- Compare and stage local DESIGN bytes when preservation is required.
- Validate any existing content-addressed archive.
- Validate all three incoming updater files and their downstream target paths.
- Create recovery copies for every path that may be mutated, including the three root `scripts/` files.
- Record originally absent paths for recovery.

On success, remove the temporary directory. On failure before mutation, remove it. On failure after mutation begins, retain it and print the exact recovery directory to stderr.

### 4. Port content-addressed DESIGN preservation

Use `hashlib.sha256` over the exact local DESIGN bytes and the accepted name:

`DESIGN.local-preserved.sha256-<full-hexdigest>.md`

Semantics will match `e40f118`:

- If local and template DESIGN files are identical, create no archive.
- If different, stage the local bytes.
- If the digest archive does not exist, create it without overwriting another path.
- If it already exists as a safe regular file with identical bytes, reuse it.
- If it is a symlink, non-file, or contains different bytes, fail before replacing DESIGN.
- Verify archive bytes after creation.
- Never overwrite or remove `DESIGN.local-preserved.md`.

### 5. Preserve the remaining accepted updater behavior

Port the existing behavior for:

- Removing `.claude/agents`, `.claude/routing-keywords.json`, and `.gemini`.
- Replacing template-managed `.claude/hooks`, `.claude/rules`, `.claude/skills`, and `.claude/scripts` only when the corresponding template directory exists.
- Copying the enumerated template-managed `.claude` files when present.
- Replacing staged root contracts.
- Replacing `.codex` when supplied by the template.
- Restoring a staged local `backtest-thresholds.json`.
- Applying executable bits to template Python scripts on a best-effort basis.

Permission changes will catch unsupported-platform and filesystem errors silently. No updater correctness will depend on chmod succeeding.

### 6. Self-update exactly three root scripts

Define one explicit tuple:

- `scripts/update.py`
- `scripts/update.sh`
- `scripts/validate_update_preservation.sh`

Require safe regular template copies, then replace only those files late in the mutation sequence. Never remove or copy the entire root `scripts/` directory. Existing project-owned scripts and subdirectories remain untouched.

Copy ordering will be:

1. `scripts/update.py`
2. `scripts/validate_update_preservation.sh`
3. `scripts/update.sh`

This is safe while updating:

- Python has already read and compiled the running module before mutation begins.
- The shell wrapper uses `exec`, so it is no longer executing when Python performs replacements.
- Copying the wrapper last leaves the old wrapper pointing to a usable Python entry point if an earlier self-update step fails.
- Recovery copies cover partial replacement failures.

### 7. Reduce `update.sh` to interpreter resolution and delegation

Replace [scripts/update.sh](/Users/ohayotaro/claude-finance/scripts/update.sh:1) with a Bash 3.2-compatible wrapper that:

- Resolves its sibling `update.py` without changing the caller's working directory.
- Tries `python3`, then `python`, accepting only Python 3.11 or newer.
- Uses direct Python deliberately because the updater is standard-library-only and should not trigger dependency synchronization or downloads.
- Fails with a clear message if no supported interpreter exists.
- Uses `exec` and forwards all arguments.
- Inherits `TEMPLATE_SOURCE_DIR`, `TEMPLATE_REPO_URL`, and the rest of the environment unchanged.

A direct interpreter is preferred over `uv run` for this entry point because no project environment is required and offline execution is more predictable. Users may still invoke `uv run python scripts/update.py` directly.

### 8. Retain and extend the Bash preservation validator

Keep [scripts/validate_update_preservation.sh](/Users/ohayotaro/claude-finance/scripts/validate_update_preservation.sh:1) rather than introducing a second validator language or filename.

Extend it to:

- Remain Bash 3.2-compatible, self-contained, fail-fast, and re-runnable.
- Create all fixtures under a private temporary directory.
- Set `TEMPLATE_SOURCE_DIR` for every updater execution.
- Keep the failing `git` shim so an attempted clone proves validation failure.
- Exercise `update.py` directly for the full hardened scenario set.
- Exercise `update.sh` end-to-end on an independent equivalent fixture.
- Compare direct and wrapper results byte-for-byte.
- Keep explicit golden contract and archive outcomes derived from `e40f118`.
- Cover empty sections, embedded marker prose, mixed line endings, and missing final newlines.
- Cover missing, duplicate, and misordered markers across local/template and CLAUDE/AGENTS inputs.
- Assert errors identify the file and marker.
- Snapshot the downstream fixture and assert complete project-tree equality after every preflight rejection.
- Verify two-run DESIGN deduplication, existing archive verification, and legacy archive preservation.
- Verify the three updater files are copied exactly and a project-owned decoy under `scripts/` is unchanged.

Retaining Bash avoids an unnecessary validator rewrite and preserves the existing stable validator filename that must itself be distributed.

### 9. Rework automated updater tests

Restructure [tests/test_orchestration/test_update_script.py](/Users/ohayotaro/claude-finance/tests/test_orchestration/test_update_script.py:1) around shared fixture and invocation helpers.

Parameterize the hardened success cases over:

- Direct Python entry point.
- Shell wrapper when Bash is available.

Assertions will cover:

- Exact contract bytes, including Zone B/project section and post-boundary content.
- Empty preserved sections.
- Content-addressed DESIGN naming and bytes.
- Two-run archive reuse.
- Legacy archive immutability.
- Preserved thresholds and non-template-managed `.claude` state.
- Legacy path migration.
- Exact self-updater replacement.
- Survival of a project-owned `scripts/decoy` file.

Add parameterized rejection cases for missing, duplicate, and misordered markers in local and template CLAUDE/AGENTS files. Each case will require a non-zero exit, file and marker diagnostics, and an unchanged downstream snapshot.

Add a focused post-mutation failure test by injecting a late replacement failure into the structured Python implementation. It will assert that recovery material remains, its path is printed, and original protected files exist in recovery storage.

Remove the fixed `DESIGN.local-preserved.md` expectation for Python.

### 10. Update README documentation

Update [README.md](/Users/ohayotaro/claude-finance/README.md:156) and its updater section to describe:

- One Python updater implementation.
- Direct invocation with `uv run python scripts/update.py` or a supported bare Python interpreter.
- `scripts/update.sh` as a stable delegating entry point.
- Automatic self-update of the three enumerated updater/validator files.
- Zone C/post-boundary and content-addressed DESIGN preservation.
- `TEMPLATE_SOURCE_DIR` for offline/local-template operation.

Remove the remote `bash <(curl ...)` example because a thin wrapper cannot operate without its sibling `update.py`. No statement will imply two independent updater implementations.

## Alternatives considered

- Keep both complete implementations: rejected because it preserves the drift class this task removes.
- Remove `update.sh`: rejected because it is a required stable entry point.
- Make `update.sh` a symlink: rejected because symlink handling is less portable and does not provide interpreter/version diagnostics.
- Prefer `uv run python` in the wrapper: rejected because the updater needs no installed dependencies and direct Python avoids unintended environment synchronization or downloads.
- Convert the validator to Python: viable, but it creates filename migration concerns and adds rewrite risk without improving the updater's single-source-of-truth property.
- Keep only expected-text assertions: rejected because paired direct/wrapper fixtures and byte comparisons provide stronger parity evidence.
- Copy the entire root `scripts/` directory: rejected because downstream validation and operational scripts are project-owned.
- Use fixed or timestamped DESIGN archives: rejected because they lack the accepted deterministic reuse and collision-verification semantics.
- Add POSIX locking with `fcntl`: rejected by the cross-platform constraint. Concurrent updater execution remains unsupported and documented as a residual risk.

## Impacted files and components

Planned modifications:

- [scripts/update.py](/Users/ohayotaro/claude-finance/scripts/update.py:1)
- [scripts/update.sh](/Users/ohayotaro/claude-finance/scripts/update.sh:1)
- [scripts/validate_update_preservation.sh](/Users/ohayotaro/claude-finance/scripts/validate_update_preservation.sh:1)
- [tests/test_orchestration/test_update_script.py](/Users/ohayotaro/claude-finance/tests/test_orchestration/test_update_script.py:1)
- [README.md](/Users/ohayotaro/claude-finance/README.md:156)

Explicitly untouched:

- `src/`
- `config/`
- `.claude/hooks/`
- `.claude/scripts/codex_handoff.py`
- `.gitignore`
- `.claude/state/` and `.claude/logs/` policies
- Downstream repositories
- Git history and index

The existing untracked `.claude/tasks/updater-python-consolidation-001/` directory will be preserved.

## Implementation sequence

1. Obtain Claude PM approval for this T2 plan.
2. Recheck worktree status and isolate the five approved files from unrelated changes.
3. Refactor `update.py` into typed validation, staging, recovery, mutation, self-update, and cleanup helpers.
4. Port the exact `e40f118` contract and DESIGN semantics.
5. Add enumerated self-update preflight, recovery, replacement, and verification.
6. Replace `update.sh` with the interpreter-resolving `exec` wrapper.
7. Extend the persistent validator for direct Python, wrapper parity, marker failures, archive behavior, and scripts scoping.
8. Rework the pytest fixture suite around both entry points and the hardened expectations.
9. Update README instructions and remove the incompatible remote-wrapper example.
10. Run only fixture-based updater executions, followed by static checks and the full offline validation suite.
11. Record exact outputs and AC evidence in the implementation result.
12. Submit the complete T2 change for independent read-only review before PM acceptance.

## Test and validation plan

Run focused checks first:

```bash
uv run --extra dev pytest tests/test_orchestration/test_update_script.py
bash scripts/validate_update_preservation.sh
```

Run required regression checks:

```bash
uv run --extra dev pytest -m "not integration and not slow"
uv run --extra dev ruff check src/ tests/ .claude/hooks/ .claude/scripts/ scripts/update.py
uv run --extra dev mypy src/ .claude/scripts/ scripts/update.py
bash -n scripts/update.sh scripts/validate_update_preservation.sh
shellcheck scripts/update.sh scripts/validate_update_preservation.sh
```

Produce AC5 static evidence:

```bash
if rg -n 'fcntl|os\.fork|(^|[^[:alnum:]_])(pwd|grp)([^[:alnum:]_]|$)|signal|SIG[A-Z_]+' scripts/update.py; then
  exit 1
fi
```

Also review every `update.py` import against the Python 3.11 standard library and verify that path manipulation uses `pathlib`.

Produce self-update and scope evidence through both pytest and the validator:

- Exact bytes of all three copied updater files equal the template versions.
- A downstream decoy script retains its original bytes.
- No other root `scripts/` path is added, removed, or changed.

Produce equivalence evidence:

- Golden CLAUDE, AGENTS, and DESIGN archive bytes match the accepted `e40f118` outcomes.
- Direct Python and wrapper fixture output manifests are identical.
- The validator prints a single final PASS result only after both entry points complete.

Finish with repository hygiene checks:

```bash
git diff --check
git status --short
git diff --name-only
rg -n -i 'independent updaters|two updaters|update\.py.*update\.sh.*implementation|update\.sh.*update\.py.*implementation' README.md scripts
```

No updater will be run with the repository root as its working directory. If any `uv` command attempts a download or other network access, validation stops and implementation is reported `BLOCKED`.

## Risks and blockers

- Multi-file updates cannot be fully atomic. Staging protected data first and retaining private recovery copies limits loss, but recovery after a late failure remains manual.
- Concurrent updater runs are not serialized because cross-platform POSIX locking is forbidden. Concurrent execution is unsupported and remains a residual operational risk.
- A local template source could be modified concurrently between inspection and copying. Critical contracts, DESIGN content, thresholds, and updater files are staged before mutation, reducing the highest-impact TOCTOU exposure; complete source-tree transactionality is outside the accepted semantics.
- Content-addressed archives intentionally accumulate for genuinely different local DESIGN revisions.
- Existing malformed downstream contracts will stop updating until their markers are repaired. This is intentional fail-closed behavior.
- The Bash wrapper and validator require Bash; Windows users must invoke `update.py` directly.
- Windows compliance can only be established by standard-library construction, forbidden-API checks, and review. Lack of Windows execution remains the required residual risk.
- The README remote one-file wrapper invocation must be removed because it is incompatible with sibling delegation.
- No technical blocker is currently identified. Implementation remains gated on Claude PM approval and must remain fully offline.

## Acceptance-criteria mapping

| Criterion | Planned evidence |
|---|---|
| AC1 | Exact byte-slice port in `update.py`; golden validator fixtures for CLAUDE, AGENTS, mixed endings, empty sections, and DESIGN archives; direct Python outcomes compared with accepted expected bytes. |
| AC2 | `update.sh` contains only interpreter resolution and `exec`; independent wrapper fixture produces the same output manifest as direct Python. |
| AC3 | Parameterized local/template and CLAUDE/AGENTS missing, duplicate, and misordered cases; embedded prose succeeds; every rejection names file and marker, exits non-zero, and leaves the project snapshot unchanged. |
| AC4 | Explicit three-file self-update tuple, safe target preflight, late ordered replacement, exact-byte assertions, and an unchanged project-owned decoy under `scripts/`. |
| AC5 | Standard-library import review, `pathlib` paths, forbidden-API grep, and no `fcntl`, fork, account database, or signal-dependent logic. |
| AC6 | Reworked updater tests for both entry points plus the full offline fast suite. |
| AC7 | Exact required ruff and mypy commands, strict annotations/docstrings, plus `bash -n` and shellcheck for both touched shell files. |
| AC8 | Persistent offline Bash validator always uses `TEMPLATE_SOURCE_DIR`, blocks `git clone`, runs Python directly and the wrapper, and fails fast. |
| AC9 | README presents one implementation with two entry points, documents self-update, and removes the incompatible remote one-file wrapper command and any dual-implementation wording. |