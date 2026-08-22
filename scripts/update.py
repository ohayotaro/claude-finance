"""Refresh the Financial Trading AI Orchestrator template in an existing project.

The update does not touch user project code.

Usage:
    python3 scripts/update.py
    TEMPLATE_SOURCE_DIR=/path/to/template python3 scripts/update.py

Safety contract:
    CLAUDE.md and AGENTS.md must exist in both the downstream project and the
    incoming template. Each contract must contain exactly one full-line start
    marker and one full-line repository marker, in that order. Missing,
    duplicated, or misordered markers cause a non-zero exit before any
    template-managed project content is replaced. If a later replacement
    fails, private recovery copies are retained and their path is printed.

    Contract composition is byte-preserving: the template prefix and
    repository-marker line surround the local project section and local
    post-boundary content.

    A differing local DESIGN.md is preserved in a content-addressed archive.
    The updater stages protected content in a private temporary directory and
    replaces only the three explicitly managed updater files under scripts/.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

DEFAULT_REPO_URL = "https://github.com/ohayotaro/claude-finance.git"

CLAUDE_START_MARKER = b"@orchestra:template-boundary"
CLAUDE_REPO_MARKER = b"@orchestra:repo-boundary"
AGENTS_START_MARKER = b"@codex:template-boundary"
AGENTS_REPO_MARKER = b"@codex:repo-boundary"

TEMPLATE_DIRS_IN_CLAUDE = ("hooks", "rules", "skills", "scripts")
TEMPLATE_FILES_IN_CLAUDE = (
    Path("settings.json"),
    Path("backtest-thresholds.json"),
    Path("docs/CODEX_TASK_CONTRACT.md"),
    Path("docs/DESIGN.md"),
)
SELF_UPDATE_PATHS = (
    Path("scripts/update.py"),
    Path("scripts/validate_update_preservation.sh"),
    Path("scripts/update.sh"),
)
RECOVERY_PATHS = (
    Path("CLAUDE.md"),
    Path("AGENTS.md"),
    Path(".claude/agents"),
    Path(".claude/routing-keywords.json"),
    Path(".gemini"),
    Path(".claude/hooks"),
    Path(".claude/rules"),
    Path(".claude/skills"),
    Path(".claude/scripts"),
    Path(".claude/settings.json"),
    Path(".claude/backtest-thresholds.json"),
    Path(".claude/docs/CODEX_TASK_CONTRACT.md"),
    Path(".claude/docs/DESIGN.md"),
    Path(".codex"),
    *SELF_UPDATE_PATHS,
)


class UpdateError(Exception):
    """Report a validation or update failure without a traceback."""


@dataclass(frozen=True)
class UpdatePlan:
    """Hold paths and staged data needed by the mutation phase."""

    project_root: Path
    template_root: Path
    work_dir: Path
    recovery_dir: Path
    staged_claude: Path
    staged_agents: Path
    staged_thresholds: Path | None
    staged_design: Path | None
    design_archive: Path | None
    staged_updaters: tuple[tuple[Path, Path], ...]


def _color(code: str, message: str) -> str:
    return f"\033[{code}m{message}\033[0m"


def _red(message: str) -> None:
    print(_color("31", message), file=sys.stderr)


def _green(message: str) -> None:
    print(_color("32", message))


def _yellow(message: str) -> None:
    print(_color("33", message))


def _exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _require_regular_file(path: Path) -> None:
    if not path.is_file() or path.is_symlink():
        raise UpdateError(f"Required regular file is missing or unsafe: {path}")


def _require_safe_directory(path: Path, message: str | None = None) -> None:
    if not path.is_dir() or path.is_symlink():
        raise UpdateError(message or f"Required safe directory is missing or unsafe: {path}")


def _validate_optional_file(path: Path, description: str) -> None:
    if _exists(path) and (not path.is_file() or path.is_symlink()):
        raise UpdateError(f"Unsafe {description} path: {path}")


def _validate_optional_directory(path: Path, description: str) -> None:
    if _exists(path) and (not path.is_dir() or path.is_symlink()):
        raise UpdateError(f"Unsafe {description} path: {path}")


def _line_content(line: bytes) -> bytes:
    if line.endswith(b"\r\n"):
        return line[:-2]
    if line.endswith((b"\n", b"\r")):
        return line[:-1]
    return line


def _marker_index(path: Path, lines: list[bytes], marker: bytes) -> int:
    indexes = [index for index, line in enumerate(lines) if _line_content(line) == marker]
    if len(indexes) != 1:
        marker_text = marker.decode("ascii")
        raise UpdateError(
            f"{path}: expected exactly one full-line marker {marker_text!r}; "
            f"found {len(indexes)}"
        )
    return indexes[0]


def _validated_contract(
    path: Path,
    start_marker: bytes,
    repo_marker: bytes,
) -> tuple[list[bytes], int, int]:
    lines = path.read_bytes().splitlines(keepends=True)
    start_index = _marker_index(path, lines, start_marker)
    repo_index = _marker_index(path, lines, repo_marker)
    if start_index >= repo_index:
        raise UpdateError(
            f"{path}: marker {start_marker.decode('ascii')!r} must precede "
            f"{repo_marker.decode('ascii')!r}"
        )
    return lines, start_index, repo_index


def _compose_contract(
    local_path: Path,
    template_path: Path,
    start_marker: bytes,
    repo_marker: bytes,
) -> bytes:
    local_lines, local_start, local_repo = _validated_contract(
        local_path, start_marker, repo_marker
    )
    template_lines, template_start, template_repo = _validated_contract(
        template_path, start_marker, repo_marker
    )
    return b"".join(
        template_lines[: template_start + 1]
        + local_lines[local_start + 1 : local_repo]
        + template_lines[template_repo : template_repo + 1]
        + local_lines[local_repo + 1 :]
    )


def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif _exists(path):
        path.unlink()


def _stage_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(source.read_bytes())
    with suppress(NotImplementedError, OSError):
        destination.chmod(stat.S_IMODE(source.stat().st_mode))


def _replace_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _copy_tree(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination)


def _template_root(work_dir: Path, project_root: Path) -> Path:
    source = os.environ.get("TEMPLATE_SOURCE_DIR")
    if source:
        template_root = Path(source).expanduser().resolve()
        _require_safe_directory(
            template_root,
            f"Template source is not a safe directory: {template_root}",
        )
        if template_root == project_root:
            raise UpdateError("Template source must differ from the downstream project root.")
        _yellow(f"Using local template source: {template_root}")
        return template_root

    template_root = work_dir / "template"
    repo_url = os.environ.get("TEMPLATE_REPO_URL", DEFAULT_REPO_URL)
    _yellow("Cloning latest template into private temporary storage")
    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", repo_url, str(template_root)],
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise UpdateError(f"Unable to clone template: {error}") from error
    return template_root


def _validate_template_paths(template_root: Path) -> None:
    template_claude = template_root / ".claude"
    _require_safe_directory(
        template_claude,
        f"Incoming template has no safe .claude/ directory: {template_claude}",
    )
    _require_regular_file(template_root / "CLAUDE.md")
    _require_regular_file(template_root / "AGENTS.md")

    for dirname in TEMPLATE_DIRS_IN_CLAUDE:
        _validate_optional_directory(
            template_claude / dirname,
            f"incoming template .claude/{dirname}",
        )
    for relative_path in TEMPLATE_FILES_IN_CLAUDE:
        _validate_optional_file(
            template_claude / relative_path,
            f"incoming template .claude/{relative_path.as_posix()}",
        )
    _validate_optional_directory(template_root / ".codex", "incoming template .codex")

    _require_safe_directory(
        template_root / "scripts",
        f"Incoming template has no safe scripts/ directory: {template_root / 'scripts'}",
    )
    for relative_path in SELF_UPDATE_PATHS:
        _require_regular_file(template_root / relative_path)


def _validate_project_targets(project_root: Path) -> None:
    _require_safe_directory(
        project_root / ".claude",
        "No safe .claude/ directory found. Run this from an installed project root.",
    )
    _require_regular_file(project_root / "CLAUDE.md")
    _require_regular_file(project_root / "AGENTS.md")
    _require_safe_directory(
        project_root / "scripts",
        "No safe scripts/ directory found. Run this from an installed project root.",
    )

    for dirname in TEMPLATE_DIRS_IN_CLAUDE:
        _validate_optional_directory(
            project_root / ".claude" / dirname,
            f"local .claude/{dirname}",
        )
    for relative_path in TEMPLATE_FILES_IN_CLAUDE:
        _validate_optional_file(
            project_root / ".claude" / relative_path,
            f"local .claude/{relative_path.as_posix()}",
        )
    _validate_optional_directory(project_root / ".codex", "local .codex")
    for relative_path in SELF_UPDATE_PATHS:
        _validate_optional_file(project_root / relative_path, f"local {relative_path.as_posix()}")


def _stage_thresholds(project_root: Path, staged_root: Path) -> Path | None:
    source = project_root / ".claude/backtest-thresholds.json"
    if not _exists(source):
        return None
    _validate_optional_file(source, "local threshold")
    destination = staged_root / "backtest-thresholds.json"
    _yellow("Staging .claude/backtest-thresholds.json")
    _stage_file(source, destination)
    return destination


def _stage_design(
    project_root: Path,
    template_root: Path,
    staged_root: Path,
) -> tuple[Path | None, Path | None]:
    docs_path = project_root / ".claude/docs"
    _validate_optional_directory(docs_path, "local .claude/docs")
    template_design = template_root / ".claude/docs/DESIGN.md"
    if not _exists(template_design):
        return None, None

    _require_regular_file(template_design)
    local_design = docs_path / "DESIGN.md"
    if not _exists(local_design):
        return None, None
    _validate_optional_file(local_design, "local DESIGN.md")

    local_bytes = local_design.read_bytes()
    if local_bytes == template_design.read_bytes():
        return None, None

    digest = hashlib.sha256(local_bytes).hexdigest()
    archive = docs_path / f"DESIGN.local-preserved.sha256-{digest}.md"
    if _exists(archive):
        _validate_optional_file(archive, "DESIGN.md archive")
        if archive.read_bytes() != local_bytes:
            raise UpdateError(f"DESIGN.md archive digest collision or content mismatch: {archive}")

    staged_design = staged_root / "DESIGN.md"
    staged_design.write_bytes(local_bytes)
    return staged_design, archive


def _backup_for_recovery(project_root: Path, recovery_dir: Path, relative_path: Path) -> None:
    source = project_root / relative_path
    if not _exists(source):
        absent = recovery_dir / "originally-absent.txt"
        with absent.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(f"{relative_path.as_posix()}\n")
        return

    destination = recovery_dir / "project" / relative_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir() and not source.is_symlink():
        shutil.copytree(source, destination, symlinks=True)
    else:
        shutil.copy2(source, destination, follow_symlinks=False)


def _create_recovery(plan: UpdatePlan) -> None:
    _yellow("Creating private recovery copies")
    paths = list(RECOVERY_PATHS)
    if plan.design_archive is not None:
        paths.append(plan.design_archive.relative_to(plan.project_root))
    for relative_path in paths:
        _backup_for_recovery(plan.project_root, plan.recovery_dir, relative_path)
    (plan.recovery_dir / "README.txt").write_text(
        "These files are private recovery copies from a failed template update.\n"
        "Copy only the needed paths back into the downstream project after inspection.\n",
        encoding="utf-8",
        newline="\n",
    )


def _prepare_update(project_root: Path, work_dir: Path) -> UpdatePlan:
    _validate_project_targets(project_root)
    template_root = _template_root(work_dir, project_root)
    _validate_template_paths(template_root)

    staged_root = work_dir / "staged"
    staged_root.mkdir()
    _yellow("Preflighting and staging protected contract sections")
    staged_claude = staged_root / "CLAUDE.md"
    staged_claude.write_bytes(
        _compose_contract(
            project_root / "CLAUDE.md",
            template_root / "CLAUDE.md",
            CLAUDE_START_MARKER,
            CLAUDE_REPO_MARKER,
        )
    )
    staged_agents = staged_root / "AGENTS.md"
    staged_agents.write_bytes(
        _compose_contract(
            project_root / "AGENTS.md",
            template_root / "AGENTS.md",
            AGENTS_START_MARKER,
            AGENTS_REPO_MARKER,
        )
    )

    staged_thresholds = _stage_thresholds(project_root, staged_root)
    staged_design, design_archive = _stage_design(project_root, template_root, staged_root)

    staged_updaters: list[tuple[Path, Path]] = []
    for relative_path in SELF_UPDATE_PATHS:
        staged_path = staged_root / relative_path
        _stage_file(template_root / relative_path, staged_path)
        staged_updaters.append((staged_path, project_root / relative_path))

    recovery_dir = work_dir / "recovery"
    (recovery_dir / "project").mkdir(parents=True)
    plan = UpdatePlan(
        project_root=project_root,
        template_root=template_root,
        work_dir=work_dir,
        recovery_dir=recovery_dir,
        staged_claude=staged_claude,
        staged_agents=staged_agents,
        staged_thresholds=staged_thresholds,
        staged_design=staged_design,
        design_archive=design_archive,
        staged_updaters=tuple(staged_updaters),
    )
    _create_recovery(plan)
    return plan


def _create_or_verify_design_archive(plan: UpdatePlan) -> None:
    if plan.staged_design is None or plan.design_archive is None:
        return

    archive = plan.design_archive
    expected = plan.staged_design.read_bytes()
    archive.parent.mkdir(parents=True, exist_ok=True)
    if not _exists(archive):
        try:
            with archive.open("xb") as handle:
                handle.write(expected)
        except FileExistsError:
            pass
    _validate_optional_file(archive, "DESIGN.md archive")
    if archive.read_bytes() != expected:
        raise UpdateError(f"DESIGN.md archive verification failed: {archive}")


def _best_effort_make_template_scripts_executable(project_root: Path) -> None:
    paths = [
        *(project_root / ".claude/hooks").glob("*.py"),
        *(project_root / ".claude/scripts").glob("*.py"),
    ]
    for path in paths:
        with suppress(NotImplementedError, OSError):
            path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _apply_update(plan: UpdatePlan) -> None:
    project_root = plan.project_root
    template_root = plan.template_root

    _yellow("Removing legacy provider and routing paths")
    for relative_path in (
        Path(".claude/agents"),
        Path(".claude/routing-keywords.json"),
        Path(".gemini"),
    ):
        _remove_path(project_root / relative_path)

    _yellow("Replacing template-managed .claude paths")
    for dirname in TEMPLATE_DIRS_IN_CLAUDE:
        source = template_root / ".claude" / dirname
        if source.is_dir():
            destination = project_root / ".claude" / dirname
            _remove_path(destination)
            _copy_tree(source, destination)

    _create_or_verify_design_archive(plan)
    for relative_path in TEMPLATE_FILES_IN_CLAUDE:
        source = template_root / ".claude" / relative_path
        if source.is_file():
            _replace_file(source, project_root / ".claude" / relative_path)

    _yellow("Replacing root contracts and Codex config")
    _replace_file(plan.staged_claude, project_root / "CLAUDE.md")
    _replace_file(plan.staged_agents, project_root / "AGENTS.md")
    template_codex = template_root / ".codex"
    if template_codex.is_dir():
        destination_codex = project_root / ".codex"
        _remove_path(destination_codex)
        _copy_tree(template_codex, destination_codex)

    if plan.staged_thresholds is not None:
        _replace_file(
            plan.staged_thresholds,
            project_root / ".claude/backtest-thresholds.json",
        )

    _best_effort_make_template_scripts_executable(project_root)

    _yellow("Updating updater entry points and preservation validator")
    for source, destination in plan.staged_updaters:
        _replace_file(source, destination)


def _make_private_work_dir() -> Path:
    work_dir = Path(tempfile.mkdtemp(prefix="claude-finance-update-"))
    with suppress(NotImplementedError, OSError):
        work_dir.chmod(stat.S_IRWXU)
    return work_dir


def main() -> int:
    """Run the staged template update from the current project root."""
    project_root = Path.cwd().resolve()
    work_dir = _make_private_work_dir()
    plan: UpdatePlan | None = None
    mutation_started = False
    succeeded = False
    try:
        plan = _prepare_update(project_root, work_dir)
        mutation_started = True
        _apply_update(plan)
        succeeded = True
    except (OSError, shutil.Error, UpdateError) as error:
        _red(f"ERROR: {error}")
        return 1
    except KeyboardInterrupt:
        _red("ERROR: Update interrupted.")
        return 130
    finally:
        if succeeded or not mutation_started:
            shutil.rmtree(work_dir, ignore_errors=True)
        elif plan is not None:
            _red("ERROR: Update failed after project replacement began.")
            _red(f"Recovery copies were retained at: {plan.recovery_dir}")

    _green("Update complete.")
    _yellow("Next steps:")
    print("  - Review changes: git diff")
    print("  - Run: uv sync --extra dev")
    print('  - Run: uv run --extra dev pytest -m "not integration and not slow"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
