Status: PASS

Summary: Implemented mixed-ownership `.codex` updates, preserve-local `DESIGN.md`, and self-updating updater tests. All updater execution was limited to offline temporary fixtures.

Files changed:

- [scripts/update.py](/Users/ohayotaro/claude-finance/scripts/update.py)
- [scripts/validate_update_preservation.sh](/Users/ohayotaro/claude-finance/scripts/validate_update_preservation.sh)
- [tests/test_orchestration/test_update_script.py](/Users/ohayotaro/claude-finance/tests/test_orchestration/test_update_script.py)
- [README.md](/Users/ohayotaro/claude-finance/README.md)

Material decisions:

- Template `.codex` files are recursively preflighted, staged, recovery-backed, then overlaid file-by-file; unmanaged downstream paths are untouched.
- `DESIGN.md` is copied only when absent; existing `DESIGN.local-preserved*` files are never managed.
- `SELF_UPDATE_PATHS` now includes the updater test, with fail-closed validation of existing parent directories.

Validation results:

- `bash scripts/validate_update_preservation.sh` -> `PASS: Python updater and shell wrapper preservation fixtures passed.`
- `UV_CACHE_DIR=/private/tmp/updater-uv-cache uv run --offline --extra dev pytest -m "not integration and not slow"` -> `215 passed`
- `UV_CACHE_DIR=/private/tmp/updater-uv-cache uv run --offline --extra dev ruff check src/ tests/ .claude/hooks/ .claude/scripts/ scripts/update.py` -> passed
- `UV_CACHE_DIR=/private/tmp/updater-uv-cache uv run --offline --extra dev mypy src/ .claude/scripts/ scripts/update.py` -> passed
- `bash -n scripts/validate_update_preservation.sh scripts/update.sh` -> passed
- `shellcheck scripts/validate_update_preservation.sh scripts/update.sh` -> passed
- `git diff --check` -> passed

The unmodified `uv run` invocation could not access the host default cache; the writable temporary cache plus `--offline` was used to satisfy the no-network constraint.

Acceptance criteria:

- AC1-AC2: Python and shell fixtures verify `.codex/plans/decoy.md` preservation, config replacement, and no-template `.codex` no-op.
- AC3: Full preservation validator and updater tests pass.
- AC4: Full fast suite, Ruff, mypy, Bash syntax, and ShellCheck pass.
- AC5: Module contract and README describe mixed `.codex` ownership.
- AC6-AC7: Fixtures cover local `DESIGN.md` preservation/scaffolding and legacy archive survival; updater executable code has no archive-management path.
- AC8: Fixtures verify updater-test replacement and preservation of a project-owned `tests/` decoy; README lists all four support files.

Residual risks: Existing updater-wide non-atomic mutation and TOCTOU limitations remain, with recovery copies retained on late failure. No financial, trading, network, credential, Git-state, or downstream-repository actions were performed.