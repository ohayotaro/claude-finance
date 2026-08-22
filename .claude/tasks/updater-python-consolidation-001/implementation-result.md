Status: PASS

Summary: Added F3 interpreter resolution to both shell entry points. They now try `UPDATER_PYTHON`, standard/versioned Python commands, then offline `uv python find '>=3.11'`. README documents this behavior.

Files changed:

- [README.md](/Users/ohayotaro/claude-finance/README.md)
- [scripts/update.sh](/Users/ohayotaro/claude-finance/scripts/update.sh)
- [scripts/validate_update_preservation.sh](/Users/ohayotaro/claude-finance/scripts/validate_update_preservation.sh)

The existing task worktree also contains the approved updater port and tests in `scripts/update.py` and `tests/test_orchestration/test_update_script.py`; those were preserved.

Material design decisions:

- Identical Bash 3.2-compatible resolver in both scripts.
- Every interpreter candidate is version-checked for Python >=3.11.
- `uv python find` is discovery-only; no `uv run`, install, sync, or download.
- Wrapper remains delegation-only after interpreter resolution.

Validation results:

- `UV_CACHE_DIR=/private/tmp/claude-finance-uv-cache uv run --extra dev pytest tests/test_orchestration/test_update_script.py`  
  `30 passed`
- `UV_CACHE_DIR=/private/tmp/claude-finance-uv-cache uv run --extra dev pytest -m "not integration and not slow"`  
  `208 passed`
- `UV_CACHE_DIR=/private/tmp/claude-finance-uv-cache uv run --extra dev ruff check src/ tests/ .claude/hooks/ .claude/scripts/ scripts/update.py`  
  `All checks passed!`
- `UV_CACHE_DIR=/private/tmp/claude-finance-uv-cache uv run --extra dev mypy src/ .claude/scripts/ scripts/update.py`  
  `Success: no issues found in 14 source files`
- `bash -n scripts/update.sh scripts/validate_update_preservation.sh && shellcheck ...`  
  Passed.
- `bash scripts/validate_update_preservation.sh`  
  `PASS: Python updater and shell wrapper preservation fixtures passed.`
- Workspace evidence: `python3` is `3.9.6`; the validator still passed by selecting a supported fallback. `UV_CACHE_DIR=/private/tmp/claude-finance-uv-cache uv python find '>=3.11'` returned the installed `.venv` interpreter.
- Corrected AC5 scan:

  ```bash
  if rg -n '(^|[^[:alnum:]_])(fcntl|os\.fork|pwd|grp|signal|SIG[A-Z_]+)([^[:alnum:]_]|$)' scripts/update.py; then exit 1; fi
  ```

  Result: no matches.

Acceptance criteria: AC1–AC4 and AC6–AC9 remain covered by the passing updater tests and preservation validator; AC5 passes the corrected token-bounded scan. F3 is satisfied by the shared resolver, successful end-to-end validator run with Python 3.9 rejected, and successful offline uv discovery.

Residual risks: Windows execution remains untested by design; concurrent updater runs remain unsupported. No network access, Git mutation, or repository-root updater execution occurred.