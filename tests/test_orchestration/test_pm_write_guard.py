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
        ".claude/checkpoints/task-1.json",
        ".claude/plans/task-1.md",
        ".claude/state/session.json",
        ".claude/docs/reviews/task-1.md",
    ],
)
def test_pm_write_guard_allows_pm_orchestration_paths(
    tmp_path: Path, file_path: str
) -> None:
    guard = load_guard()
    allowed, reason = guard.is_allowed_path(file_path, tmp_path)
    assert allowed
    assert "Allowed" in reason


@pytest.mark.parametrize("file_name", ["README.md", "CLAUDE.md"])
def test_pm_write_guard_allows_root_documentation_files(
    tmp_path: Path, file_name: str
) -> None:
    guard = load_guard()
    allowed, reason = guard.is_allowed_path(str(tmp_path / file_name), tmp_path)
    assert allowed
    assert reason == "Allowed: PM root documentation file"


@pytest.mark.parametrize(
    "file_path",
    [
        ".claude/rules/security.md",
        "src/bot/main.py",
        "config/strategies/example.toml",
        "mql5/Experts/example.mq5",
        "tests/test_example.py",
        "docs/README.md",
    ],
)
def test_pm_write_guard_blocks_disallowed_paths(tmp_path: Path, file_path: str) -> None:
    guard = load_guard()
    allowed, reason = guard.is_allowed_path(file_path, tmp_path)
    assert not allowed
    assert "codex_handoff.py" in reason


def test_pm_write_guard_rejects_traversal(tmp_path: Path) -> None:
    guard = load_guard()
    allowed, reason = guard.is_allowed_path("../outside.md", tmp_path)
    assert not allowed
    assert "outside-project" in reason
