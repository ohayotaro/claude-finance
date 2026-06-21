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

FORBIDDEN_FLAGS = ("--full" + "-auto", "--" + "yolo")
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
    "implement": PhaseConfig("implement", "workspace-write", "result.md"),
    "review": PhaseConfig("review", "read-only", "review.md"),
}


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


def read_required(path: Path) -> str:
    """Read a required non-empty UTF-8 text file."""

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise HandoffError(f"Missing required file: {path}") from exc
    if not text.strip():
        raise HandoffError(f"Required file is empty: {path}")
    return text


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
        prerequisites["Implementation result"] = read_required(task_dir / "result.md")
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


def git_metadata(project_root: Path) -> dict[str, str]:
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
        "--ask-for-approval",
        "never",
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


def write_metadata(
    task_dir: Path,
    phase: str,
    command: list[str],
    started_at: str,
    finished_at: str,
    exit_status: int,
    git_before: dict[str, str],
    git_after: dict[str, str],
) -> None:
    """Write phase metadata without raw prompts or secrets."""

    sanitized_command = [
        part if part not in {str(task_dir / PHASES[phase].output_name), "-"} else part
        for part in command
    ]
    metadata = {
        "phase": phase,
        "started_at": started_at,
        "finished_at": finished_at,
        "exit_status": exit_status,
        "command": sanitized_command,
        "git_before": git_before,
        "git_after": git_after,
    }
    (task_dir / f"{phase}.metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def execute_phase(phase: str, task_ref: str, project_root: Path) -> Path:
    """Run one Codex phase and return the output artifact path."""

    if phase not in PHASES:
        raise HandoffError(f"Unsupported phase: {phase}")

    project_root = project_root.resolve()
    task_dir = resolve_task_dir(task_ref, project_root)
    brief = read_required(task_dir / "brief.md")
    ensure_no_network_requirement(brief)
    prerequisites = phase_prerequisites(phase, task_dir, brief)

    output_path = task_dir / PHASES[phase].output_name
    event_log_path = task_dir / f"codex-{phase}.events.jsonl"
    prompt = prompt_for_phase(phase, brief, prerequisites)
    command = build_codex_command(phase, project_root, output_path)

    started_at = utc_now()
    git_before = git_metadata(project_root)
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
        raise HandoffError(f"Failed to execute Codex: {exc}") from exc
    finished_at = utc_now()
    git_after = git_metadata(project_root)

    event_log_path.write_text(result.stdout, encoding="utf-8")
    if result.stderr.strip():
        (task_dir / f"codex-{phase}.stderr.txt").write_text(
            result.stderr,
            encoding="utf-8",
        )
    write_metadata(
        task_dir,
        phase,
        command,
        started_at,
        finished_at,
        result.returncode,
        git_before,
        git_after,
    )

    if result.returncode != 0:
        raise HandoffError(f"Codex {phase} failed with exit status {result.returncode}")
    if not output_path.exists() or not output_path.read_text(encoding="utf-8").strip():
        raise HandoffError(f"Codex {phase} produced no final output: {output_path}")
    return output_path


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse CLI arguments."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=sorted(PHASES))
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
        output_path = execute_phase(args.phase, args.task, Path(args.project_root))
    except HandoffError as exc:
        print(f"codex_handoff: {exc}", file=sys.stderr)
        return 2
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
