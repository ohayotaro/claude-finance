#!/usr/bin/env python3
"""PostToolUse hook (Bash): Log codex and gemini CLI command usage to
.claude/logs/cli-tools.jsonl for session tracking and analytics.

Can be run standalone (reads JSON from stdin) or imported by the dispatcher
via handle(payload).
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

LOG_FILE = os.path.join(
    os.environ.get("CLAUDE_PROJECT_DIR", "."),
    ".claude", "logs", "cli-tools.jsonl",
)

TRACKED_COMMANDS = ["codex", "gemini"]


def handle(data):
    """Process a parsed PostToolUse payload.

    Logs CLI tool usage to JSONL file. Always returns None (no advisory output).
    Called by the consolidated dispatcher or by main() for standalone use.
    """
    tool_input = data.get("tool_input", {})
    command = tool_input.get("command", "")

    # Only log tracked CLI tool usage
    if not any(
        command.startswith(cmd) or (" %s " % cmd) in command
        for cmd in TRACKED_COMMANDS
    ):
        return None

    # Claude Code emits the tool result as "tool_response"; accept the
    # legacy "tool_output" key as a fallback for direct invocation.
    tool_output = data.get("tool_response") or data.get("tool_output") or {}
    if not isinstance(tool_output, dict):
        tool_output = {}
    stdout = tool_output.get("stdout", "")
    exit_code = tool_output.get("exit_code", None)

    # Determine which tool was used
    tool_name = "unknown"
    for cmd in TRACKED_COMMANDS:
        if cmd in command:
            tool_name = cmd
            break

    log_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tool": tool_name,
        "command": command[:500],  # Truncate long commands
        "exit_code": exit_code,
        "output_length": len(stdout),
        "session_id": data.get("session_id", ""),
    }

    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        with open(LOG_FILE, "a") as f:
            f.write(json.dumps(log_entry) + "\n")
    except OSError:
        pass  # Do not fail the hook on logging errors

    return None


def main():
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
