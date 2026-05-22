"""Shared helpers for Codex commit-stop fallback tests."""

import json
import subprocess
import sys
from pathlib import Path

import pytest


def isolate_fallback_markers(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point fallback/native marker files into a tmp dir for the test."""
    marker_dir = tmp_path / "markers"
    project_dir = tmp_path / "project"
    marker_dir.mkdir()
    project_dir.mkdir()
    monkeypatch.setenv("SASE_TMPDIR", str(marker_dir))
    monkeypatch.setenv("CODEX_PROJECT_DIR", str(project_dir))


def set_sase_session(monkeypatch: pytest.MonkeyPatch, ts: str = "260511_120000") -> str:
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", ts)
    return ts


def start_fixture_codex_process(
    events: list[dict[str, object]],
) -> subprocess.Popen[str]:
    lines = [json.dumps(event) for event in events]
    script = f"import sys\nfor line in {lines!r}:\n    print(line, flush=True)\n"
    return subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def codex_tool_turn_events(tool_id: str, reply: str) -> list[dict[str, object]]:
    return [
        {
            "type": "item.started",
            "item": {
                "id": tool_id,
                "type": "command_execution",
                "command": f"/bin/zsh -lc 'printf {tool_id}'",
                "aggregated_output": "",
                "exit_code": None,
                "status": "in_progress",
            },
        },
        {
            "type": "item.completed",
            "item": {
                "id": tool_id,
                "type": "command_execution",
                "command": f"/bin/zsh -lc 'printf {tool_id}'",
                "aggregated_output": f"{tool_id}\n",
                "exit_code": 0,
                "status": "completed",
            },
        },
        {
            "type": "item.completed",
            "item": {"id": f"msg_{tool_id}", "type": "agent_message", "text": reply},
        },
    ]
