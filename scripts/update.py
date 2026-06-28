"""Refresh the Financial Trading AI Orchestrator template in an existing project.

Usage:
    uv run python scripts/update.py
    TEMPLATE_SOURCE_DIR=/path/to/template uv run python scripts/update.py
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from contextlib import suppress
from pathlib import Path

REPO_URL = os.environ.get(
    "TEMPLATE_REPO_URL", "https://github.com/ohayotaro/claude-finance.git"
)
TMP_DIR = Path(".starter-update")
BACKUP_ZONE_B = Path(".zone-b.backup.md")
BACKUP_AGENTS_PROJECT = Path(".agents-project.backup.md")
BACKUP_THRESHOLDS = Path(".backtest-thresholds.backup.json")
BACKUP_DESIGN = Path(".design-local.backup.md")


def _color(code: str, message: str) -> str:
    return f"\033[{code}m{message}\033[0m"


def red(message: str) -> None:
    print(_color("31", message))


def green(message: str) -> None:
    print(_color("32", message))


def yellow(message: str) -> None:
    print(_color("33", message))


def require_file(path: str) -> None:
    if not Path(path).is_file():
        red(f"Missing {path} -- run this from an installed project root.")
        raise SystemExit(1)


def extract_between_markers(file: str, start: str, end: str, output: Path) -> None:
    path = Path(file)
    if not path.is_file():
        output.write_text("", encoding="utf-8")
        return

    in_zone = False
    lines: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if start in line:
            in_zone = True
            continue
        if end in line:
            in_zone = False
            continue
        if in_zone:
            lines.append(line)
    output.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def restore_between_markers(file: str, start: str, end: str, backup_path: Path) -> None:
    target = Path(file)
    if not backup_path.is_file() or backup_path.stat().st_size == 0 or not target.is_file():
        return

    backup = backup_path.read_text(encoding="utf-8")
    text = target.read_text(encoding="utf-8")
    start_index = text.find(start)
    end_index = text.find(end)
    if start_index == -1 or end_index == -1:
        print(f"[update.py] {target} missing boundary markers; restore skipped", file=sys.stderr)
        return
    start_eol = text.find("\n", start_index)
    if start_eol == -1:
        print(f"[update.py] {target} missing boundary newline; restore skipped", file=sys.stderr)
        return

    new_text = text[: start_eol + 1] + "\n" + backup.rstrip("\n") + "\n\n" + text[end_index:]
    target.write_text(new_text, encoding="utf-8")


def remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        with suppress(FileNotFoundError):
            path.unlink()


def copy_tree_if_exists(source: Path, target: Path) -> None:
    if source.is_dir():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, target)


def copy_file_if_exists(source: Path, target: Path) -> None:
    if source.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def make_template_scripts_executable() -> None:
    for path in [*Path(".claude/hooks").glob("*.py"), *Path(".claude/scripts").glob("*.py")]:
        try:
            path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        except OSError:
            continue


def main() -> int:
    if not Path(".claude").is_dir():
        red(
            "No .claude/ here. "
            "Run this from the project root that already has the template installed."
        )
        return 1
    require_file("CLAUDE.md")

    yellow("Backing up CLAUDE.md Zone B")
    extract_between_markers(
        "CLAUDE.md",
        "@orchestra:template-boundary",
        "@orchestra:repo-boundary",
        BACKUP_ZONE_B,
    )

    yellow("Backing up AGENTS.md project section")
    extract_between_markers(
        "AGENTS.md",
        "@codex:template-boundary",
        "@codex:repo-boundary",
        BACKUP_AGENTS_PROJECT,
    )

    if Path(".claude/backtest-thresholds.json").is_file():
        yellow("Backing up .claude/backtest-thresholds.json")
        shutil.copy2(".claude/backtest-thresholds.json", BACKUP_THRESHOLDS)

    if Path(".claude/docs/DESIGN.md").is_file():
        shutil.copy2(".claude/docs/DESIGN.md", BACKUP_DESIGN)

    template_source_dir = os.environ.get("TEMPLATE_SOURCE_DIR")
    if template_source_dir:
        template_dir = Path(template_source_dir)
        yellow(f"Using local template source: {template_dir}")
    else:
        yellow(f"Cloning latest template into {TMP_DIR}/")
        remove_path(TMP_DIR)
        subprocess.run(["git", "clone", "--depth", "1", REPO_URL, str(TMP_DIR)], check=True)
        template_dir = TMP_DIR

    yellow("Removing legacy provider and routing paths")
    remove_path(Path(".claude/agents"))
    remove_path(Path(".claude/routing-keywords.json"))
    remove_path(Path(".gemini"))

    template_dirs_in_claude = ("hooks", "rules", "skills", "scripts")
    template_files_in_claude = (
        "settings.json",
        "backtest-thresholds.json",
        "docs/CODEX_TASK_CONTRACT.md",
        "docs/DESIGN.md",
    )

    yellow("Replacing template-managed .claude paths")
    for dirname in template_dirs_in_claude:
        target = Path(".claude") / dirname
        remove_path(target)
        copy_tree_if_exists(template_dir / ".claude" / dirname, target)

    for filename in template_files_in_claude:
        copy_file_if_exists(template_dir / ".claude" / filename, Path(".claude") / filename)

    if BACKUP_DESIGN.is_file():
        Path(".claude/docs").mkdir(parents=True, exist_ok=True)
        shutil.copy2(BACKUP_DESIGN, ".claude/docs/DESIGN.local-preserved.md")

    yellow("Replacing root contracts and Codex config")
    shutil.copy2(template_dir / "CLAUDE.md", "CLAUDE.md")
    if (template_dir / "AGENTS.md").is_file():
        shutil.copy2(template_dir / "AGENTS.md", "AGENTS.md")
    remove_path(Path(".codex"))
    copy_tree_if_exists(template_dir / ".codex", Path(".codex"))

    yellow("Restoring preserved local sections")
    restore_between_markers(
        "CLAUDE.md",
        "@orchestra:template-boundary",
        "@orchestra:repo-boundary",
        BACKUP_ZONE_B,
    )
    restore_between_markers(
        "AGENTS.md",
        "@codex:template-boundary",
        "@codex:repo-boundary",
        BACKUP_AGENTS_PROJECT,
    )

    if BACKUP_THRESHOLDS.is_file():
        shutil.move(str(BACKUP_THRESHOLDS), ".claude/backtest-thresholds.json")

    make_template_scripts_executable()

    if not template_source_dir:
        remove_path(TMP_DIR)
    for backup in (BACKUP_ZONE_B, BACKUP_AGENTS_PROJECT, BACKUP_THRESHOLDS, BACKUP_DESIGN):
        remove_path(backup)

    green("Update complete.")
    yellow("Next steps:")
    print("  - Review changes: git diff")
    print("  - Run: uv sync --extra dev")
    print('  - Run: uv run --extra dev pytest -m "not integration and not slow"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
