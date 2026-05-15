"""Tests for Gemini CLI stream-json parsing and tool artifacts."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.llm_provider._subprocess import (
    _process_gemini_json_line,
    stream_and_parse_gemini_json_output,
)
from sase.llm_provider._tool_calls import _normalize_gemini_tool_call_event
from sase.llm_provider.gemini import GeminiProvider


def _start_fixture_gemini_process(
    events: list[dict[str, object] | str],
    *,
    return_code: int = 0,
) -> subprocess.Popen[str]:
    lines = [event if isinstance(event, str) else json.dumps(event) for event in events]
    script = (
        "import sys\n"
        f"for line in {lines!r}:\n"
        "    print(line, flush=True)\n"
        f"sys.exit({return_code})\n"
    )
    return subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_gemini_parser_streams_text_tool_artifacts_and_usage(
    tmp_path: Path,
) -> None:
    events: list[dict[str, object] | str] = [
        {"type": "init", "session_id": "session-1", "model": "gemini-test"},
        {"type": "message", "role": "assistant", "text": "Hello "},
        "{not json",
        {
            "type": "tool_use",
            "tool_id": "tool-1",
            "name": "run_shell_command",
            "arguments": {"command": "printf hi"},
            "session_id": "session-1",
            "cwd": "/workspace",
        },
        {
            "type": "tool_result",
            "tool_id": "tool-1",
            "name": "run_shell_command",
            "status": "success",
            "output": "hi\n",
            "session_id": "session-1",
        },
        {"type": "message", "role": "assistant", "text": "world"},
        {
            "type": "result",
            "response": "Hello world",
            "usage": {"input_tokens": 12, "output_tokens": 3},
        },
    ]
    process = _start_fixture_gemini_process(events)

    with patch.dict(os.environ, {"SASE_ARTIFACTS_DIR": str(tmp_path)}):
        text, stderr, rc, usage = stream_and_parse_gemini_json_output(
            process, suppress_output=True
        )

    assert (text, stderr, rc) == ("Hello world", "", 0)
    assert usage["input_tokens"] == 12
    assert usage["output_tokens"] == 3
    assert json.loads((tmp_path / "usage.json").read_text(encoding="utf-8")) == usage
    assert (tmp_path / "live_reply.md").read_text(encoding="utf-8") == "Hello world"

    tool_records = _read_jsonl(tmp_path / "tool_calls.jsonl")
    assert [record["event"] for record in tool_records] == ["ToolUse", "ToolResult"]
    assert [record["runtime"] for record in tool_records] == ["gemini", "gemini"]
    assert [record["tool_name"] for record in tool_records] == ["Bash", "Bash"]
    assert tool_records[0]["tool_input_summary"] == {"command": "printf hi"}
    assert tool_records[1]["tool_response_summary"]["preview"] == "hi\n"

    timestamp_records = _read_jsonl(tmp_path / "live_reply_timestamps.jsonl")
    assert [record["byte_offset"] for record in timestamp_records] == [0]


def test_gemini_parser_uses_result_text_when_messages_absent() -> None:
    assistant_chunks: list[str] = []

    _process_gemini_json_line(
        json.dumps({"type": "result", "response": "final answer"}),
        assistant_chunks,
        suppress_output=True,
    )

    assert assistant_chunks == ["final answer"]


def test_gemini_parser_captures_error_diagnostics_on_failure() -> None:
    process = _start_fixture_gemini_process(
        [{"type": "error", "error": {"message": "bad request"}}],
        return_code=1,
    )

    text, stderr, rc, _usage = stream_and_parse_gemini_json_output(
        process, suppress_output=True
    )

    assert text == ""
    assert rc == 1
    assert "[error] bad request" in stderr


def test_gemini_tool_normalizer_maps_files_and_unknown_tools() -> None:
    read_record = _normalize_gemini_tool_call_event(
        {
            "type": "tool_use",
            "tool_id": "read-1",
            "name": "read_file",
            "arguments": {"file_path": "src/sase/foo.py"},
        }
    )
    unknown_record = _normalize_gemini_tool_call_event(
        {
            "type": "tool_use",
            "tool_id": "custom-1",
            "name": "mcp__demo__lookup",
            "arguments": {"query": "fixture"},
        }
    )

    assert read_record is not None
    assert read_record["tool_name"] == "Read"
    assert read_record["tool_input_summary"] == {"file_path": "src/sase/foo.py"}
    assert unknown_record is not None
    assert unknown_record["tool_name"] == "mcp__demo__lookup"
    assert unknown_record["tool_input_summary"] == {"input_keys": ["query"]}


def test_gemini_tool_writer_diagnoses_malformed_events(tmp_path: Path) -> None:
    with patch.dict(os.environ, {"SASE_ARTIFACTS_DIR": str(tmp_path)}):
        _process_gemini_json_line(
            json.dumps({"type": "tool_use", "arguments": {"command": "pwd"}}),
            [],
            suppress_output=True,
        )

    assert not (tmp_path / "tool_calls.jsonl").exists()
    diagnostics = _read_jsonl(tmp_path / "tool_calls_writer_errors.jsonl")
    assert diagnostics[0]["reason"] == "gemini_tool_event_missing_tool_identity"


def test_gemini_tool_writer_noops_without_artifacts_dir() -> None:
    with (
        patch.dict(os.environ, {}, clear=True),
        patch("sase.llm_provider._tool_call_gemini.append_jsonl") as mock_append,
    ):
        _process_gemini_json_line(
            json.dumps(
                {
                    "type": "tool_use",
                    "tool_id": "tool-1",
                    "name": "read_file",
                    "arguments": {"file_path": "README.md"},
                }
            ),
            [],
            suppress_output=True,
        )

    mock_append.assert_not_called()


@patch("sase.llm_provider.gemini.stream_and_parse_gemini_json_output")
@patch("sase.llm_provider.gemini.subprocess.Popen")
@patch("sase.llm_provider.gemini.gemini_timer")
def test_gemini_provider_command_construction_uses_stream_json(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    mock_process = MagicMock()
    mock_popen.return_value = mock_process
    mock_stream.return_value = (
        "response",
        "",
        0,
        {
            "input_tokens": 1,
            "output_tokens": 2,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        },
    )

    result = GeminiProvider().invoke(
        "test prompt", model_tier="large", suppress_output=True
    )

    cmd = mock_popen.call_args.args[0]
    assert cmd[0] == "gemini"
    assert "--output-format" in cmd
    assert "stream-json" in cmd
    assert "--yolo" in cmd
    assert "--model" in cmd
    assert "gemini-3-flash-preview" in cmd
    assert mock_popen.call_args.kwargs["stdout"] is subprocess.PIPE
    assert mock_popen.call_args.kwargs["text"] is True
    mock_process.stdin.write.assert_called_once_with("test prompt")
    mock_process.stdin.close.assert_called_once()
    assert result.content == "response"
    assert result.usage == {
        "input_tokens": 1,
        "output_tokens": 2,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }


@patch("sase.llm_provider.gemini.stream_and_parse_gemini_json_output")
@patch("sase.llm_provider.gemini.subprocess.Popen")
@patch("sase.llm_provider.gemini.gemini_timer")
def test_gemini_provider_raises_called_process_error_on_failure(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    mock_popen.return_value = MagicMock()
    mock_stream.return_value = (
        "",
        "gemini failed",
        2,
        {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        },
    )

    with pytest.raises(subprocess.CalledProcessError) as exc_info:
        GeminiProvider().invoke("test", model_tier="large", suppress_output=True)

    assert exc_info.value.returncode == 2
    assert exc_info.value.stderr == "gemini failed"
