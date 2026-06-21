#!/usr/bin/env python3
"""Block Claude source/config writes outside PM orchestration paths."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ALLOWED_RELATIVE_DIRS = (
    ".claude/tasks",
    ".claude/checkpoints",
    ".claude/plans",
    ".claude/state",
    ".claude/docs/reviews",
)
ALLOWED_ROOT_FILES = ("README.md", "CLAUDE.md")


def is_within(child: Path, parent: Path) -> bool:
    """Return whether child resolves inside parent."""

    try:
        return os.path.commonpath([str(child), str(parent)]) == str(parent)
    except ValueError:
        return False


def resolve_target(file_path: str, project_dir: Path) -> Path:
    """Resolve a Claude tool file path against the project root."""

    raw = Path(file_path)
    if raw.is_absolute():
        return raw.resolve()
    return (project_dir / raw).resolve()


def is_allowed_path(file_path: str, project_dir: Path) -> tuple[bool, str]:
    """Return allow/block decision and reason for a target write path."""

    project_root = project_dir.resolve()
    target = resolve_target(file_path, project_root)
    if not is_within(target, project_root):
        return False, f"Path traversal or outside-project write blocked: {target}"

    relative_target = target.relative_to(project_root)
    if relative_target in (Path(file_name) for file_name in ALLOWED_ROOT_FILES):
        return True, "Allowed: PM root documentation file"

    for relative_dir in ALLOWED_RELATIVE_DIRS:
        allowed_root = (project_root / relative_dir).resolve()
        if is_within(target, allowed_root):
            return True, f"Allowed PM orchestration path: {relative_dir}"

    allowed = ", ".join(ALLOWED_RELATIVE_DIRS)
    return (
        False,
        "Claude source/config writes are blocked by default. Create or update a "
        "canonical task brief and delegate technical work through "
        "`.claude/scripts/codex_handoff.py`. Allowed write roots: "
        f"{allowed}",
    )


def main() -> int:
    """Claude Code PreToolUse entry point."""

    raw = sys.stdin.read()
    if not raw.strip():
        return 0

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return 0

    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")
    if not file_path:
        return 0

    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", "."))
    allowed, reason = is_allowed_path(file_path, project_dir)
    if allowed:
        return 0

    print(f"BLOCKED: {reason}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
