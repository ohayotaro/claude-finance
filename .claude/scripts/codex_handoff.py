#!/usr/bin/env python3
"""Run isolated Codex handoff phases for Claude-managed tasks.

The runner is intentionally stdlib-only so hooks and skills can depend on it
without adding runtime dependencies.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import TextIO

FORBIDDEN_FLAGS = ("--full" + "-auto", "--" + "yolo")
STATE_NAME = "state.json"
EVENT_LOG_NAME = "codex-events.jsonl"
VALID_STATUSES = frozenset({"queued", "running", "succeeded", "failed", "blocked", "cancelled"})
REQUIRED_STATE_KEYS = frozenset(
    {
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
)
NETWORK_REQUIRED_RE = re.compile(
    r"(?im)^\s*(?:network(?:\s+access)?|requires\s+network)\s*:\s*"
    r"(?:required|yes|true)\s*$"
)
RISK_TIER_RE = re.compile(r"(?im)^\s*##\s*Risk Tier\s*$\s*^([Tt][0-3])\b", re.MULTILINE)


class HandoffError(RuntimeError):
    """Raised for invalid handoff state or Codex execution failure."""


@dataclass(frozen=True)
class PhaseConfig:
    """Codex execution settings for a handoff phase."""

    name: str
    sandbox: str
    output_name: str


PHASES: dict[str, PhaseConfig] = {
    "plan": PhaseConfig("plan", "read-only", "plan.md"),
    "implement": PhaseConfig("implement", "workspace-write", "implementation-result.md"),
    "review": PhaseConfig("review", "read-only", "review.md"),
}
LIFECYCLE_COMMANDS = frozenset({"status", "collect", "cancel"})
COMMANDS = frozenset(PHASES) | LIFECYCLE_COMMANDS

GitMetadata = dict[str, str]
HandoffState = dict[str, object]


def utc_now() -> str:
    """Return the current UTC timestamp in ISO 8601 form."""

    return datetime.now(UTC).isoformat()


def is_within(child: Path, parent: Path) -> bool:
    """Return whether child resolves inside parent."""

    try:
        return os.path.commonpath([str(child), str(parent)]) == str(parent)
    except ValueError:
        return False


def resolve_task_dir(task_ref: str, project_root: Path) -> Path:
    """Resolve a task ID or task path, rejecting traversal outside tasks root."""

    tasks_root = (project_root / ".claude" / "tasks").resolve()
    raw_ref = Path(task_ref)
    if raw_ref.is_absolute():
        candidate = raw_ref.resolve()
    elif raw_ref.parts and (raw_ref.parts[0] == ".claude" or len(raw_ref.parts) > 1):
        candidate = (project_root / raw_ref).resolve()
    else:
        candidate = (tasks_root / task_ref).resolve()

    if not is_within(candidate, tasks_root):
        raise HandoffError(f"Task path must stay under {tasks_root}: {task_ref}")
    if not candidate.is_dir():
        raise HandoffError(f"Task directory does not exist: {candidate}")
    return candidate


def task_id_from_dir(task_dir: Path) -> str:
    """Return the canonical task ID for a task directory."""

    return task_dir.name


def state_path(task_dir: Path) -> Path:
    """Return the unified state file path for a task."""

    return task_dir / STATE_NAME


def event_log_path(task_dir: Path) -> Path:
    """Return the consolidated event log path for a task."""

    return task_dir / EVENT_LOG_NAME


def phase_result_path(phase: str, task_dir: Path) -> Path:
    """Return the result artifact path for a phase."""

    return task_dir / PHASES[phase].output_name


def project_relative_path(path: Path, project_root: Path) -> str:
    """Return a stable project-relative path string when possible."""

    try:
        return str(path.resolve().relative_to(project_root.resolve()))
    except ValueError:
        return str(path)


def read_required(path: Path) -> str:
    """Read a required non-empty UTF-8 text file."""

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise HandoffError(f"Missing required file: {path}") from exc
    if not text.strip():
        raise HandoffError(f"Required file is empty: {path}")
    return text


def load_state(task_dir: Path) -> HandoffState:
    """Load state.json as a JSON object."""

    path = state_path(task_dir)
    try:
        decoded = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise HandoffError(f"Missing required state file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise HandoffError(f"State file is not valid JSON: {path}") from exc

    if not isinstance(decoded, dict):
        raise HandoffError(f"State file must contain a JSON object: {path}")
    return {str(key): value for key, value in decoded.items()}


def make_state(
    task_dir: Path,
    phase: str,
    status: str,
    started_at: str | None,
    finished_at: str | None,
    pid: int | None,
    exit_code: int | None,
    git_before: GitMetadata,
    git_after: GitMetadata,
    result_path: str,
) -> HandoffState:
    """Create a complete state object."""

    return {
        "task_id": task_id_from_dir(task_dir),
        "phase": phase,
        "status": status,
        "started_at": started_at,
        "finished_at": finished_at,
        "pid": pid,
        "exit_code": exit_code,
        "git_before": git_before,
        "git_after": git_after,
        "result_path": result_path,
    }


def write_state(task_dir: Path, state: HandoffState) -> None:
    """Write state.json, enforcing the required schema keys."""

    missing = sorted(REQUIRED_STATE_KEYS - state.keys())
    if missing:
        raise HandoffError(f"State is missing required keys: {', '.join(missing)}")

    status = state.get("status")
    if not isinstance(status, str) or status not in VALID_STATUSES:
        raise HandoffError(f"Invalid state status: {status}")

    state_path(task_dir).write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def append_jsonl(path: Path, entry: HandoffState) -> None:
    """Append one JSON object to a JSONL file."""

    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")


def append_event_marker(
    task_dir: Path,
    phase: str,
    marker: str,
    status: str,
    extra: HandoffState | None = None,
) -> None:
    """Append a phase marker to the consolidated event log."""

    entry: HandoffState = {
        "type": "phase_marker",
        "phase": phase,
        "marker": marker,
        "status": status,
        "timestamp": utc_now(),
    }
    if extra is not None:
        entry.update(extra)
    append_jsonl(event_log_path(task_dir), entry)


def append_event_stdout(task_dir: Path, stdout: str) -> None:
    """Append raw Codex JSONL stdout to the consolidated event log."""

    if not stdout:
        return
    with event_log_path(task_dir).open("a", encoding="utf-8") as handle:
        handle.write(stdout)
        if not stdout.endswith("\n"):
            handle.write("\n")


def risk_tier(brief: str) -> str | None:
    """Extract the risk tier from a canonical brief."""

    match = RISK_TIER_RE.search(brief)
    if match is None:
        return None
    return match.group(1).upper()


def ensure_no_network_requirement(brief: str) -> None:
    """Fail closed when a task declares that network access is required."""

    if NETWORK_REQUIRED_RE.search(brief):
        raise HandoffError(
            "Task declares network access is required. The handoff runner does not enable "
            "network by default; obtain explicit handling before running Codex."
        )


def phase_prerequisites(phase: str, task_dir: Path, brief: str) -> dict[str, str]:
    """Load phase prerequisites and validate task state."""

    if phase == "plan":
        return {}

    tier = risk_tier(brief)
    if tier is None:
        raise HandoffError("Brief must include a Risk Tier section before implementation/review")

    prerequisites: dict[str, str] = {}
    if phase == "implement":
        plan_path = task_dir / "plan.md"
        approval_path = task_dir / "approval.md"
        if tier in {"T2", "T3"}:
            prerequisites["Approved plan"] = read_required(plan_path)
            prerequisites["Claude approval"] = read_required(approval_path)
        elif plan_path.exists():
            prerequisites["Plan"] = read_required(plan_path)
        return prerequisites

    if phase == "review":
        prerequisites["Approved plan"] = read_required(task_dir / "plan.md")
        prerequisites["Implementation result"] = read_required(
            task_dir / PHASES["implement"].output_name
        )
        return prerequisites

    raise HandoffError(f"Unsupported phase: {phase}")


def run_text_command(args: list[str], cwd: Path) -> str:
    """Run a command and return stripped stdout, swallowing command failures."""

    try:
        result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=False)
    except OSError:
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def git_metadata(project_root: Path) -> GitMetadata:
    """Capture minimal Git state without storing command bodies or environment."""

    return {
        "head": run_text_command(["git", "rev-parse", "HEAD"], project_root),
        "branch": run_text_command(["git", "branch", "--show-current"], project_root),
        "status": run_text_command(["git", "status", "--short"], project_root),
    }


def build_codex_command(phase: str, project_root: Path, output_path: Path) -> list[str]:
    """Build the Codex command for a phase."""

    config = PHASES[phase]
    command = [
        "codex",
        "exec",
        "--strict-config",
        "--sandbox",
        config.sandbox,
        "--cd",
        str(project_root),
        "--ephemeral",
        "--json",
        "--output-last-message",
        str(output_path),
    ]

    model = os.environ.get("CODEX_HANDOFF_MODEL", "").strip()
    if model:
        command.extend(["--model", model])

    command.append("-")
    joined = " ".join(command)
    if any(flag in joined for flag in FORBIDDEN_FLAGS):
        raise HandoffError(f"Forbidden Codex flag present in command: {joined}")
    return command


def prompt_for_phase(phase: str, brief: str, prerequisites: dict[str, str]) -> str:
    """Assemble a phase prompt for Codex."""

    common = """You are Codex, the technical lead for this financial trading repository.

