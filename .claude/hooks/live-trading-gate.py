#!/usr/bin/env python3
"""PreToolUse hook (Bash): Block live-trading commands unless safety
acknowledgment is in place.

Detection patterns:
  - BOT_MODE=live
  - BOT_ENVIRONMENT=production
  - --mode live | --mode=live
  - --live (standalone, not --live-something)
  - --env-file *.env.production | *.env.live

Gates (in order):
  1. KillSwitch: if data/KILL exists -> block.
  2. Per-strategy KillSwitch: if data/KILL.{strategy_id} exists -> block.
  3. Acknowledgment: .claude/state/live-trading-{YYYY-MM-DD}.ack created
     within the last 24 hours. If absent or stale -> block with checklist.
  4. Otherwise -> allow.

Exit codes:
  0 = allow (no live indicator, or all gates pass)
  2 = block (Claude Code surfaces stderr to the model)
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
from datetime import datetime, timedelta, timezone

LIVE_PATTERNS = [
    r"\bBOT_MODE\s*=\s*['\"]?live\b",
    r"\bBOT_ENVIRONMENT\s*=\s*['\"]?production\b",
    r"--mode[\s=]+['\"]?live\b",
    r"(?<![\w-])--live(?:\s|$|['\"])",
    r"--env-file\s+\S*\.env\.production\b",
    r"--env-file\s+\S*\.env\.live\b",
]

# Verbs that can never start a trading bot. If the command starts with one
# of these, skip the live-pattern scan entirely — otherwise commit messages,
# echo strings, and grep queries that mention live-trading keywords would
# false-positive (the gate would block its own commits, etc.).
SAFE_LEAD_VERBS = {
    "git", "gh", "echo", "printf", "cat", "head", "tail", "less", "more",
    "grep", "rg", "awk", "sed", "wc", "sort", "uniq", "find", "ls", "pwd",
    "diff", "jq", "tr", "cut", "rm", "mkdir", "rmdir", "touch", "mv", "cp",
    "chmod", "chown", "stat", "tree", "which", "type",
}


def first_executable_verb(command: str) -> str | None:
    """Return the first non-env-var-assignment token's basename, or None."""
    for tok in command.strip().split():
        # Skip leading env-var assignments like FOO=bar (but not paths or flags)
        if "=" in tok and "/" not in tok and not tok.startswith("-"):
            continue
        return os.path.basename(tok)
    return None


def command_tokens(command: str) -> list[str]:
    try:
        return shlex.split(command)
    except ValueError:
        return command.strip().split()


def extract_strategy_id(command: str) -> str | None:
    tokens = command_tokens(command)

    for index, token in enumerate(tokens):
        if token == "--strategy-id" and index + 1 < len(tokens):
            return tokens[index + 1]
        if token.startswith("--strategy-id="):
            return token.split("=", 1)[1]

    for token in tokens:
        if token.startswith("STRATEGY_ID="):
            return token.split("=", 1)[1]

    return None


CHECKLIST = """Live-trading acknowledgment required.

Before acknowledging, confirm ALL of:
  [ ] Testnet validation passed within the last 7 days
  [ ] MAX_POSITION_SIZE and MAX_DAILY_LOSS environment variables set
  [ ] Stop loss implemented in the strategy code
  [ ] KillSwitch verified (touch data/KILL exits the bot cleanly)
  [ ] Notification webhook smoke-tested
  [ ] /risk-report generated within the last 7 days

When all items are true, acknowledge with:

  mkdir -p .claude/state
  touch .claude/state/live-trading-$(date +%Y-%m-%d).ack

The acknowledgment is valid for 24 hours; re-create it daily.

See .claude/rules/security.md "Live-trading acknowledgment" for rationale.
"""


def acknowledgment_valid(state_dir: str) -> bool:
    if not os.path.isdir(state_dir):
        return False
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)  # noqa: UP017
    for entry in os.listdir(state_dir):
        if not (entry.startswith("live-trading-") and entry.endswith(".ack")):
            continue
        full = os.path.join(state_dir, entry)
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(full), tz=timezone.utc)  # noqa: UP017
        except OSError:
            continue
        if mtime >= cutoff:
            return True
    return False


def main() -> None:
    raw = sys.stdin.read()
    if not raw.strip():
        sys.exit(0)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        sys.exit(0)

    tool_input = data.get("tool_input", {})
    command = tool_input.get("command", "")
    if not command:
        sys.exit(0)

    # Skip non-execution commands (git commit, echo, grep, etc.) — they cannot
    # start a trading bot, even if their arguments mention live-trading keywords.
    verb = first_executable_verb(command)
    if verb and verb in SAFE_LEAD_VERBS:
        sys.exit(0)

    if not any(re.search(p, command) for p in LIVE_PATTERNS):
        sys.exit(0)

    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", ".")

    # Gate 1: KillSwitch
    kill_path = os.path.join(project_dir, "data", "KILL")
    if os.path.exists(kill_path):
        print(
            "BLOCKED: KillSwitch active (data/KILL exists). "
            "Live-trading commands are denied until the underlying issue is resolved.",
            file=sys.stderr,
        )
        sys.exit(2)

    strategy_id = extract_strategy_id(command)
    if strategy_id:
        per_strategy_kill_path = os.path.join(project_dir, "data", f"KILL.{strategy_id}")
        if os.path.exists(per_strategy_kill_path):
            print(
                "BLOCKED: Per-strategy KillSwitch active "
                f"({per_strategy_kill_path} exists for strategy_id={strategy_id}). "
                "Live-trading commands for this strategy are denied until the "
                "underlying issue is resolved.",
                file=sys.stderr,
            )
            sys.exit(2)

    # Gate 3: 24-hour acknowledgment file
    state_dir = os.path.join(project_dir, ".claude", "state")
    if acknowledgment_valid(state_dir):
        sys.exit(0)

    print(
        f"BLOCKED: Live-trading command detected without valid acknowledgment.\n\n"
        f"Detected command:\n  {command}\n\n"
        f"{CHECKLIST}",
        file=sys.stderr,
    )
    sys.exit(2)


if __name__ == "__main__":
    main()
