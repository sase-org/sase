"""Tests locking Claude Tools collection to stream-backed artifacts."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.llm_provider._tool_calls import append_claude_tool_call_event
from sase.llm_provider.claude import ClaudeCodeProvider


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    path = tmp_path / "ws"
    path.mkdir()
    return path


@pytest.fixture
def artifacts_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "artifacts"
    path.mkdir()
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(path))
    return path


def _settings_path(workspace: Path) -> Path:
    return workspace / ".claude" / "settings.local.json"


def _invoke_with_fake_stream(
    stream_result: tuple[str, str, int, dict[str, int]],
) -> None:
    with (
        patch("sase.llm_provider.claude.subprocess.Popen", return_value=MagicMock()),
        patch(
            "sase.llm_provider.claude.stream_and_parse_json_output",
            return_value=stream_result,
        ),
        patch("sase.llm_provider.claude.provider_timer"),
    ):
        ClaudeCodeProvider().invoke("hi", model_tier="small", suppress_output=True)


def test_claude_provider_does_not_mutate_existing_settings(
    workspace: Path,
    artifacts_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_GIT_WORKSPACE_DIR", str(workspace))
    settings_path = _settings_path(workspace)
    settings_path.parent.mkdir()
    original = {
        "permissions": {"allow": ["Bash(ls:*)"]},
        "hooks": {
            "Notification": [
                {"matcher": "*", "hooks": [{"type": "command", "command": "ping"}]}
            ]
        },
    }
    settings_path.write_text(json.dumps(original, indent=2) + "\n", encoding="utf-8")

    _invoke_with_fake_stream(
        (
            "response",
            "",
            0,
            {
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
            },
        )
    )

    assert json.loads(settings_path.read_text(encoding="utf-8")) == original
    assert not (artifacts_dir / "tool_calls_writer_errors.jsonl").exists()


def test_claude_provider_does_not_create_settings_file(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_GIT_WORKSPACE_DIR", str(workspace))

    _invoke_with_fake_stream(
        (
            "response",
            "",
            0,
            {
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
            },
        )
    )

    assert not _settings_path(workspace).exists()
    assert not (workspace / ".claude").exists()


def test_simulated_claude_provider_run_writes_stream_records(
    workspace: Path,
    artifacts_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui.models.agent import Agent, AgentType
    from sase.ace.tui.tools import read_tool_calls_for_agent

    monkeypatch.setenv("SASE_GIT_WORKSPACE_DIR", str(workspace))
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "20260515_010101")

    def fake_stream(
        *_args: object,
        **_kwargs: object,
    ) -> tuple[str, str, int, dict[str, int]]:
        append_claude_tool_call_event(
            {
                "type": "assistant",
                "session_id": "session-sim",
                "message": {
                    "id": "msg_1",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_simulated",
                            "name": "Bash",
                            "input": {"command": "printf hi"},
                        }
                    ],
                },
            }
        )
        append_claude_tool_call_event(
            {
                "type": "user",
                "session_id": "session-sim",
                "message": {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "toolu_simulated",
                            "content": "hi",
                        }
                    ],
                },
                "tool_use_result": {"exit_code": 0, "stdout": "hi", "success": True},
            }
        )
        return (
            "response",
            "",
            0,
            {
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
            },
        )

    with (
        patch("sase.llm_provider.claude.subprocess.Popen", return_value=MagicMock()),
        patch(
            "sase.llm_provider.claude.stream_and_parse_json_output",
            side_effect=fake_stream,
        ),
        patch("sase.llm_provider.claude.provider_timer"),
    ):
        ClaudeCodeProvider().invoke("hi", model_tier="small", suppress_output=True)

    assert not _settings_path(workspace).exists()
    raw_rows = [
        json.loads(line)
        for line in (artifacts_dir / "tool_calls.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert [row["schema_version"] for row in raw_rows] == [2, 2]
    assert [row["event"] for row in raw_rows] == ["ToolUse", "ToolResult"]
    assert all(row.get("source") != "hook" for row in raw_rows)

    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="proj",
        project_file=str(workspace / "proj.sase"),
        status="DONE",
        start_time=datetime(2026, 5, 15, 1, 1, 1),
        artifacts_dir=str(artifacts_dir),
        raw_suffix=artifacts_dir.name,
    )
    entries = read_tool_calls_for_agent(agent)

    assert entries is not None
    assert len(entries) == 1
    entry = entries[0]
    assert entry.source is None
    assert entry.tool_use_id == "toolu_simulated"
    assert entry.status == "success"
    assert entry.compact_target == "printf hi"
