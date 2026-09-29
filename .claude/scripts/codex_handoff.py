#!/usr/bin/env python3
"""Run isolated Codex phases for Claude-managed tasks.

Claude implements repository changes; Codex provides independent reviews and,
optionally, plans or delegated implementations. The runner is intentionally
stdlib-only so hooks and skills can depend on it without adding runtime
dependencies.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping
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
VALID_EFFORTS = frozenset({"minimal", "low", "medium", "high", "xhigh"})
EFFORT_RANK = {
    "minimal": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
    "xhigh": 4,
}
DEFAULT_EFFORT_BY_TIER = {
    "T0": "medium",
    "T1": "medium",
    "T2": "high",
    "T3": "xhigh",
}
REVIEW_SCOPES = ("full", "delta")
REVIEW_SCOPE_NAME = "review-scope.md"
T3_DELTA_REVIEW_EFFORT = "high"
REVIEW_VALIDATION_NAME = "review-validation.md"
VALIDATION_TIMEOUT_SECONDS = 900
VALIDATION_OUTPUT_TAIL_CHARS = 4000
FENCE_OPEN_RE = re.compile(r"^\s*(?P<ticks>`{3,}|~{3,})\s*(?P<lang>[\w+-]*)\s*$")
HEADING_RE = re.compile(r"^\s{0,3}(?P<hashes>#{1,6})\s+(?P<title>.*?)\s*#*\s*$")
VALIDATION_FENCE_LANGUAGES = frozenset({"bash", "sh"})
UNFENCED_COMMAND_RE = re.compile(r"^(?:uv|git|pytest|ruff|mypy|python3?)\s")
SHELL_METACHARACTERS = frozenset(";&|<>`$\n")
# Defense in depth on top of the per-command argument allowlist: no live-trading
# form or credential file reference may appear anywhere in a validation command.
LIVE_TOKEN_RE = re.compile(
    r"(?i)\bBOT_MODE\b|\bBOT_ENVIRONMENT\b|(?<![\w-])--live\b|--mode\b|--env-file\b|\.env\b"
)
POSITIONAL_ARG_RE = re.compile(r"^[A-Za-z0-9_.][A-Za-z0-9_./:\[\]~^@=*-]*$")
PYTEST_TB_STYLES = frozenset({"auto", "long", "short", "line", "native", "no"})


@dataclass(frozen=True)
class ValidationCommandSpec:
    """Allowed shape of one runner-executed validation command."""

    prefix: tuple[str, ...]
    flags: frozenset[str] = frozenset()
    value_flags: frozenset[str] = frozenset()
    positionals: bool = True


_PYTEST_FLAGS = frozenset({"-q", "-qq", "-v", "-vv", "-x", "--no-header", "--strict-markers"})
_PYTEST_VALUE_FLAGS = frozenset({"-m", "-k", "--tb", "-p"})
_RUFF_FLAGS = frozenset({"--no-cache", "--quiet", "-q", "--statistics"})
_MYPY_FLAGS = frozenset({"--strict", "--no-incremental", "--pretty"})
_GIT_DIFF_FLAGS = frozenset(
    {
        "--check",
        "--stat",
        "--name-only",
        "--name-status",
        "--cached",
        "--staged",
        "--exit-code",
        "--",
    }
)
_GIT_STATUS_FLAGS = frozenset({"--short", "-s", "--porcelain", "--branch", "-b", "--"})

# Validation commands the runner may execute outside the Codex sandbox. Each
# command must match a prefix and then use only the listed options and
# repository-relative positional arguments. Commands run without a shell, so no
# environment assignment, pipe, redirection, or chained command can reach them.
VALIDATION_COMMAND_SPECS: tuple[ValidationCommandSpec, ...] = (
    ValidationCommandSpec(
        ("uv", "run", "--extra", "dev", "python", "-m", "pytest"),
        _PYTEST_FLAGS,
        _PYTEST_VALUE_FLAGS,
    ),
    ValidationCommandSpec(
        ("uv", "run", "--extra", "dev", "pytest"), _PYTEST_FLAGS, _PYTEST_VALUE_FLAGS
    ),
    ValidationCommandSpec(("uv", "run", "pytest"), _PYTEST_FLAGS, _PYTEST_VALUE_FLAGS),
    ValidationCommandSpec(("uv", "run", "--extra", "dev", "ruff", "check"), _RUFF_FLAGS),
    ValidationCommandSpec(("uv", "run", "ruff", "check"), _RUFF_FLAGS),
    ValidationCommandSpec(("uv", "run", "--extra", "dev", "mypy"), _MYPY_FLAGS),
    ValidationCommandSpec(("uv", "run", "mypy"), _MYPY_FLAGS),
    ValidationCommandSpec(
        ("uv", "run", "python", "-m", "src.orchestrator.registry", "audit"), positionals=False
    ),
    ValidationCommandSpec(("git", "diff"), _GIT_DIFF_FLAGS),
    ValidationCommandSpec(("git", "status"), _GIT_STATUS_FLAGS),
)


class HandoffError(RuntimeError):
    """Raised for invalid handoff state or Codex execution failure."""


@dataclass(frozen=True)
class PhaseConfig:
    """Codex execution settings for a handoff phase."""

    name: str
    sandbox: str
    output_name: str


@dataclass(frozen=True)
class ModelEffortSelection:
    """Resolved Codex model and reasoning-effort selection for one phase."""

    requested_model: str | None
    resolved_model: str | None
    requested_effort: str | None
    resolved_effort: str | None
    selection_source: dict[str, str]


PHASES: dict[str, PhaseConfig] = {
    "plan": PhaseConfig("plan", "read-only", "plan.md"),
    "implement": PhaseConfig("implement", "workspace-write", "implementation-result.md"),
    "review": PhaseConfig("review", "read-only", "review.md"),
}
PHASE_MODEL_ENV = {
    "plan": "CODEX_PLAN_MODEL",
    "implement": "CODEX_IMPLEMENT_MODEL",
    "review": "CODEX_REVIEW_MODEL",
}
PHASE_EFFORT_ENV = {
    "plan": "CODEX_PLAN_EFFORT",
    "implement": "CODEX_IMPLEMENT_EFFORT",
    "review": "CODEX_REVIEW_EFFORT",
}
LIFECYCLE_COMMANDS = frozenset({"status", "collect", "cancel"})
COMMANDS = frozenset(PHASES) | LIFECYCLE_COMMANDS

GitMetadata = dict[str, str]
HandoffState = dict[str, object]


def selection_state_fields(selection: ModelEffortSelection | None) -> HandoffState:
    """Return additive state/event fields for model and effort selection."""

    if selection is None:
        return {
            "requested_model": None,
            "resolved_model": None,
            "requested_effort": None,
            "resolved_effort": None,
            "selection_source": {
                "model": "not_applicable",
                "effort": "not_applicable",
            },
        }

    return {
        "requested_model": selection.requested_model,
        "resolved_model": selection.resolved_model,
        "requested_effort": selection.requested_effort,
        "resolved_effort": selection.resolved_effort,
        "selection_source": dict(selection.selection_source),
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
    selection: ModelEffortSelection | None = None,
    review_scope: str | None = None,
) -> HandoffState:
    """Create a complete state object."""

    state: HandoffState = {
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
        "review_scope": review_scope,
    }
    state.update(selection_state_fields(selection))
    return state


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


def non_empty(value: str | None) -> str | None:
    """Return stripped text, treating empty strings as missing."""

    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def validate_effort(effort: str, source: str) -> None:
    """Reject unsupported model reasoning efforts."""

    if effort not in VALID_EFFORTS:
        valid = ", ".join(sorted(VALID_EFFORTS))
        raise HandoffError(f"Invalid Codex effort from {source}: {effort!r}. Valid values: {valid}")


def validate_review_scope(phase: str, review_scope: str | None) -> None:
    """Reject review scopes on non-review phases and unknown scope values."""

    if review_scope is None:
        return
    if phase != "review":
        raise HandoffError(f"--scope applies only to the review phase, not {phase}")
    if review_scope not in REVIEW_SCOPES:
        raise HandoffError(
            f"Invalid review scope: {review_scope!r}. Valid values: {', '.join(REVIEW_SCOPES)}"
        )


def phase_uses_read_only_sandbox(phase: str) -> bool:
    """Return whether a phase uses a read-only sandbox."""

    return PHASES[phase].sandbox == "read-only"


def resolve_model_effort(
    phase: str,
    tier: str,
    cli_model: str | None,
    cli_effort: str | None,
    environ: Mapping[str, str],
    review_scope: str | None = None,
) -> ModelEffortSelection:
    """Resolve Codex model and reasoning effort for a phase.

    T3 phases require `xhigh` effort, except delta reviews, which require at
    least `high`. A lower CLI effort is a deliberate operator override.
    """

    if phase not in PHASES:
        raise HandoffError(f"Unsupported phase: {phase}")

    tier = tier.upper()
    if tier not in DEFAULT_EFFORT_BY_TIER:
        raise HandoffError(f"Unsupported risk tier for Codex effort selection: {tier}")
    validate_review_scope(phase, review_scope)
    is_delta_review = phase == "review" and review_scope == "delta"

    model = non_empty(cli_model)
    model_source = "cli"
    if model is None:
        phase_model = non_empty(environ.get(PHASE_MODEL_ENV[phase]))
        if phase_model is not None:
            model = phase_model
            model_source = "phase_env"
        else:
            general_model = non_empty(environ.get("CODEX_MODEL"))
            if general_model is not None:
                model = general_model
                model_source = "general_env"
            elif tier == "T0" and phase_uses_read_only_sandbox(phase):
                fast_model = non_empty(environ.get("CODEX_FAST_MODEL"))
                if fast_model is not None:
                    model = fast_model
                    model_source = "fast_env"
                else:
                    model_source = "omitted"
            else:
                model_source = "omitted"

    effort = non_empty(cli_effort)
    effort_source = "cli"
    if effort is None:
        phase_effort = non_empty(environ.get(PHASE_EFFORT_ENV[phase]))
        if phase_effort is not None:
            effort = phase_effort
            effort_source = "phase_env"
        else:
            general_effort = non_empty(environ.get("CODEX_EFFORT"))
            if general_effort is not None:
                effort = general_effort
                effort_source = "general_env"
            else:
                effort = DEFAULT_EFFORT_BY_TIER[tier]
                if tier == "T3" and is_delta_review:
                    effort = T3_DELTA_REVIEW_EFFORT
                effort_source = "default_matrix"

    validate_effort(effort, effort_source)

    t3_floor = T3_DELTA_REVIEW_EFFORT if is_delta_review else "xhigh"
    if tier == "T3" and effort_source != "cli" and EFFORT_RANK[effort] < EFFORT_RANK[t3_floor]:
        raise HandoffError(
            f"T3 {phase} requires at least {t3_floor} Codex effort unless deliberately "
            "overridden by CLI"
        )

    return ModelEffortSelection(
        requested_model=model,
        resolved_model=model,
        requested_effort=effort,
        resolved_effort=effort,
        selection_source={"model": model_source, "effort": effort_source},
    )


def ensure_no_network_requirement(brief: str) -> None:
    """Fail closed when a task declares that network access is required."""

    if NETWORK_REQUIRED_RE.search(brief):
        raise HandoffError(
            "Task declares network access is required. The handoff runner does not enable "
            "network by default; obtain explicit handling before running Codex."
        )


def phase_prerequisites(
    phase: str,
    task_dir: Path,
    brief: str,
    review_scope: str | None = None,
) -> dict[str, str]:
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
        plan_path = task_dir / "plan.md"
        if plan_path.exists():
            prerequisites["Plan"] = read_required(plan_path)
        prerequisites["Implementation result"] = read_required(
            task_dir / PHASES["implement"].output_name
        )
        if review_scope == "delta":
            prerequisites["Delta review scope"] = read_required(task_dir / REVIEW_SCOPE_NAME)
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


def validation_fence_lines(brief: str) -> list[str]:
    """Return the lines of every bash fence under a `## Required Validation` heading.

    Headings inside fences are not section boundaries, fences may be indented,
    and every Required Validation section is scanned so a duplicate heading
    cannot hide a command. Unsupported formatting fails closed: a non-bash
    fence, an unterminated fence, or a bare command line outside a fence.
    """

    in_section = False
    fence_ticks: str | None = None
    fence_in_section = False
    lines: list[str] = []
    for line in brief.splitlines():
        stripped = line.strip()
        if fence_ticks is not None:
            if stripped and set(stripped) == {fence_ticks[0]} and len(stripped) >= len(fence_ticks):
                fence_ticks = None
            elif fence_in_section:
                lines.append(stripped)
            continue

        opener = FENCE_OPEN_RE.match(line)
        if opener is not None:
            fence_ticks = opener.group("ticks")
            fence_in_section = in_section
            if in_section and opener.group("lang").casefold() not in VALIDATION_FENCE_LANGUAGES:
                raise HandoffError(
                    "Required Validation fences must be bash or sh: "
                    f"{opener.group('lang') or '(no language)'}"
                )
            continue

        heading = HEADING_RE.match(line)
        if heading is not None and len(heading.group("hashes")) <= 2:
            in_section = (
                len(heading.group("hashes")) == 2
                and heading.group("title").casefold() == "required validation"
            )
            continue

        if in_section and UNFENCED_COMMAND_RE.match(stripped):
            raise HandoffError(f"Validation command outside a bash fence: {stripped}")
        if in_section and (stripped.startswith(">") or "```" in stripped or "~~~" in stripped):
            raise HandoffError(
                "Unsupported Required Validation formatting (blockquote or inline fence): "
                f"{stripped}"
            )

    if fence_ticks is not None and fence_in_section:
        raise HandoffError("Unterminated fence in Required Validation")
    return lines


def _validate_command_arguments(spec: ValidationCommandSpec, args: list[str], text: str) -> None:
    """Reject any argument outside the spec's option allowlist or path shape."""

    index = 0
    while index < len(args):
        arg = args[index]
        if arg in spec.flags:
            index += 1
            continue
        flag, has_inline, inline_value = arg.partition("=")
        if flag in spec.value_flags:
            if has_inline and flag.startswith("--"):
                value = inline_value
                index += 1
            elif not has_inline and index + 1 < len(args):
                value = args[index + 1]
                index += 2
            else:
                raise HandoffError(f"Validation option needs a value: {text}")
            if flag == "--tb" and value not in PYTEST_TB_STYLES:
                raise HandoffError(f"Validation option value is not allowed: {text}")
            if flag == "-p" and not value.startswith("no:"):
                raise HandoffError(f"Validation plugin option is not allowed: {text}")
            continue
        if arg.startswith("-") or not spec.positionals:
            raise HandoffError(f"Validation argument is not allowlisted: {arg} in {text}")
        if not POSITIONAL_ARG_RE.match(arg) or ".." in Path(arg).parts:
            raise HandoffError(f"Validation path argument is not allowed: {arg} in {text}")
        index += 1