Read AGENTS.md and the relevant .claude/rules files before acting.
Preserve unrelated dirty-worktree changes. Never revert user work.
Do not commit, push, deploy, execute live trades, use production credentials,
or perform destructive Git operations.
Do not enable network access. If network is required, stop and report BLOCKED.
Map all conclusions to the task acceptance criteria.
"""

    if phase == "plan":
        contract = """Produce a plan only. Do not edit repository files.

Your output must include:
- Recommended design and rationale
- Alternatives considered
- Impacted files/components
- Implementation sequence
- Test/validation plan
- Risks and blockers
- Mapping to every acceptance criterion
"""
    elif phase == "implement":
        contract = """Implement the approved task. Run relevant tests and checks.

Your output must include:
- Status: PASS, PARTIAL, or BLOCKED
- Summary
- Files changed
- Material design decisions
- Exact validation commands and results
- Acceptance-criteria mapping
- Residual risks, debt, or blockers
"""
    elif phase == "review":
        contract = """Review the current repository and diff as a fresh independent reviewer.

Do not rely on any implementation transcript. You may read only the brief, approved plan,
implementation result artifact, repository, and diff available in this working tree.

Your output must include:
- Verdict: APPROVE or CHANGES_REQUIRED
- Findings by severity with file and line references where applicable
- Acceptance-criteria gaps
- Validation gaps
- Residual financial, operational, security, and regression risks
"""
    else:
        raise HandoffError(f"Unsupported phase: {phase}")

    sections = [common, contract, "## Task Brief\n\n" + brief.strip()]
    for title, body in prerequisites.items():
        sections.append(f"## {title}\n\n{body.strip()}")
    return "\n\n".join(sections) + "\n"


def finish_phase_state(
    task_dir: Path,
    phase: str,
    started_at: str,
    status: str,
    exit_code: int | None,
    git_before: GitMetadata,
    git_after: GitMetadata,
    result_path: str,
    error: str | None = None,
) -> None:
    """Write terminal phase state and append a finish marker."""

    state = make_state(
        task_dir=task_dir,
        phase=phase,
        status=status,
        started_at=started_at,
        finished_at=utc_now(),
        pid=os.getpid(),
        exit_code=exit_code,
        git_before=git_before,
        git_after=git_after,
        result_path=result_path,
    )
    write_state(task_dir, state)

    marker_extra: HandoffState = {"result_path": result_path}
    if exit_code is not None:
        marker_extra["exit_code"] = exit_code
    if error is not None:
        marker_extra["error"] = error
    append_event_marker(task_dir, phase, "finished", status, marker_extra)


def start_phase_state(
    task_dir: Path,
    phase: str,
    started_at: str,
    git_before: GitMetadata,
    result_path: str,
) -> None:
    """Write running phase state and append a start marker."""

    state = make_state(
        task_dir=task_dir,
        phase=phase,
        status="running",
        started_at=started_at,
        finished_at=None,
        pid=os.getpid(),
        exit_code=None,
        git_before=git_before,
        git_after={},
        result_path=result_path,
    )
    write_state(task_dir, state)
    append_event_marker(
        task_dir,
        phase,
        "started",
        "running",
        {"pid": os.getpid(), "result_path": result_path},
    )


def resolve_state_result_path(state: HandoffState, project_root: Path, task_dir: Path) -> Path:
    """Resolve the state result path, rejecting paths outside the task directory."""

    result_path = state.get("result_path")
    if not isinstance(result_path, str) or not result_path:
        raise HandoffError("State does not include a result_path")

    raw_path = Path(result_path)
    if raw_path.is_absolute():
        candidate = raw_path.resolve()
    else:
        candidate = (project_root / raw_path).resolve()

    if not is_within(candidate, task_dir.resolve()):
        raise HandoffError(f"State result_path must stay under {task_dir}: {result_path}")
    return candidate


def print_status(task_ref: str, project_root: Path, stdout: TextIO) -> Path:
    """Print state.json contents without modifying task files."""

    task_dir = resolve_task_dir(task_ref, project_root.resolve())
    path = state_path(task_dir)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise HandoffError(f"Missing required state file: {path}") from exc
    if not text.strip():
        raise HandoffError(f"Required file is empty: {path}")

    stdout.write(text)
    if not text.endswith("\n"):
        stdout.write("\n")
    return path


def collect_result(task_ref: str, project_root: Path, stdout: TextIO) -> Path:
    """Print the current state's result artifact without modifying task files."""

    project_root = project_root.resolve()
    task_dir = resolve_task_dir(task_ref, project_root)
    state = load_state(task_dir)
    result_path = resolve_state_result_path(state, project_root, task_dir)
    try:
        stdout.write(result_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise HandoffError(f"Missing result artifact: {result_path}") from exc
    return result_path


def cancel_task(task_ref: str, project_root: Path) -> Path:
    """Mark a task cancelled without signaling any running process."""

    task_dir = resolve_task_dir(task_ref, project_root.resolve())
    now = utc_now()
    if state_path(task_dir).exists():
        state = load_state(task_dir)
        state["task_id"] = task_id_from_dir(task_dir)
        state["phase"] = state.get("phase") if isinstance(state.get("phase"), str) else "cancel"
        state["status"] = "cancelled"
        state["started_at"] = (
            state.get("started_at") if isinstance(state.get("started_at"), str) else now
        )
        state["finished_at"] = now
        state["pid"] = os.getpid()
        state["exit_code"] = (
            state.get("exit_code") if isinstance(state.get("exit_code"), int) else None
        )
        state["git_before"] = (
            state.get("git_before") if isinstance(state.get("git_before"), dict) else {}
        )
        state["git_after"] = (
            state.get("git_after") if isinstance(state.get("git_after"), dict) else {}
        )
        state["result_path"] = (
            state.get("result_path") if isinstance(state.get("result_path"), str) else ""
        )
    else:
        state = make_state(
            task_dir=task_dir,
            phase="cancel",
            status="cancelled",
            started_at=now,
            finished_at=now,
            pid=os.getpid(),
            exit_code=None,
            git_before={},
            git_after={},
            result_path="",
        )
    write_state(task_dir, state)
    return state_path(task_dir)


def execute_phase(phase: str, task_ref: str, project_root: Path) -> Path:
    """Run one Codex phase and return the output artifact path."""

    if phase not in PHASES:
        raise HandoffError(f"Unsupported phase: {phase}")

    project_root = project_root.resolve()
    task_dir = resolve_task_dir(task_ref, project_root)
    brief = read_required(task_dir / "brief.md")
    output_path = phase_result_path(phase, task_dir)
    result_path = project_relative_path(output_path, project_root)
    started_at = utc_now()
    git_before = git_metadata(project_root)

    start_phase_state(task_dir, phase, started_at, git_before, result_path)

    try:
        ensure_no_network_requirement(brief)
        prerequisites = phase_prerequisites(phase, task_dir, brief)
        prompt = prompt_for_phase(phase, brief, prerequisites)
        command = build_codex_command(phase, project_root, output_path)
    except HandoffError as exc:
        git_after = git_metadata(project_root)
        finish_phase_state(
            task_dir=task_dir,
            phase=phase,
            started_at=started_at,
            status="blocked",
            exit_code=None,
            git_before=git_before,
            git_after=git_after,
            result_path=result_path,
            error=str(exc),
        )
        raise

    try:
        result = subprocess.run(
            command,
            cwd=project_root,
            input=prompt,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        error = f"Failed to execute Codex: {exc}"
        git_after = git_metadata(project_root)
        finish_phase_state(
            task_dir=task_dir,
            phase=phase,
            started_at=started_at,
            status="failed",
            exit_code=None,
            git_before=git_before,
            git_after=git_after,
            result_path=result_path,
            error=error,
        )
        raise HandoffError(error) from exc

    git_after = git_metadata(project_root)

    append_event_stdout(task_dir, result.stdout)
    if result.stderr.strip():
        (task_dir / f"codex-{phase}.stderr.txt").write_text(
            result.stderr,
            encoding="utf-8",
        )

    if result.returncode != 0:
        error = f"Codex {phase} failed with exit status {result.returncode}"
        finish_phase_state(
            task_dir=task_dir,
            phase=phase,
            started_at=started_at,
            status="failed",
            exit_code=result.returncode,
            git_before=git_before,
            git_after=git_after,
            result_path=result_path,
            error=error,
        )
        raise HandoffError(error)

    try:
        output_text = output_path.read_text(encoding="utf-8")
    except OSError:
        output_text = ""
    if not output_text.strip():
        error = f"Codex {phase} produced no final output: {output_path}"
        finish_phase_state(
            task_dir=task_dir,
            phase=phase,
            started_at=started_at,
            status="failed",
            exit_code=result.returncode,
            git_before=git_before,
            git_after=git_after,
            result_path=result_path,
            error=error,
        )
        raise HandoffError(error)

    finish_phase_state(
        task_dir=task_dir,
        phase=phase,
        started_at=started_at,
        status="succeeded",
        exit_code=result.returncode,
        git_before=git_before,
        git_after=git_after,
        result_path=result_path,
    )
    return output_path


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse CLI arguments."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=sorted(COMMANDS))
    parser.add_argument("task", help="Task ID or path under .claude/tasks/")
    parser.add_argument(
        "--project-root",
        default=".",
        help="Repository root. Defaults to the current directory.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""

    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        project_root = Path(args.project_root)
        if args.command == "status":
            output_path = print_status(args.task, project_root, sys.stdout)
        elif args.command == "collect":
            output_path = collect_result(args.task, project_root, sys.stdout)
        elif args.command == "cancel":
            output_path = cancel_task(args.task, project_root)
        else:
            output_path = execute_phase(args.command, args.task, project_root)
    except HandoffError as exc:
        print(f"codex_handoff: {exc}", file=sys.stderr)
        return 2
    if args.command not in {"status", "collect"}:
        print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
