#!/usr/bin/env python3
"""Block Claude Edit/Write on safety-gate files that require explicit user approval.

Claude implements repository changes directly. This hook protects only the
files whose modification changes a trading-safety gate or a credential:

- the live-trading gate hook and this guard itself
- `.claude/settings.json` (hook registration and the permission deny list)
- live-trading acknowledgments under `.claude/state/` (user-created only)
- `.env` credential files (`.env.example` templates stay writable)

This is a workflow guardrail for the Edit/Write tools, not a security boundary:
Bash can still write these paths. Claude changes a protected file only after the
user explicitly approves that change in the conversation, and records the
approval in the task artifacts.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

PROTECTED_FILES = (
    ".claude/hooks/live-trading-gate.py",
    ".claude/hooks/pm-write-guard.py",
    ".claude/settings.json",
)
LIVE_ACK_DIR = ".claude/state"
LIVE_ACK_PREFIX = "live-trading-"
LIVE_ACK_SUFFIX = ".ack"
ENV_TEMPLATE_SUFFIX = ".example"


def is_within(child: Path, parent: Path) -> bool:
    """Return whether child resolves inside parent."""

    try:
        return os.path.commonpath([str(child), str(parent)]) == str(parent)
    except ValueError:
        return False


def resolve_target(file_path: str, project_dir: Path) -> Path:
    """Resolve a Claude tool file path against the project root, following symlinks."""

    raw = Path(file_path)
    if raw.is_absolute():
        return raw.resolve()
    return (project_dir / raw).resolve()


def lexical_target(file_path: str, project_dir: Path) -> Path:
    """Normalize a Claude tool file path without following symlinks."""

    raw = Path(file_path)
    base = raw if raw.is_absolute() else project_dir.absolute() / raw
    return Path(os.path.normpath(base))


def candidate_relative_paths(file_path: str, project_dir: Path) -> list[Path]:
    """Return project-relative forms of the requested and the resolved target.

    Both are checked so a symlink cannot hide a protected name (a `.env` link
    to an unprotected file) or a protected destination (an alias pointing at
    the live-trading gate).
    """

    roots = {project_dir.absolute(), project_dir.resolve()}
    targets = (
        lexical_target(file_path, project_dir),
        resolve_target(file_path, project_dir.resolve()),
    )
    candidates: list[Path] = []
    for target in targets:
        for root in roots:
            relative = relative_to_casefold(target, root)
            if relative is not None:
                candidates.append(relative)
    return candidates


def relative_to_casefold(target: Path, root: Path) -> Path | None:
    """Return target relative to root, comparing path components case-insensitively.

    Case-insensitive filesystems (macOS APFS default) let a case variant of an
    ancestor directory name the same file, so containment must not be
    case-sensitive.
    """

    target_parts = target.parts
    root_parts = root.parts
    if len(target_parts) < len(root_parts):
        return None
    for index, root_part in enumerate(root_parts):
        if target_parts[index].casefold() != root_part.casefold():
            return None
    return Path(*target_parts[len(root_parts) :])


def _is_env_credential_file(name: str) -> bool:
    lowered = name.casefold()
    if lowered == ".env":
        return True
    return lowered.startswith(".env.") and not lowered.endswith(ENV_TEMPLATE_SUFFIX)


def protected_reason(relative_target: Path) -> str | None:
    """Return why a project-relative path is protected, or None when writable.

    Comparison is case-insensitive so case-folding filesystems (macOS APFS)
    cannot be used to sidestep an exact-path match.
    """

    relative = relative_target.as_posix().casefold()
    if relative in (item.casefold() for item in PROTECTED_FILES):
        return f"safety-gate file {relative_target.as_posix()}"

    parent = relative_target.parent.as_posix().casefold()
    name = relative_target.name.casefold()
    if (
        parent == LIVE_ACK_DIR.casefold()
        and name.startswith(LIVE_ACK_PREFIX)
        and name.endswith(LIVE_ACK_SUFFIX)
    ):
        return "live-trading acknowledgment (user-created only)"

    if _is_env_credential_file(relative_target.name):
        return f"credential file {relative_target.as_posix()}"
    return None


def is_allowed_path(file_path: str, project_dir: Path) -> tuple[bool, str]:
    """Return allow/block decision and reason for a target write path."""

    candidates = candidate_relative_paths(file_path, project_dir)
    if not candidates:
        return True, "Allowed: outside project; Claude Code permissions apply"

    reason = next(
        (found for found in (protected_reason(path) for path in candidates) if found),
        None,
    )
    if reason is None:
        return True, "Allowed: not a protected safety-gate path"

    return (
        False,
        f"Protected {reason}. Changing it alters a trading-safety gate or credential. "
        "Ask the user for explicit approval of this specific change first, then record "
        "the approval in the task artifacts.",
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