def required_validation_commands(brief: str) -> list[list[str]]:
    """Return allowlisted commands from bash fences in the brief's Required Validation.

    Raises HandoffError for any command outside the allowlist so an unexpected
    command fails the review closed instead of being skipped silently.
    """

    commands: list[list[str]] = []
    for text in validation_fence_lines(brief):
        if not text or text.startswith("#"):
            continue
        if any(char in SHELL_METACHARACTERS for char in text):
            raise HandoffError(f"Validation command uses shell syntax: {text}")
        if LIVE_TOKEN_RE.search(text):
            raise HandoffError(f"Validation command references live trading or credentials: {text}")
        try:
            tokens = shlex.split(text)
        except ValueError as exc:
            raise HandoffError(f"Validation command cannot be parsed: {text}") from exc
        spec = next(
            (
                candidate
                for candidate in VALIDATION_COMMAND_SPECS
                if tuple(tokens[: len(candidate.prefix)]) == candidate.prefix
            ),
            None,
        )
        if spec is None:
            raise HandoffError(f"Validation command is not allowlisted: {text}")
        _validate_command_arguments(spec, tokens[len(spec.prefix) :], text)
        commands.append(tokens)
    return commands


def run_validation_commands(commands: list[list[str]], project_root: Path) -> str:
    """Run validation commands and return a Markdown evidence report."""

    lines = [
        "# Runner validation evidence",
        "",
        "Executed by `codex_handoff.py` before the review, outside the Codex sandbox.",
        "",
    ]
    for tokens in commands:
        display = shlex.join(tokens)
        try:
            result = subprocess.run(
                tokens,
                cwd=project_root,
                capture_output=True,
                text=True,
                check=False,
                timeout=VALIDATION_TIMEOUT_SECONDS,
            )
            status = f"exit {result.returncode}"
            output = (result.stdout + result.stderr).strip()
        except subprocess.TimeoutExpired:
            status = f"timeout after {VALIDATION_TIMEOUT_SECONDS}s"
            output = ""
        except OSError as exc:
            status = f"failed to start: {exc}"
            output = ""
        tail = output[-VALIDATION_OUTPUT_TAIL_CHARS:]
        lines.extend([f"## `{display}`", "", f"Result: {status}", "", "```text", tail, "```", ""])
    return "\n".join(lines)


