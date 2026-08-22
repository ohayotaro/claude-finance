from __future__ import annotations

import hashlib
import importlib.util
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from types import ModuleType

ROOT = Path(__file__).parents[2]
PYTHON_UPDATER = ROOT / "scripts/update.py"
SHELL_UPDATER = ROOT / "scripts/update.sh"
SELF_UPDATE_PATHS = (
    Path("scripts/update.py"),
    Path("scripts/validate_update_preservation.sh"),
    Path("scripts/update.sh"),
)

CLAUDE_START = b"@orchestra:template-boundary"
CLAUDE_REPO = b"@orchestra:repo-boundary"
AGENTS_START = b"@codex:template-boundary"
AGENTS_REPO = b"@codex:repo-boundary"

TEMPLATE_CLAUDE_PREFIX = (
    b"# Incoming CLAUDE\r\n"
    b"Prose containing @orchestra:template-boundary is not a marker.\r\n"
    + CLAUDE_START
    + b"\r\n"
)
TEMPLATE_CLAUDE_REPO_LINE = CLAUDE_REPO + b"\r\n"
LOCAL_CLAUDE_ZONE = (
    b"Local Zone B one.\n"
    b"Embedded @orchestra:repo-boundary text remains content.\r\n"
)
LOCAL_CLAUDE_POST = (
    b"Local Zone C one.\r"
    b"Embedded @orchestra:template-boundary text remains content.\n"
    b"Local Zone C final without newline."
)
TEMPLATE_CLAUDE = (
    TEMPLATE_CLAUDE_PREFIX
    + b"Incoming Zone B.\n"
    + TEMPLATE_CLAUDE_REPO_LINE
    + b"Incoming Zone C."
)
LOCAL_CLAUDE = (
    b"# Local CLAUDE\n"
    + CLAUDE_START
    + b"\n"
    + LOCAL_CLAUDE_ZONE
    + CLAUDE_REPO
    + b"\r\n"
    + LOCAL_CLAUDE_POST
)
EXPECTED_CLAUDE = (
    TEMPLATE_CLAUDE_PREFIX + LOCAL_CLAUDE_ZONE + TEMPLATE_CLAUDE_REPO_LINE + LOCAL_CLAUDE_POST
)

TEMPLATE_AGENTS_PREFIX = (
    b"# Incoming AGENTS\n"
    b"Prose containing @codex:repo-boundary is not a marker.\n"
    + AGENTS_START
    + b"\n"
)
TEMPLATE_AGENTS_REPO_LINE = AGENTS_REPO + b"\n"
LOCAL_AGENTS_ZONE = b"Local project section.\r\nEmbedded @codex:repo-boundary remains content.\n"
LOCAL_AGENTS_POST = b"Local post-boundary section without newline."
TEMPLATE_AGENTS = (
    TEMPLATE_AGENTS_PREFIX
    + b"Incoming project section.\n"
    + TEMPLATE_AGENTS_REPO_LINE
    + b"Incoming tail.\n"
)
LOCAL_AGENTS = (
    b"# Local AGENTS\r\n"
    + AGENTS_START
    + b"\r\n"
    + LOCAL_AGENTS_ZONE
    + AGENTS_REPO
    + b"\n"
    + LOCAL_AGENTS_POST
)
EXPECTED_AGENTS = (
    TEMPLATE_AGENTS_PREFIX + LOCAL_AGENTS_ZONE + TEMPLATE_AGENTS_REPO_LINE + LOCAL_AGENTS_POST
)

ENTRY_POINTS = [
    pytest.param("python", id="python"),
    pytest.param(
        "shell",
        id="shell",
        marks=pytest.mark.skipif(shutil.which("bash") is None, reason="bash is unavailable"),
    ),
]


def _write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _make_template(root: Path) -> None:
    _write(root / "CLAUDE.md", TEMPLATE_CLAUDE)
    _write(root / "AGENTS.md", TEMPLATE_AGENTS)
    _write(root / ".claude/hooks/incoming.py", b"incoming hook\n")
    _write(root / ".claude/rules/incoming.md", b"incoming rule\n")
    _write(root / ".claude/skills/incoming.md", b"incoming skill\n")
    _write(root / ".claude/scripts/incoming.py", b"incoming script\n")
    _write(root / ".claude/settings.json", b'{"incoming": true}\n')
    _write(root / ".claude/backtest-thresholds.json", b'{"threshold": "incoming"}\n')
    _write(root / ".claude/docs/CODEX_TASK_CONTRACT.md", b"incoming task contract\n")
    _write(root / ".claude/docs/DESIGN.md", b"incoming design\n")
    _write(root / ".codex/config.toml", b"incoming = true\n")
    for index, relative_path in enumerate(SELF_UPDATE_PATHS, start=1):
        _write(root / relative_path, f"template updater file {index}\n".encode())


