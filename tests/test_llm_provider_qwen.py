"""Tests for QwenProvider invoke/command construction."""

import json
import os
import subprocess
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.llm_provider._subprocess import _process_qwen_json_line
from sase.llm_provider.base import LLMProvider
from sase.llm_provider.qwen import QwenProvider
from sase.llm_provider.registry import resolve_model_provider


def test_qwen_provider_is_llm_provider() -> None:
    provider = QwenProvider()
    assert isinstance(provider, LLMProvider)


def test_qwen_provider_resolve_model_name() -> None:
    provider = QwenProvider()
    assert provider.resolve_model_name() == "qwen3-coder-plus"
    assert provider.resolve_model_name("large") == "qwen3-coder-plus"
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
    assert "qwen3-coder-plus" in cmd
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
    assert "qwen3-coder-plus" not in cmd


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


def test_qwen_model_resolution() -> None:
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