def archive_previous_review(task_dir: Path) -> Path | None:
    """Move an existing review.md to the next free review-<n>.md."""

    current = phase_result_path("review", task_dir)
    if not current.exists():
        return None
    index = 1
    while (task_dir / f"review-{index}.md").exists():
        index += 1
    archived = task_dir / f"review-{index}.md"
    current.rename(archived)
    return archived


def build_codex_command(
    phase: str,
    project_root: Path,
    output_path: Path,
    selection: ModelEffortSelection,
) -> list[str]:
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

    if selection.requested_model is not None:
        command.extend(["--model", selection.requested_model])

    if selection.requested_effort is not None:
        command.extend(["-c", f'model_reasoning_effort="{selection.requested_effort}"'])

    command.append("-")
    joined = " ".join(command)
    if any(flag in joined for flag in FORBIDDEN_FLAGS):
        raise HandoffError(f"Forbidden Codex flag present in command: {joined}")
    return command


def prompt_for_phase(phase: str, brief: str, prerequisites: dict[str, str]) -> str:
    """Assemble a phase prompt for Codex."""

    common = """You are Codex, working with Claude on this financial trading repository.
Claude implements changes; you provide plans or independent reviews as requested.

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
        contract = REVIEW_CONTRACT
    else:
        raise HandoffError(f"Unsupported phase: {phase}")

    sections = [common, contract, "## Task Brief\n\n" + brief.strip()]
    for title, body in prerequisites.items():
        sections.append(f"## {title}\n\n{body.strip()}")
    return "\n\n".join(sections) + "\n"


REVIEW_CONTRACT = """Review the current repository and diff as a fresh independent reviewer.

