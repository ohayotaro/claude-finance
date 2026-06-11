#!/usr/bin/env python3
"""PostToolUse hook (Bash): Detect backtest execution commands and suggest
automatic result analysis and performance threshold checks.

Can be run standalone (reads JSON from stdin) or imported by the dispatcher
via handle(payload).

Thresholds are loaded from .claude/backtest-thresholds.json if present,
otherwise built-in defaults are used.
"""
from __future__ import annotations

import json
import os
import re
import sys

# Match actual backtest invocations, not any string containing "backtest".
# These are concrete command fragments that indicate a real run.
BACKTEST_KEYWORDS = [
    "backtrader", "vectorbt", "run_backtest",
    "cerebro.run", "vbt.Portfolio", "bt.run",
    "python -m backtest", "uv run backtest",
    "pytest -m backtest", "pytest -k backtest",
]

# Built-in defaults
DEFAULT_THRESHOLDS = {
    "sharpe": {
        "pattern": r"[Ss]harpe.*?(-?[\d.]+)",
        "threshold": 1.0,
        "comparison": "below",
        "message": "Sharpe Ratio below threshold",
    },
    "max_drawdown": {
        "pattern": r"[Mm]ax.*?[Dd]rawdown.*?(-?[\d.]+)%?",
        "threshold": 20.0,
        "comparison": "above",
        "message": "Max Drawdown exceeds threshold",
    },
    "win_rate": {
        "pattern": r"[Ww]in.*?[Rr]ate.*?([\d.]+)%?",
        "threshold": 40.0,
        "comparison": "below",
        "message": "Win Rate below threshold",
    },
    "profit_factor": {
        "pattern": r"[Pp]rofit.*?[Ff]actor.*?([\d.]+)",
        "threshold": 1.5,
        "comparison": "below",
        "message": "Profit Factor below threshold",
    },
}


def load_thresholds():
    """Load thresholds from project config, fall back to defaults."""
    config_path = os.path.join(
        os.environ.get("CLAUDE_PROJECT_DIR", "."),
        ".claude", "backtest-thresholds.json",
    )
    try:
        with open(config_path) as f:
            config = json.load(f)
        thresholds = {k: v for k, v in config.items() if not k.startswith("_") and v}
        return thresholds if thresholds else DEFAULT_THRESHOLDS
    except (FileNotFoundError, json.JSONDecodeError):
        return DEFAULT_THRESHOLDS


def handle(data):
    """Process a parsed PostToolUse payload.

    Returns additionalContext string if backtest detected, None otherwise.
    Called by the consolidated dispatcher or by main() for standalone use.
    """
    tool_input = data.get("tool_input", {})
    command = tool_input.get("command", "")

    command_lower = command.lower()
    if not any(kw in command_lower for kw in BACKTEST_KEYWORDS):
        return None

    # Claude Code emits the tool result as "tool_response"; accept the
    # legacy "tool_output" key as a fallback for direct invocation.
    tool_output = data.get("tool_response") or data.get("tool_output") or {}
    if not isinstance(tool_output, dict):
        tool_output = {}
    stdout = tool_output.get("stdout", "")
    stderr = tool_output.get("stderr", "")
    exit_code = tool_output.get("exit_code", 0)

    # If the backtest command failed, report failure.
    if exit_code != 0:
        failure_parts = [
            "BACKTEST FAILED (exit_code=%s). Recommended next steps:" % exit_code,
            "1. Inspect stderr/traceback before any further action.",
            "2. Delegate root-cause analysis: "
            '`codex exec --full-auto "Debug backtest failure: {error}"`',
            "3. Do NOT proceed with strategy validation until the failure is resolved.",
        ]
        if stderr:
            failure_parts.append("\nstderr (first 500 chars):\n%s" % stderr[:500])
        return "\n".join(failure_parts)

    thresholds = load_thresholds()

    # Gate: only proceed if stdout actually contains backtest-style metric output.
    # Without this, a `git commit` whose message mentions a backtest framework
    # would falsely fire the completion suggestion.
    if not any(
        re.search(cfg.get("pattern", ""), stdout)
        for cfg in thresholds.values()
    ):
        return None

    warnings = []

    for metric_name, config in thresholds.items():
        pattern = config.get("pattern", "")
        threshold = config.get("threshold", 0)
        comparison = config.get("comparison", "below")
        message = config.get("message", "%s threshold breached" % metric_name)

        match = re.search(pattern, stdout)
        if match:
            try:
                value = float(match.group(1))
                breached = False
                if comparison == "below" and value < threshold:
                    breached = True
                elif comparison == "above" and abs(value) > threshold:
                    breached = True

                if breached:
                    warnings.append(
                        "WARNING: %s (actual: %.4f, threshold: %s)"
                        % (message, value, threshold)
                    )
            except (ValueError, IndexError):
                pass

    suggestions = [
        "BACKTEST COMPLETED. Recommended next steps:",
        "1. Review performance metrics against risk-management.md thresholds",
        "2. Run statistical validation via Codex: "
        '`codex exec "Validate backtest results: {metrics}"`',
        "3. Check for look-ahead bias in strategy code",
        "4. Run Out-of-Sample test if not done",
    ]

    if warnings:
        suggestions.insert(0, "\n".join(warnings))

    return "\n".join(suggestions)


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