def _make_project(root: Path) -> None:
    _write(root / "CLAUDE.md", LOCAL_CLAUDE)
    _write(root / "AGENTS.md", LOCAL_AGENTS)
    _write(root / ".claude/agents/old.md", b"legacy agent\n")
    _write(root / ".claude/routing-keywords.json", b"{}\n")
    _write(root / ".gemini/settings.json", b"{}\n")
    _write(root / ".claude/hooks/local.py", b"local hook\n")
    _write(root / ".claude/rules/local.md", b"local rule\n")
    _write(root / ".claude/skills/local.md", b"local skill\n")
    _write(root / ".claude/scripts/local.py", b"local script\n")
    _write(root / ".claude/settings.json", b'{"local": true}\n')
    _write(root / ".claude/backtest-thresholds.json", b'{"threshold": "local"}\n')
    _write(root / ".claude/docs/CODEX_TASK_CONTRACT.md", b"local task contract\n")
    _write(root / ".claude/docs/DESIGN.md", b"local design without newline")
    _write(root / ".claude/docs/DESIGN.local-preserved.md", b"legacy archive unchanged\n")
    _write(root / ".claude/tasks/task-1/brief.md", b"preserved task\n")
    _write(root / ".claude/logs/preserved.log", b"preserved log\n")
    _write(root / ".codex/config.toml", b"local = true\n")
    for relative_path in SELF_UPDATE_PATHS:
        _write(root / relative_path, b"stale updater\n")
    _write(root / "scripts/project-owned-decoy.sh", b"project owned\n")
    for name in (
        ".zone-b.backup.md",
        ".agents-project.backup.md",
        ".backtest-thresholds.backup.json",
        ".design-local.backup.md",
    ):
        _write(root / name, f"reserved sentinel {name}\n".encode())


def _scaffold(tmp_path: Path, name: str = "fixture") -> tuple[Path, Path]:
    template = tmp_path / f"{name}-template"
    project = tmp_path / f"{name}-project"
    _make_template(template)
    _make_project(project)
    return template, project


def _command(entry_point: str) -> list[str]:
    if entry_point == "python":
        return [sys.executable, str(PYTHON_UPDATER)]
    return ["bash", str(SHELL_UPDATER)]


def _run_update(
    entry_point: str,
    project: Path,
    template: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        _command(entry_point),
        cwd=project,
        env={
            **os.environ,
            "TEMPLATE_SOURCE_DIR": str(template),
            "TEMPLATE_REPO_URL": "network-clone-must-not-run",
        },
        capture_output=True,
        text=True,
        check=False,
    )


def _tree_manifest(root: Path) -> dict[str, tuple[str, bytes]]:
    manifest: dict[str, tuple[str, bytes]] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_dir():
            manifest[relative] = ("directory", b"")
        else:
            manifest[relative] = ("file", path.read_bytes())
    return manifest


def _assert_success_outcomes(project: Path, template: Path) -> None:
    assert (project / "CLAUDE.md").read_bytes() == EXPECTED_CLAUDE
    assert (project / "AGENTS.md").read_bytes() == EXPECTED_AGENTS
    assert (project / ".claude/backtest-thresholds.json").read_bytes() == (
        b'{"threshold": "local"}\n'
    )
    assert (project / ".claude/tasks/task-1/brief.md").read_bytes() == b"preserved task\n"
    assert (project / ".claude/logs/preserved.log").read_bytes() == b"preserved log\n"
    assert not (project / ".claude/agents").exists()
    assert not (project / ".claude/routing-keywords.json").exists()
    assert not (project / ".gemini").exists()

    local_design = b"local design without newline"
    digest = hashlib.sha256(local_design).hexdigest()
    archive = project / ".claude/docs" / f"DESIGN.local-preserved.sha256-{digest}.md"
    assert archive.read_bytes() == local_design
    assert (project / ".claude/docs/DESIGN.md").read_bytes() == b"incoming design\n"
    assert (project / ".claude/docs/DESIGN.local-preserved.md").read_bytes() == (
        b"legacy archive unchanged\n"
    )

    expected_scripts = {
        "project-owned-decoy.sh": b"project owned\n",
        **{
            relative_path.name: (template / relative_path).read_bytes()
            for relative_path in SELF_UPDATE_PATHS
        },
    }
    actual_scripts = {
        path.name: path.read_bytes() for path in (project / "scripts").iterdir() if path.is_file()
    }
    assert actual_scripts == expected_scripts

    for name in (
        ".zone-b.backup.md",
        ".agents-project.backup.md",
        ".backtest-thresholds.backup.json",
        ".design-local.backup.md",
    ):
        assert (project / name).read_bytes() == f"reserved sentinel {name}\n".encode()


@pytest.mark.parametrize("entry_point", ENTRY_POINTS)
def test_hardened_update_succeeds_for_both_entry_points(
    tmp_path: Path,
    entry_point: str,
) -> None:
    template, project = _scaffold(tmp_path)

    first = _run_update(entry_point, project, template)
    assert first.returncode == 0, first.stderr
    _assert_success_outcomes(project, template)

    second = _run_update(entry_point, project, template)
    assert second.returncode == 0, second.stderr
    _assert_success_outcomes(project, template)
    archives = list((project / ".claude/docs").glob("DESIGN.local-preserved.sha256-*.md"))
    assert len(archives) == 1


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash is unavailable")
def test_shell_wrapper_and_python_entry_point_are_byte_identical(tmp_path: Path) -> None:
    template, python_project = _scaffold(tmp_path, "python")
    shell_project = tmp_path / "shell-project"
    shutil.copytree(python_project, shell_project)

    python_result = _run_update("python", python_project, template)
    shell_result = _run_update("shell", shell_project, template)

    assert python_result.returncode == 0, python_result.stderr
    assert shell_result.returncode == 0, shell_result.stderr
    assert _tree_manifest(shell_project) == _tree_manifest(python_project)