Do not rely on any implementation transcript. You may read only the brief, plan (if any),
implementation result artifact, delta review scope (if any), repository, and diff.
Do not modify repository files. The sandbox is read-only, so commands that write caches or
temp files may fail; the runner already executed the brief's Required Validation commands
and includes their output as "Runner validation evidence" when present. Treat a failing
runner validation command as a blocking finding.

Classify every finding:
- Severity: Critical, High, Medium, or Low.
- Disposition: blocking or follow-up. A finding is blocking if and only if its severity
  is Critical or High, or it directly violates a stated acceptance criterion, or a
  required validation command fails, or it weakens a financial safeguard (look-ahead
  bias, costs/slippage, IS/OOS separation, risk controls, UTC handling, numerical
  precision). Everything else is follow-up.
- Origin: new, or carried (restates a finding from the previous review round).

Verdict: CHANGES_REQUIRED if and only if at least one blocking finding exists;
otherwise APPROVE. Follow-ups never block.

If a delta review scope is provided, review only the listed findings and regressions in
the files touched by the corrections. Report anything outside that scope only if it is
blocking.

Process note: Claude stops the review loop after the third CHANGES_REQUIRED verdict in a
task and escalates to the user. This does not change how you classify findings.

Your output must include:
- Verdict: APPROVE or CHANGES_REQUIRED
- Blocking findings with severity, origin, and file and line references
- Follow-ups with severity, origin, and file and line references
- Acceptance-criteria gaps
- Validation evidence reviewed (runner evidence and any read-only checks you ran)
- Residual financial, operational, security, and regression risks
"""


def finish_phase_state(
    task_dir: Path,
    phase: str,
    started_at: str,
    status: str,
    exit_code: int | None,
    git_before: GitMetadata,
    git_after: GitMetadata,
    result_path: str,
    selection: ModelEffortSelection | None,
    error: str | None = None,
    review_scope: str | None = None,
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
        selection=selection,
        review_scope=review_scope,
    )
    write_state(task_dir, state)

    marker_extra: HandoffState = {"result_path": result_path, "review_scope": review_scope}
    if exit_code is not None:
        marker_extra["exit_code"] = exit_code
    if error is not None:
        marker_extra["error"] = error
    marker_extra.update(selection_state_fields(selection))
    append_event_marker(task_dir, phase, "finished", status, marker_extra)


def start_phase_state(
    task_dir: Path,
    phase: str,
    started_at: str,
    git_before: GitMetadata,
    result_path: str,
    selection: ModelEffortSelection,
    review_scope: str | None = None,
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
        selection=selection,
        review_scope=review_scope,
    )
    write_state(task_dir, state)
    marker_extra: HandoffState = {
        "pid": os.getpid(),
        "result_path": result_path,
        "review_scope": review_scope,
    }
    marker_extra.update(selection_state_fields(selection))
    append_event_marker(
        task_dir,
        phase,
        "started",
        "running",
        marker_extra,
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


def execute_phase(
    phase: str,
    task_ref: str,
    project_root: Path,
    cli_model: str | None = None,
    cli_effort: str | None = None,
    review_scope: str | None = None,
) -> Path:
    """Run one Codex phase and return the output artifact path."""

    if phase not in PHASES:
        raise HandoffError(f"Unsupported phase: {phase}")
    if phase == "review" and review_scope is None:
        review_scope = "full"

    project_root = project_root.resolve()
    task_dir = resolve_task_dir(task_ref, project_root)
    brief = read_required(task_dir / "brief.md")
    tier = risk_tier(brief)
    if tier is None:
        raise HandoffError("Brief must include a Risk Tier section before running Codex")
    selection = resolve_model_effort(
        phase, tier, cli_model, cli_effort, os.environ, review_scope=review_scope
    )
    output_path = phase_result_path(phase, task_dir)
    result_path = project_relative_path(output_path, project_root)
    if phase == "review":
        archive_previous_review(task_dir)
    started_at = utc_now()
    git_before = git_metadata(project_root)

    start_phase_state(task_dir, phase, started_at, git_before, result_path, selection, review_scope)

    try:
        ensure_no_network_requirement(brief)
        prerequisites = phase_prerequisites(phase, task_dir, brief, review_scope)
        if phase == "review":
            validation_commands = required_validation_commands(brief)
            if validation_commands:
                evidence = run_validation_commands(validation_commands, project_root)
                (task_dir / REVIEW_VALIDATION_NAME).write_text(evidence, encoding="utf-8")
                prerequisites["Runner validation evidence"] = evidence
        prompt = prompt_for_phase(phase, brief, prerequisites)
        command = build_codex_command(phase, project_root, output_path, selection)
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
            selection=selection,
            error=str(exc),
            review_scope=review_scope,
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
            selection=selection,
            error=error,
            review_scope=review_scope,
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
            selection=selection,
            error=error,
            review_scope=review_scope,
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
            selection=selection,
            error=error,
            review_scope=review_scope,
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
        selection=selection,
        review_scope=review_scope,
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
    parser.add_argument(
        "--model",
        default=None,
        help="Codex model override for phase commands.",
    )
    parser.add_argument(
        "--effort",
        default=None,
        help="Codex reasoning effort override for phase commands.",
    )
    parser.add_argument(
        "--scope",
        default=None,
        choices=REVIEW_SCOPES,
        help="Review scope: full (default) or delta (requires review-scope.md).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""

    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if args.scope is not None and args.command != "review":
            raise HandoffError(f"--scope applies only to the review phase, not {args.command}")
        project_root = Path(args.project_root)
        if args.command == "status":
            output_path = print_status(args.task, project_root, sys.stdout)
        elif args.command == "collect":
            output_path = collect_result(args.task, project_root, sys.stdout)
        elif args.command == "cancel":
            output_path = cancel_task(args.task, project_root)
        else:
            output_path = execute_phase(
                args.command,
                args.task,
                project_root,
                cli_model=args.model,
                cli_effort=args.effort,
                review_scope=args.scope,
            )
    except HandoffError as exc:
        print(f"codex_handoff: {exc}", file=sys.stderr)
        return 2
    if args.command not in {"status", "collect"}:
        print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
