from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[2]


def iter_active_text_files() -> list[Path]:
    paths: list[Path] = [
        ROOT / "AGENTS.md",
        ROOT / "CLAUDE.md",
        ROOT / "README.md",
        ROOT / ".claude" / "settings.json",
    ]
    for directory in [
        ROOT / ".claude" / "hooks",
        ROOT / ".claude" / "rules",
        ROOT / ".claude" / "scripts",
        ROOT / ".claude" / "skills",
    ]:
        paths.extend(
            path
            for path in directory.rglob("*")
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
        )
    return paths


def test_no_agent_frontmatter_in_active_skills() -> None:
    for path in (ROOT / ".claude" / "skills").glob("*/SKILL.md"):
        text = path.read_text(encoding="utf-8")
        assert "\nagent:" not in text


def test_no_deprecated_codex_flags_in_active_contracts() -> None:
    forbidden = ["--full" + "-auto", "--" + "yolo", "danger-" + "full-access"]
    offenders: list[str] = []
    for path in iter_active_text_files():
        text = path.read_text(encoding="utf-8")
        for term in forbidden:
            if term in text:
                offenders.append(f"{path.relative_to(ROOT)}:{term}")
    assert offenders == []


def test_no_active_legacy_provider_or_role_routing_references() -> None:
    forbidden = [
        "Gem" + "ini",
        "gem" + "ini",
        "Agent Teams",
        "TeammateIdle",
        "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS",
        "CLAUDE_CODE_SUBAGENT_MODEL",
        "codex-debugger",
        "agent-router",
        "routing-keywords",
        "team-implement",
        "team-review",
        "codex-system",
        "gemini-system",
        "market-analysis",
    ]
    offenders: list[str] = []
    for path in iter_active_text_files():
        text = path.read_text(encoding="utf-8")
        for term in forbidden:
            if term in text:
                offenders.append(f"{path.relative_to(ROOT)}:{term}")
    assert offenders == []
