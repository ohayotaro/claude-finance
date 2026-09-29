from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from types import ModuleType


def load_guard() -> ModuleType:
    path = Path(__file__).parents[2] / ".claude" / "hooks" / "pm-write-guard.py"
    spec = importlib.util.spec_from_file_location("pm_write_guard", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "file_path",
    [
        ".claude/tasks/task-1/brief.md",
        ".claude/state/session.json",
        ".claude/rules/security.md",
        ".claude/skills/codex-task/SKILL.md",
        ".claude/scripts/codex_handoff.py",
        ".claude/hooks/error-to-codex.py",
        ".claude/hooks/live-trading-gate.py.bak",
        ".claude/settings.local.json",
        "AGENTS.md",
        "CLAUDE.md",
        "src/bot/main.py",
        "config/strategies/example.toml",
        "tests/test_example.py",
        ".env.example",
        ".env.production.example",
    ],
)
def test_pm_write_guard_allows_unprotected_paths(tmp_path: Path, file_path: str) -> None:
    guard = load_guard()
    allowed, reason = guard.is_allowed_path(file_path, tmp_path)
    assert allowed
    assert "Allowed" in reason


@pytest.mark.parametrize(
    "file_path",
    [
        ".claude/hooks/live-trading-gate.py",
        ".claude/hooks/pm-write-guard.py",
        ".claude/settings.json",
        ".claude/SETTINGS.JSON",
        ".claude/state/live-trading-2026-09-29.ack",
        ".env",
        ".env.production",
        "config/.env.live",
    ],
)
def test_pm_write_guard_blocks_safety_gate_paths(tmp_path: Path, file_path: str) -> None:
    guard = load_guard()
    allowed, reason = guard.is_allowed_path(file_path, tmp_path)
    assert not allowed
    assert "explicit approval" in reason


def test_pm_write_guard_blocks_symlink_to_protected_file(tmp_path: Path) -> None:
    guard = load_guard()
    hooks = tmp_path / ".claude" / "hooks"
    hooks.mkdir(parents=True)
    (hooks / "live-trading-gate.py").write_text("gate", encoding="utf-8")
    (tmp_path / "alias.py").symlink_to(hooks / "live-trading-gate.py")

    allowed, _reason = guard.is_allowed_path("alias.py", tmp_path)
    assert not allowed


def test_pm_write_guard_blocks_protected_name_that_is_a_symlink(tmp_path: Path) -> None:
    guard = load_guard()
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "credentials.txt").write_text("x", encoding="utf-8")
    (tmp_path / ".env").symlink_to(tmp_path / "config" / "credentials.txt")

    allowed, _reason = guard.is_allowed_path(".env", tmp_path)
    assert not allowed


def test_pm_write_guard_blocks_protected_name_linking_outside_project(tmp_path: Path) -> None:
    guard = load_guard()
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("x", encoding="utf-8")
    (project / ".env").symlink_to(outside)

    allowed, _reason = guard.is_allowed_path(".env", project)
    assert not allowed


def test_pm_write_guard_blocks_via_symlinked_project_root(tmp_path: Path) -> None:
    guard = load_guard()
    real = tmp_path / "real"
    (real / ".claude").mkdir(parents=True)
    alias = tmp_path / "alias"
    alias.symlink_to(real)

    allowed, _reason = guard.is_allowed_path(str(alias / ".claude" / "settings.json"), alias)
    assert not allowed


@pytest.mark.parametrize(
    "variant",
    [
        "{root_upper}/.claude/settings.json",
        "{root_upper}/.CLAUDE/hooks/live-trading-gate.py",
        "{root_upper}/.Env",
    ],
)
def test_pm_write_guard_blocks_ancestor_case_variants(tmp_path: Path, variant: str) -> None:
    guard = load_guard()
    project = tmp_path / "claude-finance"
    project.mkdir()
    root_upper = str(tmp_path / "CLAUDE-FINANCE")

    allowed, _reason = guard.is_allowed_path(variant.format(root_upper=root_upper), project)
    assert not allowed


def test_pm_write_guard_leaves_outside_project_to_permissions(tmp_path: Path) -> None:
    guard = load_guard()
    allowed, reason = guard.is_allowed_path("../outside.md", tmp_path)
    assert allowed
    assert "outside project" in reason
