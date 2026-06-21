from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import ModuleType

    import pytest


def load_log_hook() -> ModuleType:
    path = Path(__file__).parents[2] / ".claude" / "hooks" / "log-cli-tools.py"
    spec = importlib.util.spec_from_file_location("log_cli_tools", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_codex_telemetry_omits_raw_command_and_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hook = load_log_hook()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))

    hook.handle(
        {
            "session_id": "session-secret",
            "tool_input": {"command": 'codex exec - "API_SECRET=supersecret"'},
            "tool_response": {
                "stdout": "token=supersecret",
                "stderr": "another secret",
                "exit_code": 0,
            },
        }
    )

    log_path = tmp_path / ".claude" / "logs" / "cli-tools.jsonl"
    payload = json.loads(log_path.read_text(encoding="utf-8"))
    serialized = json.dumps(payload)
    assert payload["tool"] == "codex"
    assert payload["mode"] == "exec"
    assert "command" not in payload
    assert "session-secret" not in serialized
    assert "supersecret" not in serialized
    assert "token=" not in serialized
