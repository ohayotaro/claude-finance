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


GIT_STATE = {"head": "abc123", "branch": "main", "status": "clean"}
STATE_KEYS = {
    "task_id",
    "phase",
    "status",
    "started_at",
    "finished_at",
    "pid",
    "exit_code",
    "git_before",
    "git_after",
    "result_path",
}


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


def read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def assert_state_schema(state: dict[str, object]) -> None:
    assert set(state) == STATE_KEYS


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
    implement = handoff.build_codex_command(
        "implement",
        tmp_path,
        tmp_path / "implementation-result.md",
    )
    review = handoff.build_codex_command("review", tmp_path, tmp_path / "review.md")

    assert plan[0:2] == ["codex", "exec"]
    assert "--strict-config" in plan
    assert "--ephemeral" in plan
    assert "--json" in plan
    assert plan[-1] == "-"
    assert plan[plan.index("--sandbox") + 1] == "read-only"
    assert implement[implement.index("--sandbox") + 1] == "workspace-write"
    assert review[review.index("--sandbox") + 1] == "read-only"
    deprecated_approval_flag = "--ask-for-" + "approval"
    assert deprecated_approval_flag not in plan
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


def test_phase_runs_write_state_and_consolidated_events(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handoff = load_handoff()
    task_dir = make_task(tmp_path)
    monkeypatch.setattr(handoff, "git_metadata", lambda _root: GIT_STATE)

    def fake_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        command = _args[0]
        assert isinstance(command, list)
        output_path = Path(command[command.index("--output-last-message") + 1])
        output_path.write_text(f"{output_path.name} body", encoding="utf-8")
        stdout = '{"event":"done"}\n'
        return subprocess.CompletedProcess(args=["codex"], returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(handoff.subprocess, "run", fake_run)

    for phase, artifact in [
        ("plan", "plan.md"),
        ("implement", "implementation-result.md"),
        ("review", "review.md"),
    ]:
        output_path = handoff.execute_phase(phase, "task-1", tmp_path)
        assert output_path == task_dir / artifact

        state = read_json(task_dir / "state.json")
        assert_state_schema(state)
        assert state["task_id"] == "task-1"
        assert state["phase"] == phase
        assert state["status"] == "succeeded"
        assert state["pid"] == handoff.os.getpid()
        assert state["exit_code"] == 0
        assert state["git_before"] == GIT_STATE
        assert state["git_after"] == GIT_STATE
        assert str(state["result_path"]).endswith(artifact)

    assert not (task_dir / ("result" + ".md")).exists()
    assert not list(task_dir.glob("*.metadata.json"))
    assert not list(task_dir.glob("codex-*.events.jsonl"))

    events = [
        json.loads(line)
        for line in (task_dir / "codex-events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    markers = [event for event in events if event.get("type") == "phase_marker"]
    assert [(marker["phase"], marker["marker"]) for marker in markers] == [
        ("plan", "started"),
        ("plan", "finished"),
        ("implement", "started"),
        ("implement", "finished"),
        ("review", "started"),
        ("review", "finished"),
    ]


def test_review_prompt_excludes_implementation_event_log(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handoff = load_handoff()
    make_task(tmp_path)
    monkeypatch.setattr(handoff, "git_metadata", lambda _root: GIT_STATE)
    prompts: dict[str, str] = {}

    def fake_run(*_args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        command = _args[0]
        assert isinstance(command, list)
        output_path = Path(command[command.index("--output-last-message") + 1])
        prompt = kwargs["input"]
        assert isinstance(prompt, str)
        prompts[output_path.name] = prompt
        output_path.write_text(f"{output_path.name} body", encoding="utf-8")
        stdout = '{"event":"IMPLEMENT_EVENT_SHOULD_NOT_APPEAR"}\n'
        if output_path.name != "implementation-result.md":
            stdout = '{"event":"done"}\n'
        return subprocess.CompletedProcess(args=["codex"], returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(handoff.subprocess, "run", fake_run)

    handoff.execute_phase("plan", "task-1", tmp_path)
    handoff.execute_phase("implement", "task-1", tmp_path)
    handoff.execute_phase("review", "task-1", tmp_path)

    review_prompt = prompts["review.md"]
    assert "implementation-result.md body" in review_prompt
    assert "IMPLEMENT_EVENT_SHOULD_NOT_APPEAR" not in review_prompt
    assert "codex-events.jsonl" not in review_prompt


def test_codex_nonzero_failure_writes_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handoff = load_handoff()
    task_dir = make_task(tmp_path)
    monkeypatch.setattr(handoff, "git_metadata", lambda _root: GIT_STATE)

    def fake_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=["codex"], returncode=1, stdout="", stderr="boom")

    monkeypatch.setattr(handoff.subprocess, "run", fake_run)

    with pytest.raises(handoff.HandoffError):
        handoff.execute_phase("implement", "task-1", tmp_path)

    state = read_json(task_dir / "state.json")
    assert_state_schema(state)
    assert state["phase"] == "implement"
    assert state["status"] == "failed"
    assert state["exit_code"] == 1
    assert (task_dir / "codex-implement.stderr.txt").read_text(encoding="utf-8") == "boom"


def test_empty_codex_output_is_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    handoff = load_handoff()
    task_dir = make_task(tmp_path)
    monkeypatch.setattr(handoff, "git_metadata", lambda _root: GIT_STATE)

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

    state = read_json(task_dir / "state.json")
    assert_state_schema(state)
    assert state["status"] == "failed"
    assert state["exit_code"] == 0


def test_status_and_collect_are_read_only(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    handoff = load_handoff()
    task_dir = make_task(tmp_path)
    artifact = task_dir / "implementation-result.md"
    artifact.write_text("implementation summary", encoding="utf-8")
    state = handoff.make_state(
        task_dir=task_dir,
        phase="implement",
        status="succeeded",
        started_at="2026-06-22T00:00:00+00:00",
        finished_at="2026-06-22T00:01:00+00:00",
        pid=123,
        exit_code=0,
        git_before=GIT_STATE,
        git_after=GIT_STATE,
        result_path=".claude/tasks/task-1/implementation-result.md",
    )
    handoff.write_state(task_dir, state)

    state_path = task_dir / "state.json"
    before_state = state_path.read_bytes()
    before_artifact = artifact.read_bytes()

    assert handoff.main(["status", "task-1", "--project-root", str(tmp_path)]) == 0
    status_out = capsys.readouterr().out
    assert json.loads(status_out) == state
    assert state_path.read_bytes() == before_state
    assert artifact.read_bytes() == before_artifact

    assert handoff.main(["collect", "task-1", "--project-root", str(tmp_path)]) == 0
    collect_out = capsys.readouterr().out
    assert collect_out == "implementation summary"
    assert state_path.read_bytes() == before_state
    assert artifact.read_bytes() == before_artifact


def test_cancel_sets_cancelled_state(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    handoff = load_handoff()
    task_dir = make_task(tmp_path)
    state = handoff.make_state(
        task_dir=task_dir,
        phase="implement",
        status="running",
        started_at="2026-06-22T00:00:00+00:00",
        finished_at=None,
        pid=999999,
        exit_code=None,
        git_before=GIT_STATE,
        git_after={},
        result_path=".claude/tasks/task-1/implementation-result.md",
    )
    handoff.write_state(task_dir, state)

    assert handoff.main(["cancel", "task-1", "--project-root", str(tmp_path)]) == 0
    assert capsys.readouterr().out.endswith("state.json\n")

    cancelled = read_json(task_dir / "state.json")
    assert_state_schema(cancelled)
    assert cancelled["phase"] == "implement"
    assert cancelled["status"] == "cancelled"
    assert cancelled["finished_at"] is not None