def test_empty_local_sections_replace_template_content(tmp_path: Path) -> None:
    template, project = _scaffold(tmp_path)
    _write(project / "CLAUDE.md", b"local\n" + CLAUDE_START + b"\n" + CLAUDE_REPO)
    _write(project / "AGENTS.md", b"local\r\n" + AGENTS_START + b"\r\n" + AGENTS_REPO)

    result = _run_update("python", project, template)

    assert result.returncode == 0, result.stderr
    assert (project / "CLAUDE.md").read_bytes() == (
        TEMPLATE_CLAUDE_PREFIX + TEMPLATE_CLAUDE_REPO_LINE
    )
    assert (project / "AGENTS.md").read_bytes() == (
        TEMPLATE_AGENTS_PREFIX + TEMPLATE_AGENTS_REPO_LINE
    )


MARKER_FAILURES = [
    pytest.param(location, filename, variant, id=f"{location}-{filename.lower()}-{variant}")
    for location in ("local", "template")
    for filename in ("CLAUDE.md", "AGENTS.md")
    for variant in ("missing", "duplicate", "misordered")
]


@pytest.mark.parametrize(("location", "filename", "variant"), MARKER_FAILURES)
@pytest.mark.parametrize("entry_point", ENTRY_POINTS)
def test_updater_rejects_invalid_markers_without_mutation(
    tmp_path: Path,
    entry_point: str,
    location: str,
    filename: str,
    variant: str,
) -> None:
    template, project = _scaffold(tmp_path)
    start, repo = (
        (CLAUDE_START, CLAUDE_REPO) if filename == "CLAUDE.md" else (AGENTS_START, AGENTS_REPO)
    )
    target_root = project if location == "local" else template
    if variant == "missing":
        invalid = b"# Missing marker\n" + start + b"\nProtected content."
        expected_markers = (repo.decode(),)
    elif variant == "duplicate":
        invalid = b"# Duplicate marker\n" + start + b"\n" + start + b"\n" + repo
        expected_markers = (start.decode(),)
    else:
        invalid = b"# Misordered markers\n" + repo + b"\nProtected content.\n" + start
        expected_markers = (start.decode(), repo.decode())
    _write(target_root / filename, invalid)
    before = _tree_manifest(project)

    result = _run_update(entry_point, project, template)

    assert result.returncode != 0
    assert _tree_manifest(project) == before
    assert filename in result.stderr
    for marker in expected_markers:
        assert marker in result.stderr


def test_python_updater_rejects_mismatched_existing_design_archive(tmp_path: Path) -> None:
    template, project = _scaffold(tmp_path)
    local_design = (project / ".claude/docs/DESIGN.md").read_bytes()
    digest = hashlib.sha256(local_design).hexdigest()
    archive = project / ".claude/docs" / f"DESIGN.local-preserved.sha256-{digest}.md"
    _write(archive, b"wrong archive bytes\n")
    before = _tree_manifest(project)

    result = _run_update("python", project, template)

    assert result.returncode != 0
    assert "digest collision or content mismatch" in result.stderr
    assert str(archive) in result.stderr
    assert _tree_manifest(project) == before


def _load_updater_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("template_updater_for_test", PYTHON_UPDATER)
    if spec is None or spec.loader is None:
        raise AssertionError("Unable to load scripts/update.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_post_mutation_failure_retains_and_reports_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    template, project = _scaffold(tmp_path)
    updater = _load_updater_module()
    replace_file = updater._replace_file

    def fail_on_final_self_update(source: Path, destination: Path) -> None:
        if destination == project / "scripts/update.sh":
            raise OSError("injected late replacement failure")
        replace_file(source, destination)

    monkeypatch.setattr(updater, "_replace_file", fail_on_final_self_update)
    monkeypatch.chdir(project)
    monkeypatch.setenv("TEMPLATE_SOURCE_DIR", str(template))
    monkeypatch.setenv("TEMPLATE_REPO_URL", "network-clone-must-not-run")

    result = updater.main()
    captured = capsys.readouterr()

    assert result == 1
    assert "injected late replacement failure" in captured.err
    match = re.search(r"Recovery copies were retained at: ([^\x1b\n]+)", captured.err)
    assert match is not None
    recovery_dir = Path(match.group(1))
    try:
        assert recovery_dir.is_dir()
        assert (recovery_dir / "project/CLAUDE.md").read_bytes() == LOCAL_CLAUDE
        for relative_path in SELF_UPDATE_PATHS:
            assert (recovery_dir / "project" / relative_path).read_bytes() == b"stale updater\n"
    finally:
        shutil.rmtree(recovery_dir.parent, ignore_errors=True)
