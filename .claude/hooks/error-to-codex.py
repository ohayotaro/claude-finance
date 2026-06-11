#!/usr/bin/env python3
"""PostToolUse hook (Bash): Detect error patterns in command output and suggest
routing to the codex-debugger subagent.

Can be run standalone (reads JSON from stdin) or imported by the dispatcher
via handle(payload).
"""
from __future__ import annotations

import json
import re
import sys

# Commands to ignore (trivial or read-only, unlikely to need debugging)
IGNORE_COMMANDS = [
    "git ", "ls ", "cd ", "pwd", "echo ", "cat ", "head ", "tail ",
    "which ", "mkdir ", "touch ", "cp ", "mv ",
    "grep ", "rg ", "find ", "wc ", "sed ", "awk ", "diff ",
]

# Error patterns to detect. Searched with re.IGNORECASE; use (?-i:...) for
# fragments that must stay case-sensitive. The test-failure pattern is
# deliberately narrow (pytest summary/verbose forms) -- a bare "error"
# substring match would false-positive on any output that merely mentions
# the word (grep results, docs).
ERROR_PATTERNS = [
    (r"Traceback \(most recent call last\)", "Python traceback"),
    (r"(?-i:\bFAILED\b)|\b\d+ (?:failed|error)s?\b|\bAssertionError\b",
     "Test failure"),
    (r"ModuleNotFoundError|ImportError", "Import error"),
    (r"TypeError|ValueError|KeyError|AttributeError", "Python runtime error"),
    (r"SyntaxError", "Syntax error"),
    (r"error\[E\d+\]", "MQL5 compilation error"),
    (r"ConnectionError|TimeoutError|HTTPError", "Network/API error"),
    (r"PermissionError|FileNotFoundError|OSError", "System error"),
    (r"panic:|SIGABRT|SIGSEGV|core dumped", "Crash"),
    (r"npm ERR!|yarn error", "Node.js package error"),
]


def handle(data):
    """Process a parsed PostToolUse payload.

    Returns additionalContext string if errors detected, None otherwise.
    Called by the consolidated dispatcher or by main() for standalone use.
    """
    tool_input = data.get("tool_input", {})
    command = tool_input.get("command", "")

    # Skip trivial commands
    if any(command.startswith(prefix) for prefix in IGNORE_COMMANDS):
        return None

    # Claude Code emits the tool result as "tool_response"; accept the
    # legacy "tool_output" key as a fallback for direct invocation.
    tool_output = data.get("tool_response") or data.get("tool_output") or {}
    if not isinstance(tool_output, dict):
        tool_output = {}
    stdout = tool_output.get("stdout", "")
    stderr = tool_output.get("stderr", "")
    output = "%s\n%s" % (stdout, stderr)

    if len(output.strip()) < 10:
        return None

    detected = []
    for pattern, label in ERROR_PATTERNS:
        if re.search(pattern, output, re.IGNORECASE):
            detected.append(label)

    if not detected:
        return None

    # Truncate output for context (first 500 chars)
    error_snippet = output[:500].strip()
    error_types = ", ".join(set(detected))

    context = (
        "ERROR DETECTED (%s):\n"
        "Command: `%s`\n"
        "```\n%s\n```\n"
        "Consider delegating to the codex-debugger subagent for root cause analysis:\n"
        "Use agent type 'codex-debugger' or run:\n"
        '`codex exec --full-auto "Debug: %s in command: %s"`'
    ) % (error_types, command, error_snippet, error_types, command)

    return context


def main():
    """Standalone entry point: read JSON from stdin, run handle(), emit result."""
    raw = sys.stdin.read()
    if not raw.strip():
        sys.exit(0)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        sys.exit(0)

    context = handle(data)
    if context is None:
        sys.exit(0)

    result = {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": context,
        }
    }
    json.dump(result, sys.stdout)


if __name__ == "__main__":
    main()
