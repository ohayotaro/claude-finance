#!/usr/bin/env python3
"""PostToolUse hook (Bash): Log Codex CLI metadata to
.claude/logs/cli-tools.jsonl for session tracking and analytics.

Can be run standalone (reads JSON from stdin) or imported by the dispatcher
via handle(payload).
"""
from __future__ import annotations

import hashlib
import json
import os
import shlex
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

TRACKED_COMMAND = "codex"


def _log_file() -> Path:
    return Path(os.environ.get("CLAUDE_PROJECT_DIR", ".")) / ".claude" / "logs" / "cli-tools.jsonl"


def _command_metadata(command: str) -> dict[str, str] | None:
    try:
        parts = shlex.split(command)
    except ValueError:
        parts = command.split()
    if TRACKED_COMMAND not in [os.path.basename(part) for part in parts]:
        return None

    codex_index = next(
        index for index, part in enumerate(parts) if os.path.basename(part) == TRACKED_COMMAND
    )
    mode = "unknown"
    for token in parts[codex_index + 1 :]:
        if token.startswith("-"):
            continue
        mode = token
        break
    return {"tool": TRACKED_COMMAND, "mode": mode}


def _stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def handle(data: dict[str, Any]) -> None:
    """Process a parsed PostToolUse payload.

    Logs CLI tool usage to JSONL file. Always returns None (no advisory output).
    Called by the consolidated dispatcher or by main() for standalone use.
    """
    tool_input = data.get("tool_input", {})
    command = tool_input.get("command", "")

    metadata = _command_metadata(command)
    if metadata is None:
        return None

    # Claude Code emits the tool result as "tool_response"; accept the
    # legacy "tool_output" key as a fallback for direct invocation.
    tool_output = data.get("tool_response") or data.get("tool_output") or {}
    if not isinstance(tool_output, dict):
        tool_output = {}
    stdout = str(tool_output.get("stdout", ""))
    stderr = str(tool_output.get("stderr", ""))
    exit_code = tool_output.get("exit_code")

    log_entry = {
        "timestamp": datetime.now(UTC).isoformat(),
        "tool": metadata["tool"],
        "mode": metadata["mode"],
        "exit_code": exit_code,
        "output_length": len(stdout),
        "stderr_length": len(stderr),
        "session_id_hash": _stable_hash(str(data.get("session_id", ""))),
    }

    try:
        log_file = _log_file()
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with log_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry) + "\n")
    except OSError:
        pass  # Do not fail the hook on logging errors

    return None


def main() -> None:
    """Standalone entry point: read JSON from stdin, run handle(), exit."""
    raw = sys.stdin.read()
    if not raw.strip():
        sys.exit(0)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        sys.exit(0)

    handle(data)
    sys.exit(0)


if __name__ == "__main__":
    main()
