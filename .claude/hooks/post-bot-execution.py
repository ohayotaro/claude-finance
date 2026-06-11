#!/usr/bin/env python3
"""PostToolUse hook (Bash): Detect bot execution errors, connection failures,
and trading errors in bot-related commands.

Can be run standalone (reads JSON from stdin) or imported by the dispatcher
via handle(payload).
"""
from __future__ import annotations

import json
import re
import sys

BOT_COMMANDS = [
    "python src/bot", "python -m src.bot", "docker compose",
    "docker run", "systemctl", "uvicorn", "gunicorn",
]

BOT_ERROR_PATTERNS = [
    (r"ConnectionError|ConnectionRefused|ConnectionReset", "Connection failure"),
    (r"TimeoutError|ReadTimeout|ConnectTimeout", "Timeout"),
    (r"AuthenticationError|InvalidApiKey|InvalidSignature", "API authentication error"),
    (r"InsufficientBalance|InsufficientFunds", "Insufficient balance"),
    (r"OrderNotFound|InvalidOrder|OrderRejected", "Order error"),
    (r"RateLimitExceeded|DDoSProtection|ExchangeNotAvailable", "Rate limit / exchange unavailable"),
    (r"NetworkError|RequestTimeout", "Network error"),
    (r"ExchangeError|BadRequest|BadResponse", "Exchange API error"),
    (r"WebSocket.*(?:closed|error|failed|disconnect)", "WebSocket disconnection"),
    (r"position.*(?:stuck|orphan|inconsistent)", "Position inconsistency"),
]


def handle(data):
    """Process a parsed PostToolUse payload.

    Returns additionalContext string if bot errors detected, None otherwise.
    Called by the consolidated dispatcher or by main() for standalone use.
    """
    tool_input = data.get("tool_input", {})
    command = tool_input.get("command", "")

    # Only check bot-related commands
    if not any(bc in command for bc in BOT_COMMANDS):
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
    for pattern, label in BOT_ERROR_PATTERNS:
        if re.search(pattern, output, re.IGNORECASE):
            detected.append(label)

    if not detected:
        return None

    error_types = ", ".join(set(detected))
    snippet = output[:500].strip()

    # Determine severity
    critical_types = {"Insufficient balance", "Position inconsistency", "API authentication error"}
    is_critical = bool(set(detected) & critical_types)

    severity = "CRITICAL" if is_critical else "WARNING"
    if is_critical:
        action = (
            "IMMEDIATE: Consider running `/incident-response` to handle this incident.\n"
            "Check exchange status and bot logs."
        )
    else:
        action = "Monitor the situation. If persistent, use `/incident-response`."

    context = (
        "BOT %s (%s):\n"
        "Command: `%s`\n"
        "```\n%s\n```\n"
        "%s"
    ) % (severity, error_types, command, snippet, action)

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
