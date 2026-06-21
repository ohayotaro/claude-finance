from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HOOK_PATH = Path(__file__).parents[2] / ".claude" / "hooks" / "live-trading-gate.py"
STRATEGY_A = "binance.swap.mean-revert.btcusdt.5m.v1"
STRATEGY_B = "binance.swap.breakout.ethusdt.5m.v1"


def run_gate(tmp_path: Path, command: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path)
    payload = {"tool_input": {"command": command}}
    return subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


def write_ack(tmp_path: Path) -> None:
    state_dir = tmp_path / ".claude" / "state"
    state_dir.mkdir(parents=True)
    (state_dir / "live-trading-test.ack").touch()


def write_kill(tmp_path: Path, name: str) -> Path:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    path = data_dir / name
    path.touch()
    return path


def test_global_kill_blocks_live_command_without_strategy_id(tmp_path: Path) -> None:
    write_kill(tmp_path, "KILL")

    result = run_gate(tmp_path, "python -m src.bot --live")

    assert result.returncode == 2
    assert "data/KILL exists" in result.stderr


def test_global_kill_blocks_live_command_with_strategy_id(tmp_path: Path) -> None:
    write_kill(tmp_path, "KILL")

    result = run_gate(tmp_path, f"python -m src.bot --live --strategy-id {STRATEGY_A}")

    assert result.returncode == 2
    assert "data/KILL exists" in result.stderr


def test_per_strategy_kill_blocks_matching_cli_strategy_id(tmp_path: Path) -> None:
    kill_path = write_kill(tmp_path, f"KILL.{STRATEGY_A}")

    result = run_gate(tmp_path, f"python -m src.bot --live --strategy-id {STRATEGY_A}")

    assert result.returncode == 2
    assert str(kill_path) in result.stderr
    assert f"strategy_id={STRATEGY_A}" in result.stderr


def test_per_strategy_kill_blocks_matching_env_strategy_id(tmp_path: Path) -> None:
    kill_path = write_kill(tmp_path, f"KILL.{STRATEGY_A}")

    result = run_gate(tmp_path, f"STRATEGY_ID={STRATEGY_A} python -m src.bot --live")

    assert result.returncode == 2
    assert str(kill_path) in result.stderr
    assert f"strategy_id={STRATEGY_A}" in result.stderr


def test_per_strategy_kill_does_not_block_different_strategy_id(tmp_path: Path) -> None:
    write_ack(tmp_path)
    write_kill(tmp_path, f"KILL.{STRATEGY_A}")

    result = run_gate(tmp_path, f"python -m src.bot --live --strategy-id {STRATEGY_B}")

    assert result.returncode == 0
    assert result.stderr == ""


def test_per_strategy_kill_does_not_block_command_without_strategy_id(tmp_path: Path) -> None:
    write_ack(tmp_path)
    write_kill(tmp_path, f"KILL.{STRATEGY_A}")

    result = run_gate(tmp_path, "python -m src.bot --live")

    assert result.returncode == 0
    assert result.stderr == ""
