from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]


def _scaffold_update_project(tmp_path: Path) -> tuple[Path, Path]:
    template = tmp_path / "template"
    project = tmp_path / "project"
    shutil.copytree(ROOT, template, ignore=shutil.ignore_patterns(".git", ".venv", ".pytest_cache"))
    project.mkdir()

    (project / ".claude" / "agents").mkdir(parents=True)
    (project / ".claude" / "agents" / "old.md").write_text("old", encoding="utf-8")
    (project / ".claude" / "tasks" / "task-1").mkdir(parents=True)
    (project / ".claude" / "tasks" / "task-1" / "brief.md").write_text("keep", encoding="utf-8")
    (project / ".claude" / "logs").mkdir(parents=True)
    (project / ".claude" / "logs" / "keep.log").write_text("keep", encoding="utf-8")
    (project / ".claude" / "routing-keywords.json").write_text("{}", encoding="utf-8")
    (project / ".gemini").mkdir()
    (project / ".gemini" / "settings.json").write_text("{}", encoding="utf-8")
    (project / ".codex").mkdir()
    (project / ".codex" / "config.toml").write_text("old = true\n", encoding="utf-8")
    (project / ".claude" / "backtest-thresholds.json").write_text(
        '{"custom": true}\n',
        encoding="utf-8",
    )
    (project / ".claude" / "docs").mkdir(exist_ok=True)
    (project / ".claude" / "docs" / "DESIGN.md").write_text("local design", encoding="utf-8")

    (project / "CLAUDE.md").write_text(
        """# Old
@orchestra:template-boundary

## Project Identity
custom zone

@orchestra:repo-boundary
old context
""",
        encoding="utf-8",
    )
    (project / "AGENTS.md").write_text(
        """# Old
@codex:template-boundary

## Project-Specific Codex Notes
custom codex notes

@codex:repo-boundary
""",
        encoding="utf-8",
    )
    return template, project


def _assert_update_migrated_legacy_paths_and_preserved_state(project: Path) -> None:
    assert not (project / ".claude" / "agents").exists()
    assert not (project / ".gemini").exists()
    assert not (project / ".claude" / "routing-keywords.json").exists()
    assert (project / ".claude" / "tasks" / "task-1" / "brief.md").read_text(
        encoding="utf-8"
    ) == "keep"
    assert (project / ".claude" / "logs" / "keep.log").read_text(encoding="utf-8") == "keep"
    assert "custom zone" in (project / "CLAUDE.md").read_text(encoding="utf-8")
    assert "custom codex notes" in (project / "AGENTS.md").read_text(encoding="utf-8")
    assert (project / ".claude" / "backtest-thresholds.json").read_text(
        encoding="utf-8"
    ) == '{"custom": true}\n'


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash is unavailable")
def test_update_sh_migrates_legacy_paths_and_preserves_state(tmp_path: Path) -> None:
    template, project = _scaffold_update_project(tmp_path)
    result = subprocess.run(
        ["bash", str(ROOT / "scripts" / "update.sh")],
        cwd=project,
        env={**os.environ, "TEMPLATE_SOURCE_DIR": str(template)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    _assert_update_migrated_legacy_paths_and_preserved_state(project)
    design_content = b"local design"
    design_digest = hashlib.sha256(design_content).hexdigest()
    design_archive = (
        project
        / ".claude"
        / "docs"
        / f"DESIGN.local-preserved.sha256-{design_digest}.md"
    )
    assert design_archive.read_bytes() == design_content
    assert not (project / ".claude" / "docs" / "DESIGN.local-preserved.md").exists()
    assert "old context" in (project / "CLAUDE.md").read_text(encoding="utf-8")


def test_update_py_migrates_legacy_paths_and_preserves_state(tmp_path: Path) -> None:
    template, project = _scaffold_update_project(tmp_path)
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "update.py")],
        cwd=project,
        env={**os.environ, "TEMPLATE_SOURCE_DIR": str(template)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    _assert_update_migrated_legacy_paths_and_preserved_state(project)
    assert (project / ".claude" / "docs" / "DESIGN.local-preserved.md").read_text(
        encoding="utf-8"
    ) == "local design"
