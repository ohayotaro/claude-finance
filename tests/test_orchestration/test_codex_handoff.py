from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from types import ModuleType


def load_handoff() -> ModuleType:
    path = Path(__file__).parents[2] / ".claude" / "scripts" / "codex_handoff.py"
    spec = importlib.util.spec_from_file_location("codex_handoff", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def make_task(root: Path, tier: str = "T1", extra: str = "") -> Path:
    task_dir = root / ".claude" / "tasks" / "task-1"
    task_dir.mkdir(parents=True)
    brief = f"""# task-1: Test

## Objective
Validate runner behavior.

## Scope
Test only.

## Non-Goals
No repository changes.

## Acceptance Criteria
- AC1: Runner validates task state.

## Constraints And Context
No secrets.

## Risk Tier
{tier} - test rationale.

## Required Validation
pytest

## Forbidden Actions
No live trading.

## Open Decisions Or Blockers
None.
{extra}
"""
    (task_dir / "brief.md").write_text(brief, encoding="utf-8")
    return task_dir


def test_resolve_task_dir_rejects_traversal(tmp_path: Path) -> None:
    handoff = load_handoff()
    make_task(tmp_path)

    resolved = handoff.resolve_task_dir("task-1", tmp_path)
    assert resolved == (tmp_path / ".claude" / "tasks" / "task-1").resolve()

    with pytest.raises(handoff.HandoffError):
        handoff.resolve_task_dir("../outside", tmp_path)

    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(handoff.HandoffError):
        handoff.resolve_task_dir(str(outside), tmp_path)


def test_codex_command_flags_by_phase(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    handoff = load_handoff()
    monkeypatch.setenv("CODEX_HANDOFF_MODEL", "test-model")

    plan = handoff.build_codex_command("plan", tmp_path, tmp_path / "plan.md")
    implement = handoff.build_codex_command("implement", tmp_path, tmp_path / "result.md")
    review = handoff.build_codex_command("review", tmp_path, tmp_path / "review.md")

    assert plan[0:2] == ["codex", "exec"]
    assert "--strict-config" in plan
    assert "--ephemeral" in plan
    assert "--json" in plan
    assert plan[-1] == "-"
    assert plan[plan.index("--sandbox") + 1] == "read-only"
    assert implement[implement.index("--sandbox") + 1] == "workspace-write"
    assert review[review.index("--sandbox") + 1] == "read-only"
    assert plan[plan.index("--ask-for-approval") + 1] == "never"
    assert "--model" in plan

    joined = " ".join(plan + implement + review)
    assert "--full" + "-auto" not in joined
    assert "--" + "yolo" not in joined
    assert "danger-" + "full-access" not in joined


def test_implement_requires_approval_for_t2(tmp_path: Path) -> None:
    handoff = load_handoff()
    task_dir = make_task(tmp_path, tier="T2")
    (task_dir / "plan.md").write_text("Plan", encoding="utf-8")
    brief = (task_dir / "brief.md").read_text(encoding="utf-8")

    with pytest.raises(handoff.HandoffError):
        handoff.phase_prerequisites("implement", task_dir, brief)

    (task_dir / "approval.md").write_text("Approved by Claude PM.", encoding="utf-8")
    prerequisites = handoff.phase_prerequisites("implement", task_dir, brief)
    assert prerequisites["Approved plan"] == "Plan"
    assert prerequisites["Claude approval"] == "Approved by Claude PM."


def test_network_requirement_fails_closed(tmp_path: Path) -> None:
    handoff = load_handoff()
    task_dir = make_task(tmp_path, extra="Network access: required\n")
    brief = (task_dir / "brief.md").read_text(encoding="utf-8")

    with pytest.raises(handoff.HandoffError):
        handoff.ensure_no_network_requirement(brief)


def test_codex_nonzero_failure_writes_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handoff = load_handoff()
    task_dir = make_task(tmp_path)
    monkeypatch.setattr(handoff, "git_metadata", lambda _root: {"status": "clean"})

    def fake_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=["codex"], returncode=1, stdout="", stderr="boom")

    monkeypatch.setattr(handoff.subprocess, "run", fake_run)

    with pytest.raises(handoff.HandoffError):
        handoff.execute_phase("implement", "task-1", tmp_path)

    metadata = json.loads((task_dir / "implement.metadata.json").read_text(encoding="utf-8"))
    assert metadata["exit_status"] == 1
    assert (task_dir / "codex-implement.stderr.txt").read_text(encoding="utf-8") == "boom"


def test_empty_codex_output_is_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    handoff = load_handoff()
    make_task(tmp_path)
    monkeypatch.setattr(handoff, "git_metadata", lambda _root: {"status": "clean"})

    def fake_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["codex"],
            returncode=0,
            stdout='{"event":"done"}\n',
            stderr="",
        )

    monkeypatch.setattr(handoff.subprocess, "run", fake_run)

    with pytest.raises(handoff.HandoffError):
        handoff.execute_phase("implement", "task-1", tmp_path)
