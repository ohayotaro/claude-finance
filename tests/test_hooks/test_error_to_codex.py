from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from types import ModuleType


FAILING_OUTPUT = "Traceback (most recent call last):\n  File x\nValueError: boom\n"


def load_hook() -> ModuleType:
    path = Path(__file__).parents[2] / ".claude" / "hooks" / "error-to-codex.py"
    spec = importlib.util.spec_from_file_location("error_to_codex", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def payload(command: str) -> dict[str, object]:
    return {
        "tool_input": {"command": command},
        "tool_response": {"stdout": FAILING_OUTPUT, "stderr": ""},
    }


@pytest.mark.parametrize(
    "command",
    [
        "pytest -q",
        'uv run --extra dev pytest -m "not integration and not slow"',
        "uv run --extra dev ruff check src/",
        "uv run --extra dev mypy src/ .claude/scripts/",
        "uv run python -m src.orchestrator.registry audit",
        "uv run python .claude/scripts/codex_handoff.py review task-1",
        "cd /repo && pytest tests/",
        "uv run --extra dev pytest -q 2>&1",
        "uv run --extra dev pytest -q &> out.txt",
        "uv run --extra dev pytest -q 2>&1 | tail -5",
        'pytest --junitxml="reports/a&b.xml"',
        "pytest -k 'ledger && not slow' -q",
    ],
)
def test_validation_commands_are_silent(command: str) -> None:
    hook = load_hook()
    assert hook.handle(payload(command)) is None


@pytest.mark.parametrize(
    "command",
    [
        "uv run python scripts/analyze_backtest_foo.py",
        "python -m src.bot.main --strategy-id x --dry-run",
        "uv run python -m pytest_helper_tool",
        "uv run python scripts/analyze.py --input reports/pytest.json",
        "python scripts/check.py --tool mypy",
        "uv run --extra dev pytest -q && uv run python scripts/analyze_backtest_foo.py",
        "pytest -q & python scripts/check.py",
        "pytest -q 2>&1 & python scripts/check.py",
    ],
)
def test_other_failing_commands_still_report(command: str) -> None:
    hook = load_hook()
    context = hook.handle(payload(command))
    assert context is not None
    assert "ERROR DETECTED" in context
    assert "regression test" in context
    assert "codex_handoff.py plan" not in context
