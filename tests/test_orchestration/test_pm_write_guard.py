from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING

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


def test_pm_write_guard_allows_task_artifacts(tmp_path: Path) -> None:
    guard = load_guard()
    allowed, reason = guard.is_allowed_path(".claude/tasks/task-1/brief.md", tmp_path)
    assert allowed
    assert "Allowed" in reason


def test_pm_write_guard_blocks_source_writes(tmp_path: Path) -> None:
    guard = load_guard()
    allowed, reason = guard.is_allowed_path("src/strategies/example.py", tmp_path)
    assert not allowed
    assert "codex_handoff.py" in reason


def test_pm_write_guard_rejects_traversal(tmp_path: Path) -> None:
    guard = load_guard()
    allowed, reason = guard.is_allowed_path("../outside.md", tmp_path)
    assert not allowed
    assert "outside-project" in reason
