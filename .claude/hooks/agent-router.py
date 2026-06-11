#!/usr/bin/env python3
"""UserPromptSubmit hook: Analyze user prompt and suggest optimal AI routing.

Selects ONE primary route, with at most ONE fallback when a different category
also matches strongly. This keeps suggestions actionable instead of dumping
every keyword match.

Priority order (used as tiebreaker):
  1. Gemini — multimodal file references (images, PDFs)
  2. Codex  — design, debug, optimization, algorithm keywords
  3. Specialized subagent — configurable domain keywords

Within a category, the candidate with the most matched keywords wins.
A fallback is only emitted if it comes from a different category than the
primary AND has at least one keyword match.

Keywords are loaded from .claude/routing-keywords.json if present,
otherwise built-in defaults are used.
"""
from __future__ import annotations

import json
import os
import re
import sys

# Built-in defaults (used when routing-keywords.json is missing or empty)
DEFAULT_ROUTING: dict[str, list[str]] = {
    "data-engineer": [
        "data", "fetch", "pipeline", "ohlcv", "parquet", "csv",
        "market data", "historical", "tick data", "candle",
    ],
    "quant-analyst": [
        "backtest", "sharpe", "sortino", "drawdown", "var",
        "cvar", "monte carlo", "walk-forward", "bootstrap",
        "performance", "metrics", "statistical",
    ],
    "strategist": [
        "strategy", "signal", "entry", "exit", "indicator",
        "moving average", "crossover", "momentum", "reversion",
        "trend", "mean reversion",
    ],
    "ea-developer": [
        "ea", "expert advisor", "mql5", "mql4", "metatrader",
        "ontick", "ctrade",
    ],
    "bot-engineer": [
        "bot", "ccxt", "websocket", "async", "executor",
        "live trading", "order manager", "position tracker",
        "testnet", "sandbox", "execution",
    ],
    "infra-ops": [
        "deploy", "docker", "dockerfile", "compose",
        "systemd", "kubernetes", "k8s", "vps", "cloud",
        "monitor", "alert", "grafana", "prometheus",
        "health check", "log", "ci/cd", "pipeline",
        "dashboard", "notification", "launchd",
    ],
    "ml-engineer": [
        "machine learning", "ml", "model", "train", "feature",
        "clustering", "classification", "regression",
        "regime", "walk-forward", "purge",
        "hyperparameter", "ablation", "overfitting",
    ],
    "codex-debugger": [
        "debug", "error", "traceback", "exception", "fix",
        "root cause", "stack trace", "failure", "crash",
        "bug", "failing test", "regression",
    ],
    "general-purpose": [
        "explore", "find", "search", "document", "explain",
        "summarize", "list", "count", "structure",
    ],
}


def load_routing_config() -> dict[str, list[str]]:
    """Load routing keywords from project config, fall back to defaults."""
    config_path = os.path.join(
        os.environ.get("CLAUDE_PROJECT_DIR", "."),
        ".claude", "routing-keywords.json",
    )
    try:
        with open(config_path) as f:
            config = json.load(f)
        # Filter out comment keys and empty entries
        routing = {k: v for k, v in config.items() if not k.startswith("_") and v}
        return routing if routing else DEFAULT_ROUTING
    except (FileNotFoundError, json.JSONDecodeError):
        return DEFAULT_ROUTING


def main() -> None:
    raw = sys.stdin.read()
    if not raw.strip():
        sys.exit(0)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        sys.exit(0)

    prompt = data.get("prompt", "")
    if len(prompt) < 10:
        sys.exit(0)

    prompt_lower = prompt.lower()

    # Each candidate: (priority, score, category, message)
    # priority: lower number = higher priority category
    # score: number of matched keywords (used to break ties within priority)
    candidates: list[tuple[int, int, str, str]] = []

    # --- Priority 1: Gemini (multimodal) ---
    multimodal_patterns = [
        r"\.(png|jpg|jpeg|gif|svg|webp|bmp|tiff)",
        r"\.(pdf|doc|docx|xls|xlsx)",
        r"chart|image|screenshot|diagram|picture",
    ]
    multimodal_hits = sum(
        1 for pattern in multimodal_patterns if re.search(pattern, prompt_lower)
    )
    if multimodal_hits > 0:
        candidates.append((
            1, multimodal_hits, "gemini",
            "ROUTING: This task involves multimodal input. "
            "Consider delegating to Gemini CLI: "
            '`gemini -p "{prompt}" -f {file}`',
        ))

    # --- Priority 2: Codex (deep reasoning) ---
    codex_keywords = [
        "design", "architect", "debug", "error", "traceback",
        "optimize", "algorithm", "review", "refactor",
        "bug", "failing test", "regression",
    ]
    codex_hits = sum(1 for kw in codex_keywords if kw in prompt_lower)
    if codex_hits > 0:
        candidates.append((
            2, codex_hits, "codex",
            "ROUTING: This task may benefit from deep reasoning. "
            "Consider delegating to Codex CLI: "
            '`codex exec "{task}"`',
        ))

    # --- Priority 3: Specialized subagent (config-driven) ---
    # Pick the single subagent with the highest keyword match count.
    agent_routing = load_routing_config()
    best_agent: str | None = None
    best_agent_hits = 0
    for agent, keywords in agent_routing.items():
        hits = sum(1 for kw in keywords if kw in prompt_lower)
        if hits > best_agent_hits:
            best_agent = agent
            best_agent_hits = hits
    if best_agent is not None:
        candidates.append((
            3, best_agent_hits, "subagent",
            f"ROUTING: Consider using the '{best_agent}' subagent for this task.",
        ))

    if not candidates:
        sys.exit(0)

    # Sort: higher-priority category first, then more keyword matches first.
    candidates.sort(key=lambda c: (c[0], -c[1]))

    suggestions: list[str] = [candidates[0][3]]
    # Optional fallback: only if from a different category.
    primary_category = candidates[0][2]
    for cand in candidates[1:]:
        if cand[2] != primary_category:
            suggestions.append("ROUTING (fallback): " + cand[3].split("ROUTING: ", 1)[-1])
            break

    result = {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": "\n".join(suggestions),
        }
    }
    json.dump(result, sys.stdout)


if __name__ == "__main__":
    main()
