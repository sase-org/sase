"""Tests for QwenProvider invoke/command construction."""

import json
import os
import subprocess
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.llm_provider._subprocess import _process_qwen_json_line
from sase.llm_provider._tool_calls import (
    _normalize_qwen_tool_call_event,
    append_qwen_tool_call_event,
)
from sase.llm_provider.base import LLMProvider
from sase.llm_provider.qwen import QwenProvider
from sase.llm_provider.registry import resolve_model_provider

QWEN_STREAM_FIXTURES = Path(__file__).parent / "fixtures" / "qwen_stream"


def _load_qwen_fixture_events(name: str) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in (QWEN_STREAM_FIXTURES / name)
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]


def test_qwen_provider_is_llm_provider() -> None:
    provider = QwenProvider()
    assert isinstance(provider, LLMProvider)


def test_qwen_provider_resolve_model_name() -> None:
    provider = QwenProvider()
    assert provider.resolve_model_name() == "qwen3.6-plus"
    assert provider.resolve_model_name("large") == "qwen3.6-plus"
    assert provider.resolve_model_name("small") == "qwen3-coder-flash"


@patch("sase.llm_provider.qwen.stream_and_parse_qwen_json_output")
@patch("sase.llm_provider.qwen.subprocess.Popen")
@patch("sase.llm_provider.qwen.gemini_timer")
def test_qwen_provider_command_construction(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    mock_process = MagicMock()
    mock_popen.return_value = mock_process
    mock_stream.return_value = ("response", "", 0, {})

    provider = QwenProvider()
    provider.invoke("test prompt", model_tier="large", suppress_output=True)

    cmd = mock_popen.call_args.args[0]
    assert cmd[0] == "qwen"
    assert "--input-format" in cmd
    assert "text" in cmd
    assert "--output-format" in cmd
    assert "stream-json" in cmd
    assert "--yolo" in cmd
    assert "--model" in cmd
    assert "qwen3.6-plus" in cmd
    assert mock_popen.call_args.kwargs["text"] is True
    mock_process.stdin.write.assert_called_once_with("test prompt")
    mock_process.stdin.close.assert_called_once()


@patch("sase.llm_provider.qwen.stream_and_parse_qwen_json_output")
@patch("sase.llm_provider.qwen.subprocess.Popen")
@patch("sase.llm_provider.qwen.gemini_timer")
def test_qwen_provider_model_override(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    mock_process = MagicMock()
    mock_popen.return_value = mock_process
    mock_stream.return_value = ("response", "", 0, {})

    provider = QwenProvider()
    provider.invoke(
        "test", model_tier="large", suppress_output=True, model_override="custom"
    )

    cmd = mock_popen.call_args.args[0]
    assert "custom" in cmd
    assert "qwen3.6-plus" not in cmd


@patch.dict(os.environ, {"SASE_QWEN_PATH": "/opt/qwen/bin/qwen"})
@patch("sase.llm_provider.qwen.stream_and_parse_qwen_json_output")
@patch("sase.llm_provider.qwen.subprocess.Popen")
@patch("sase.llm_provider.qwen.gemini_timer")
def test_qwen_provider_uses_sase_qwen_path(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    mock_process = MagicMock()
    mock_popen.return_value = mock_process
    mock_stream.return_value = ("response", "", 0, {})

    provider = QwenProvider()
    provider.invoke("test", model_tier="large", suppress_output=True)

    assert mock_popen.call_args.args[0][0] == "/opt/qwen/bin/qwen"


@patch.dict(os.environ, {"SASE_QWEN_SMALL_ARGS": "--approval-mode never"})
@patch("sase.llm_provider.qwen.stream_and_parse_qwen_json_output")
@patch("sase.llm_provider.qwen.subprocess.Popen")
@patch("sase.llm_provider.qwen.gemini_timer")
def test_qwen_provider_extra_args_from_env_small(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    mock_process = MagicMock()
    mock_popen.return_value = mock_process
    mock_stream.return_value = ("response", "", 0, {})

    provider = QwenProvider()
    provider.invoke("test", model_tier="small", suppress_output=True)

    cmd = mock_popen.call_args.args[0]
    assert "--approval-mode" in cmd
    assert "never" in cmd


@patch.dict(
    os.environ,
    {
        "SASE_LLM_LARGE_ARGS": "--generic val1",
        "SASE_QWEN_LARGE_ARGS": "--qwen val2",
    },
)
@patch("sase.llm_provider.qwen.stream_and_parse_qwen_json_output")
@patch("sase.llm_provider.qwen.subprocess.Popen")
@patch("sase.llm_provider.qwen.gemini_timer")
def test_qwen_provider_generic_env_args_precedence(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    mock_process = MagicMock()
    mock_popen.return_value = mock_process
    mock_stream.return_value = ("response", "", 0, {})

    provider = QwenProvider()
    provider.invoke("test", model_tier="large", suppress_output=True)

    cmd = mock_popen.call_args.args[0]
    assert "--generic" in cmd
    assert "val1" in cmd
    assert "--qwen" not in cmd


@patch("sase.llm_provider.qwen.subprocess.Popen")
def test_qwen_provider_missing_executable_error_mentions_resolution_paths(
    mock_popen: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SASE_QWEN_PATH", raising=False)
    mock_popen.side_effect = FileNotFoundError("missing")

    provider = QwenProvider()
    with pytest.raises(FileNotFoundError) as exc_info:
        provider.invoke("test", model_tier="large", suppress_output=True)

    message = str(exc_info.value)
    assert "SASE_QWEN_PATH" in message
    assert "PATH" in message


@patch("sase.llm_provider.qwen.stream_and_parse_qwen_json_output")
@patch("sase.llm_provider.qwen.subprocess.Popen")
@patch("sase.llm_provider.qwen.gemini_timer")
def test_qwen_provider_raises_called_process_error_on_failure(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    mock_process = MagicMock()
    mock_popen.return_value = mock_process
    mock_stream.return_value = ("", "qwen failed", 2, {})

    provider = QwenProvider()
    with pytest.raises(subprocess.CalledProcessError) as exc_info:
        provider.invoke("test", model_tier="large", suppress_output=True)

    assert exc_info.value.returncode == 2
    assert exc_info.value.stderr == "qwen failed"


def test_qwen_parser_extracts_assistant_text_and_usage() -> None:
    assistant_texts: list[str] = []
    usage_totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }

    _process_qwen_json_line(
        json.dumps(
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "hello"}]},
            }
        ),
        assistant_texts,
        suppress_output=True,
        usage_totals=usage_totals,
    )
    _process_qwen_json_line(
        json.dumps(
            {
                "type": "result",
                "result": "hello",
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            }
        ),
        assistant_texts,
        suppress_output=True,
        usage_totals=usage_totals,
    )

    assert assistant_texts == ["hello"]
    assert usage_totals["input_tokens"] == 10
    assert usage_totals["output_tokens"] == 5


def test_qwen_parser_uses_result_text_when_assistant_absent() -> None:
    assistant_texts: list[str] = []

    _process_qwen_json_line(
        json.dumps({"type": "result", "result": "final answer"}),
        assistant_texts,
        suppress_output=True,
    )

    assert assistant_texts == ["final answer"]


def test_qwen_parser_ignores_malformed_and_unknown_events() -> None:
    assistant_texts: list[str] = []

    _process_qwen_json_line("{not json", assistant_texts, suppress_output=True)
    _process_qwen_json_line(
        json.dumps({"type": "unknown", "payload": "ignored"}),
        assistant_texts,
        suppress_output=True,
    )

    assert assistant_texts == []


def test_qwen_tool_call_normalizer_handles_real_stream_fixture() -> None:
    """Qwen Code 0.15.10 emits nested tool_use/tool_result content blocks."""
    records = [
        record
        for event in _load_qwen_fixture_events("qwen-code-0.15.10-tools.jsonl")
        for record in _normalize_qwen_tool_call_event(event)
    ]

    assert [record["event"] for record in records] == ["ToolUse", "ToolResult"]
    assert records[0]["runtime"] == "qwen"
    assert records[0]["source"] == "stream"
    assert records[0]["status"] == "pending"
    assert records[0]["tool_name"] == "Bash"
    assert records[0]["tool_use_id"] == "call_09f0141925974fc99fb01f2a"
    assert records[0]["session_id"] == "ea27698c-1270-4a5a-b3e3-6a8162fd5b20"
    assert records[0]["tool_input_summary"] == {
        "command": "printf qwen_tool_fixture",
        "description": "Print qwen_tool_fixture to stdout",
    }
    assert records[1]["status"] == "success"
    assert records[1]["tool_response_summary"]["content_preview"] == (
        "qwen_tool_fixture"
    )


def test_qwen_tool_call_normalizer_accepts_explicit_tool_events() -> None:
    records = [
        record
        for event in [
            {
                "type": "tool_call",
                "session_id": "session-explicit",
                "call_id": "call-read",
                "function": {
                    "name": "read_file",
                    "arguments": '{"path": "src/sase/foo.py", "limit": 20}',
                },
            },
            {
                "type": "tool_result",
                "session_id": "session-explicit",
                "tool_call_id": "call-read",
                "content": "class Foo:\n",
            },
        ]
        for record in _normalize_qwen_tool_call_event(event)
    ]

    assert [record["event"] for record in records] == ["ToolUse", "ToolResult"]
    assert records[0]["tool_name"] == "Read"
    assert records[0]["tool_input_summary"] == {
        "file_path": "src/sase/foo.py",
        "limit": 20,
    }
    assert records[1]["session_id"] == "session-explicit"
    assert records[1]["tool_response_summary"]["content_preview"] == "class Foo:\n"


def test_append_qwen_tool_call_event_writes_artifacts_and_diagnostics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))

    append_qwen_tool_call_event(
        {
            "type": "assistant",
            "session_id": "session-qwen",
            "cwd": "/tmp/qwen",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "call-shell",
                        "name": "run_shell_command",
                        "input": {
                            "command": "TOKEN=secret echo ok",
                            "description": "demo",
                        },
                    }
                ]
            },
        }
    )
    append_qwen_tool_call_event(
        {
            "type": "user",
            "session_id": "session-qwen",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "call-shell",
                        "is_error": False,
                        "content": "ok",
                    },
                    {"type": "tool_result", "content": "missing id"},
                ]
            },
        }
    )
    append_qwen_tool_call_event({"type": "tool_stats", "summary": {"count": 1}})

    records = [
        json.loads(line)
        for line in (tmp_path / "tool_calls.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    diagnostics = [
        json.loads(line)
        for line in (tmp_path / "tool_calls_writer_errors.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]

    assert [record["event"] for record in records] == ["ToolUse", "ToolResult"]
    assert records[0]["cwd"] == "/tmp/qwen"
    assert "secret" not in records[0]["tool_input_summary"]["command"]
    assert records[1]["duration_ms"] >= 0
    assert diagnostics[0]["reason"] == "qwen_malformed_tool_result"
    assert diagnostics[1]["reason"] == "qwen_unsupported_tool_event"


def test_qwen_parser_writes_tool_call_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    assistant_texts: list[str] = []

    for event in _load_qwen_fixture_events("qwen-code-0.15.10-tools.jsonl"):
        _process_qwen_json_line(
            json.dumps(event),
            assistant_texts,
            suppress_output=True,
        )

    records = [
        json.loads(line)
        for line in (tmp_path / "tool_calls.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert assistant_texts == ["done"]
    assert [record["event"] for record in records] == ["ToolUse", "ToolResult"]


def test_qwen_model_resolution() -> None:
    assert resolve_model_provider("qwen/qwen3.6-plus") == (
        "qwen",
        "qwen3.6-plus",
    )
    assert resolve_model_provider("qwen3.6-plus") == (
        "qwen",
        "qwen3.6-plus",
    )
    assert resolve_model_provider("qwen/qwen3-coder-plus") == (
        "qwen",
        "qwen3-coder-plus",
    )
    assert resolve_model_provider("qwen3-coder-plus") == (
        "qwen",
        "qwen3-coder-plus",
    )


def test_qwen_provider_invokes_fake_cli_and_writes_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_qwen = tmp_path / "qwen"
    fake_qwen.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import json
            import sys

            prompt = sys.stdin.read()
            if "-p" in sys.argv or "--prompt" in sys.argv:
                sys.stderr.write("qwen prompt must be read from stdin\\n")
                sys.exit(64)
            if "--input-format" not in sys.argv or "text" not in sys.argv:
                sys.stderr.write("missing text input-format\\n")
                sys.exit(64)
            if prompt != "fake qwen prompt":
                sys.stderr.write(f"unexpected prompt: {prompt!r}\\n")
                sys.exit(64)

            print(json.dumps({
                "type": "assistant",
                "session_id": "fake-session",
                "message": {"content": [{
                    "type": "tool_use",
                    "id": "call_fake",
                    "name": "run_shell_command",
                    "input": {
                        "command": "printf qwen_tool_fixture",
                        "description": "fixture command",
                    },
                }]},
            }), flush=True)
            print(json.dumps({
                "type": "user",
                "session_id": "fake-session",
                "message": {"content": [{
                    "type": "tool_result",
                    "tool_use_id": "call_fake",
                    "is_error": False,
                    "content": "qwen_tool_fixture",
                }]},
            }), flush=True)
            print(json.dumps({
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "qwen fake ok"}]},
            }), flush=True)
            print(json.dumps({
                "type": "result",
                "subtype": "success",
                "result": "qwen fake ok",
                "usage": {"prompt_tokens": 11, "completion_tokens": 7},
            }), flush=True)
            """
        )
    )
    fake_qwen.chmod(0o755)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setenv("SASE_QWEN_PATH", str(fake_qwen))
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))

    result = QwenProvider().invoke(
        "fake qwen prompt", model_tier="large", suppress_output=True
    )

    assert result.content == "qwen fake ok"
    assert result.usage["input_tokens"] == 11
    assert result.usage["output_tokens"] == 7
    assert (artifacts / "live_reply.md").read_text() == "qwen fake ok"
    assert json.loads((artifacts / "usage.json").read_text())["output_tokens"] == 7
    tool_calls = [
        json.loads(line)
        for line in (artifacts / "tool_calls.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [record["event"] for record in tool_calls] == ["ToolUse", "ToolResult"]


def test_qwen_provider_fake_cli_failure_surfaces_stream_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_qwen = tmp_path / "qwen"
    fake_qwen.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import json
            import sys

            sys.stdin.read()
            print(json.dumps({
                "type": "error",
                "error": {"message": "rate limit 429"},
            }), flush=True)
            sys.exit(7)
            """
        )
    )
    fake_qwen.chmod(0o755)
    monkeypatch.setenv("SASE_QWEN_PATH", str(fake_qwen))

    with pytest.raises(subprocess.CalledProcessError) as exc_info:
        QwenProvider().invoke(
            "fake qwen prompt", model_tier="large", suppress_output=True
        )

    assert exc_info.value.returncode == 7
    assert "[error] rate limit 429" in exc_info.value.stderr
