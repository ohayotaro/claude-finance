Status: PASS

Summary: Updated the shell-updater regression test to expect a SHA-256 content-addressed DESIGN archive, verify no legacy fixed-name archive, and assert CLAUDE.md Zone C preservation. The Python updater test retains its legacy archive expectation.

Files changed:

- [tests/test_orchestration/test_update_script.py](/Users/ohayotaro/claude-finance/tests/test_orchestration/test_update_script.py)

Material decisions:

- Shared assertions now cover only common migration/state behavior.
- `update.sh` specifically verifies `DESIGN.local-preserved.sha256-<digest>.md`.
- `update.py` remains explicitly tested against `DESIGN.local-preserved.md`, per approved deferral.

Validation:

- `bash -n scripts/update.sh` - PASS
- `bash -n scripts/validate_update_preservation.sh` - PASS
- `shellcheck scripts/update.sh scripts/validate_update_preservation.sh` - PASS
- `bash scripts/validate_update_preservation.sh` - PASS
- Ignore-policy checks - PASS: task/checkpoint/plan paths not ignored; JSONL/state/log paths ignored by expected rules.
- `UV_CACHE_DIR=/private/tmp/claude-finance-uv-cache uv run --offline --extra dev pytest -m "not integration and not slow"` - PASS, 180 passed
- `UV_CACHE_DIR=/private/tmp/claude-finance-uv-cache uv run --offline --extra dev ruff check src/ tests/ .claude/hooks/ .claude/scripts/` - PASS
- `UV_CACHE_DIR=/private/tmp/claude-finance-uv-cache uv run --offline --extra dev mypy src/ .claude/scripts/` - PASS

Acceptance criteria mapping:

- AC1: PASS - verified ignore behavior.
- AC2: PASS - shell test now asserts Zone C; preservation validator passes.
- AC3: PASS - shell test verifies content-addressed archive content; validator passes consecutive-run coverage.
- AC4: PASS - preservation validator passes missing-marker cases.
- AC5: PASS - repository contradiction search confirms current policy; historical review references are retained as historical context.
- AC6: PASS - self-contained validator passes.
- AC7: PASS - full fast suite, ruff, and mypy pass.

Residual risk: plain `uv run` initially could not access the sandboxed `~/.cache/uv`; no download was attempted. Validation used an isolated permitted cache with `--offline`. Existing unrelated worktree changes were preserved.