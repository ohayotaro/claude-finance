# Runner validation evidence

Executed by `codex_handoff.py` before the review, outside the Codex sandbox.

## `uv run --extra dev pytest -m 'not integration and not slow' -q`

Result: exit 0

```text
........................................................................ [ 15%]
........................................................................ [ 31%]
........................................................................ [ 46%]
........................................................................ [ 62%]
........................................................................ [ 77%]
........................................................................ [ 93%]
................................                                         [100%]
464 passed in 7.45s
```

## `uv run --extra dev ruff check src/ tests/ .claude/hooks/ .claude/scripts/`

Result: exit 0

```text
All checks passed!
```

## `uv run --extra dev mypy src/ .claude/scripts/`

Result: exit 0

```text
Success: no issues found in 19 source files
```

## `uv run python -m src.orchestrator.registry audit`

Result: exit 0

```text
audit: ok (0 strategies, 0 accounts)
```

## `git diff --check`

Result: exit 0

```text

```

## `git diff --stat -- .claude/hooks/live-trading-gate.py .claude/settings.json`

Result: exit 0

```text

```
