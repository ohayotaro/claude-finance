from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_update_script_migrates_legacy_paths_and_preserves_state(tmp_path: Path) -> None:
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

    result = subprocess.run(
        ["bash", str(ROOT / "scripts" / "update.sh")],
        cwd=project,
        env={"TEMPLATE_SOURCE_DIR": str(template)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
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
    assert (project / ".claude" / "docs" / "DESIGN.local-preserved.md").read_text(
        encoding="utf-8"
    ) == "local design"
