#!/usr/bin/env python3
"""Consolidated PostToolUse dispatcher for Bash commands.

Reads stdin JSON once, then runs all PostToolUse/Bash handlers sequentially.
Each handler is isolated: if one raises an exception, the others still run.
Advisory additionalContext from all handlers is merged into a single JSON
output. No handler blocks (exit code 2), so this dispatcher never blocks.

Python 3.9 compatible. Stdlib only.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import traceback

# Handler modules in execution order.
# Each must expose a handle(data: dict) -> Optional[str] function.
_HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))

HANDLER_MODULES = [
    ("error_to_codex", os.path.join(_HOOKS_DIR, "error-to-codex.py")),
    ("post_backtest_analysis", os.path.join(_HOOKS_DIR, "post-backtest-analysis.py")),
    ("post_bot_execution", os.path.join(_HOOKS_DIR, "post-bot-execution.py")),
    ("log_cli_tools", os.path.join(_HOOKS_DIR, "log-cli-tools.py")),
]


def _load_module(name, path):
    """Load a Python module from an absolute file path."""
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    raw = sys.stdin.read()
    if not raw.strip():
        sys.exit(0)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        sys.exit(0)

    context_parts = []

    for mod_name, mod_path in HANDLER_MODULES:
        try:
            mod = _load_module(mod_name, mod_path)
            if mod is None:
                print(
                    f"post-bash-dispatcher: WARNING: could not load {mod_path}",
                    file=sys.stderr,
                )
                continue
            handle_fn = getattr(mod, "handle", None)
            if handle_fn is None:
                print(
                    f"post-bash-dispatcher: WARNING: no handle() in {mod_path}",
                    file=sys.stderr,
                )
                continue
            result = handle_fn(data)
            if result is not None:
                context_parts.append(result)
        except Exception:
            # Isolate failures: one handler raising must not prevent others
            tb_line = traceback.format_exc().splitlines()[-1]
            print(
                f"post-bash-dispatcher: WARNING: {mod_name} raised: {tb_line}",
                file=sys.stderr,
            )

    if not context_parts:
        sys.exit(0)

    output = {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": "\n\n".join(context_parts),
        }
    }
    json.dump(output, sys.stdout)


if __name__ == "__main__":
    main()
