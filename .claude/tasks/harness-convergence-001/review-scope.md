# Delta review scope: round 3

Previous review: `review-2.md` (delta, CHANGES_REQUIRED, three blocking findings). Review these findings and regressions in the touched files only.

## Findings addressed

1. High, AC7: absolute-path case variants bypass the write guard. `.claude/hooks/pm-write-guard.py` now derives project-relative paths with `relative_to_casefold`, comparing ancestor components case-insensitively for both the lexical and the resolved target against both the absolute and the resolved project root (user-approved change). The loop avoids `zip(strict=...)` because hooks run on the system Python 3.9.
2. Medium, AC4: blockquoted fences skipped silently. `validation_fence_lines` in `.claude/scripts/codex_handoff.py` now fails closed on any blockquote line or any line containing a fence marker (```` ``` ```` or `~~~`) inside the Required Validation section that is not a recognized fence opener.
3. Medium, AC8: background `&` separator hides failures. `.claude/hooks/error-to-codex.py` now splits segments on standalone `&` after removing file-descriptor redirections (`2>&1`, `&>`, `&>>`) that are not command boundaries.

## Touched files

- `.claude/hooks/pm-write-guard.py`
- `.claude/scripts/codex_handoff.py`
- `.claude/hooks/error-to-codex.py`
- `tests/test_orchestration/test_pm_write_guard.py`
- `tests/test_orchestration/test_codex_handoff.py`
- `tests/test_hooks/test_error_to_codex.py`
