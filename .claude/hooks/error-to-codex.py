#!/usr/bin/env python3
"""PostToolUse hook (Bash): Detect error patterns in command output and add a
short debugging reminder.

Validation and orchestration commands (pytest, ruff, mypy, the registry audit,
the Codex runner) are skipped: their failures are already the subject of the
current work, so an advisory there is noise. A command is skipped only when
every non-trivial shell segment executes one of those programs.

Can be run standalone (reads JSON from stdin) or imported by the dispatcher
via handle(payload).
"""
from __future__ import annotations

import json
import os
import re
import shlex
import sys
from typing import Any

# Commands to ignore (trivial or read-only, unlikely to need debugging)
IGNORE_COMMANDS = [
    "git ", "ls ", "cd ", "pwd", "echo ", "cat ", "head ", "tail ",
    "which ", "mkdir ", "touch ", "cp ", "mv ",
    "grep ", "rg ", "find ", "wc ", "sed ", "awk ", "diff ",
]

# Validation and orchestration commands are identified by the program each
# shell segment executes (after unwrapping env assignments and `uv run`), never
# by substrings of its arguments.
VALIDATION_PROGRAMS = frozenset({"pytest", "ruff", "mypy"})
VALIDATION_MODULES = frozenset({"pytest", "ruff", "mypy", "src.orchestrator.registry"})
VALIDATION_SCRIPTS = frozenset({"codex_handoff.py"})
TRIVIAL_PROGRAMS = frozenset(prefix.strip() for prefix in IGNORE_COMMANDS)
# Shell control operators that end a command segment, as produced by a
# quote-aware shlex lexer; `&` inside quotes stays part of its argument.
SEGMENT_OPERATORS = frozenset({"&&", "||", ";", ";;", "|", "|&", "&"})
# Redirection operators; the following token is a redirect target, not an argument.
REDIRECT_OPERATORS = frozenset({">", ">>", "<", "<<", "<<<", ">&", "<&", "&>", "&>>", ">|"})
UV_RUN_VALUE_FLAGS = frozenset(
    {"--extra", "--with", "--python", "-p", "--project", "--directory", "--group", "--package"}
)
PYTHON_PROGRAMS = frozenset({"python", "python3"})

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


# Redact likely secrets before text enters model context. The 48-char
# threshold on the base64-ish blob pattern avoids scrubbing 40-char git
# SHA-1 hashes while still catching typical 64-char exchange API keys.
_SECRET_PATTERNS = [
    (re.compile(
        r"(?i)\b([A-Z0-9_]*(?:KEY|SECRET|TOKEN|PASSWORD|PASSWD|CREDENTIAL"
        r"|AUTH)[A-Z0-9_]*)\s*=\s*\S+"
    ), r"\1=***"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]+=*"), "Bearer ***"),
    (re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9]{16,}\b"), "***"),
    (re.compile(r"\b[A-Za-z0-9+/]{48,}={0,2}\b"), "***"),
]


def _scrub(text: str) -> str:
    """Redact secret-looking substrings from text."""
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def command_segments(command: str) -> list[list[str]]:
    """Split a shell command into token lists at control operators, honoring quotes."""

    segments: list[list[str]] = []
    for line in command.splitlines():
        lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        try:
            tokens = list(lexer)
        except ValueError:
            tokens = line.split()
        current: list[str] = []
        skip_target = False
        for token in tokens:
            if skip_target:
                skip_target = False
                continue
            if token in SEGMENT_OPERATORS:
                segments.append(current)
                current = []
            elif token in REDIRECT_OPERATORS:
                skip_target = True
            else:
                current.append(token)
        segments.append(current)
    return segments


def _segment_program(tokens: list[str]) -> tuple[str, list[str]] | None:
    """Return the executed program basename and its arguments for one segment."""

    while tokens and "=" in tokens[0] and not tokens[0].startswith(("-", "/")):
        tokens = tokens[1:]
    if not tokens:
        return None
    program, args = os.path.basename(tokens[0]), tokens[1:]
    if program == "uv" and args[:1] == ["run"]:
        index = 1
        while index < len(args) and args[index].startswith("-"):
            index += 2 if args[index] in UV_RUN_VALUE_FLAGS else 1
        if index >= len(args):
            return None
        program, args = os.path.basename(args[index]), args[index + 1 :]
    return program, args


def _is_validation_segment(program: str, args: list[str]) -> bool:
    if program in VALIDATION_PROGRAMS:
        return True
    if program in PYTHON_PROGRAMS and args:
        if args[0] == "-m" and len(args) > 1:
            return args[1] in VALIDATION_MODULES
        return os.path.basename(args[0]) in VALIDATION_SCRIPTS
    return False


def is_validation_command(command: str) -> bool:
    """Return True when every non-trivial segment runs a validation program.

    `cd repo && pytest` counts as validation; `python scripts/x.py --input
    reports/pytest.json` does not, because the executed program is a script.
    """

    found = False
    for segment in command_segments(command):
        parsed = _segment_program(segment)
        if parsed is None:
            continue
        program, args = parsed
        if program in TRIVIAL_PROGRAMS:
            continue
        if not _is_validation_segment(program, args):
            return False
        found = True
    return found


def handle(data: dict[str, Any]) -> str | None:
    """Process a parsed PostToolUse payload.

    Returns additionalContext string if errors detected, None otherwise.
    Called by the consolidated dispatcher or by main() for standalone use.
    """
    tool_input = data.get("tool_input", {})
    command = tool_input.get("command", "")

    # Skip trivial commands
    if any(command.startswith(prefix) for prefix in IGNORE_COMMANDS):
        return None
    if is_validation_command(command):
        return None

    # Claude Code emits the tool result as "tool_response"; accept the
    # legacy "tool_output" key as a fallback for direct invocation.
    tool_output = data.get("tool_response") or data.get("tool_output") or {}
    if not isinstance(tool_output, dict):
        tool_output = {}
    stdout = tool_output.get("stdout", "")
    stderr = tool_output.get("stderr", "")
    output = f"{stdout}\n{stderr}"

    if len(output.strip()) < 10:
        return None

    detected = []
    for pattern, label in ERROR_PATTERNS:
        if re.search(pattern, output, re.IGNORECASE):
            detected.append(label)

    if not detected:
        return None

    # Truncate output for context (first 500 chars), scrub secrets
    error_snippet = _scrub(output[:500].strip())
    command = _scrub(command)
    error_types = ", ".join(set(detected))

    context = (
        f"ERROR DETECTED ({error_types}):\n"
        f"Command: `{command}`\n"
        f"```\n{error_snippet}\n```\n"
        "Fix the root cause and add a regression test. For T2/T3 work, record the "
        "failing command evidence in the task brief so the Codex review can check it."
    )

    return context


def main() -> None:
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
