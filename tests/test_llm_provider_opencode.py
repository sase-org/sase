"""Tests for OpenCodeProvider invoke/command construction."""

import json
import os
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from sase.llm_provider._subprocess import _process_opencode_json_line
from sase.llm_provider.base import LLMProvider
from sase.llm_provider.opencode import OpenCodeProvider
from sase.llm_provider.registry import resolve_model_provider


def test_opencode_provider_is_llm_provider() -> None:
    provider = OpenCodeProvider()
    assert isinstance(provider, LLMProvider)


def test_opencode_provider_resolve_model_name() -> None:
    provider = OpenCodeProvider()
    assert provider.resolve_model_name() == "anthropic/claude-sonnet-4-5"
    assert provider.resolve_model_name("large") == "anthropic/claude-sonnet-4-5"
    assert provider.resolve_model_name("small") == "openai/gpt-5-mini"


@patch("sase.llm_provider.opencode.stream_and_parse_opencode_json_output")
@patch("sase.llm_provider.opencode.subprocess.Popen")
@patch("sase.llm_provider.opencode.gemini_timer")
def test_opencode_provider_command_construction(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    mock_process = MagicMock()
    mock_popen.return_value = mock_process
    mock_stream.return_value = ("response", "", 0, {})

    provider = OpenCodeProvider()
    provider.invoke("test prompt", model_tier="large", suppress_output=True)

    cmd = mock_popen.call_args.args[0]
    assert cmd[:2] == ["opencode", "run"]
    assert "--format" in cmd
    assert "json" in cmd
    assert "--dangerously-skip-permissions" in cmd
    assert "--model" in cmd
    assert "anthropic/claude-sonnet-4-5" in cmd
    assert "--dir" in cmd
    assert mock_popen.call_args.kwargs["text"] is True
    assert "test prompt" not in cmd
    mock_process.stdin.write.assert_called_once_with("test prompt")
    mock_process.stdin.close.assert_called_once()


@patch("sase.llm_provider.opencode.stream_and_parse_opencode_json_output")
@patch("sase.llm_provider.opencode.subprocess.Popen")
@patch("sase.llm_provider.opencode.gemini_timer")
def test_opencode_provider_model_override(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    mock_process = MagicMock()
    mock_popen.return_value = mock_process
    mock_stream.return_value = ("response", "", 0, {})

    provider = OpenCodeProvider()
    provider.invoke(
        "test",
        model_tier="large",
        suppress_output=True,
        model_override="openrouter/anthropic/claude-sonnet-4-5",
    )

    cmd = mock_popen.call_args.args[0]
    assert "openrouter/anthropic/claude-sonnet-4-5" in cmd
    assert "anthropic/claude-sonnet-4-5" not in cmd


@patch.dict(os.environ, {"SASE_OPENCODE_PATH": "/opt/opencode/bin/opencode"})
@patch("sase.llm_provider.opencode.stream_and_parse_opencode_json_output")
@patch("sase.llm_provider.opencode.subprocess.Popen")
@patch("sase.llm_provider.opencode.gemini_timer")
def test_opencode_provider_uses_sase_opencode_path(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    mock_process = MagicMock()
    mock_popen.return_value = mock_process
    mock_stream.return_value = ("response", "", 0, {})

    provider = OpenCodeProvider()
    provider.invoke("test", model_tier="large", suppress_output=True)

    assert mock_popen.call_args.args[0][0] == "/opt/opencode/bin/opencode"


@patch.dict(os.environ, {"SASE_OPENCODE_SMALL_ARGS": "--agent build"})
@patch("sase.llm_provider.opencode.stream_and_parse_opencode_json_output")
@patch("sase.llm_provider.opencode.subprocess.Popen")
@patch("sase.llm_provider.opencode.gemini_timer")
def test_opencode_provider_extra_args_from_env_small(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    mock_process = MagicMock()
    mock_popen.return_value = mock_process
    mock_stream.return_value = ("response", "", 0, {})

    provider = OpenCodeProvider()
    provider.invoke("test", model_tier="small", suppress_output=True)

    cmd = mock_popen.call_args.args[0]
    assert "--agent" in cmd
    assert "build" in cmd


@patch.dict(
    os.environ,
    {
        "SASE_LLM_LARGE_ARGS": "--generic val1",
        "SASE_OPENCODE_LARGE_ARGS": "--opencode val2",
    },
)
@patch("sase.llm_provider.opencode.stream_and_parse_opencode_json_output")
@patch("sase.llm_provider.opencode.subprocess.Popen")
@patch("sase.llm_provider.opencode.gemini_timer")
def test_opencode_provider_generic_env_args_precedence(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    mock_process = MagicMock()
    mock_popen.return_value = mock_process
    mock_stream.return_value = ("response", "", 0, {})

    provider = OpenCodeProvider()
    provider.invoke("test", model_tier="large", suppress_output=True)

    cmd = mock_popen.call_args.args[0]
    assert "--generic" in cmd
    assert "val1" in cmd
    assert "--opencode" not in cmd


@patch("sase.llm_provider.opencode.subprocess.Popen")
def test_opencode_provider_missing_executable_error_mentions_resolution_paths(
    mock_popen: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SASE_OPENCODE_PATH", raising=False)
    mock_popen.side_effect = FileNotFoundError("missing")

    provider = OpenCodeProvider()
    with pytest.raises(FileNotFoundError) as exc_info:
        provider.invoke("test", model_tier="large", suppress_output=True)

    message = str(exc_info.value)
    assert "SASE_OPENCODE_PATH" in message
    assert "PATH" in message


@patch("sase.llm_provider.opencode.stream_and_parse_opencode_json_output")
@patch("sase.llm_provider.opencode.subprocess.Popen")
@patch("sase.llm_provider.opencode.gemini_timer")
def test_opencode_provider_raises_called_process_error_on_failure(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    mock_process = MagicMock()
    mock_popen.return_value = mock_process
    mock_stream.return_value = ("", "opencode failed", 2, {})

    provider = OpenCodeProvider()
    with pytest.raises(subprocess.CalledProcessError) as exc_info:
        provider.invoke("test", model_tier="large", suppress_output=True)

    assert exc_info.value.returncode == 2
    assert exc_info.value.stderr == "opencode failed"


def test_opencode_parser_extracts_text_and_usage() -> None:
    assistant_texts: list[str] = []
    usage_totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }

    _process_opencode_json_line(
        json.dumps(
            {
                "type": "text",
                "part": {"type": "text", "text": "hello from opencode"},
            }
        ),
        assistant_texts,
        suppress_output=True,
        usage_totals=usage_totals,
    )
    _process_opencode_json_line(
        json.dumps(
            {
                "type": "step_finish",
                "part": {
                    "type": "step-finish",
                    "tokens": {
                        "input": 10,
                        "output": 5,
                        "cache": {"read": 3, "write": 2},
                    },
                },
            }
        ),
        assistant_texts,
        suppress_output=True,
        usage_totals=usage_totals,
    )

    assert assistant_texts == ["hello from opencode"]
    assert usage_totals["input_tokens"] == 10
    assert usage_totals["output_tokens"] == 5
    assert usage_totals["cache_read_input_tokens"] == 3
    assert usage_totals["cache_creation_input_tokens"] == 2


def test_opencode_parser_ignores_malformed_and_unknown_events() -> None:
    assistant_texts: list[str] = []

    _process_opencode_json_line("{not json", assistant_texts, suppress_output=True)
    _process_opencode_json_line(
        json.dumps({"type": "tool_use", "part": {"tool": "bash"}}),
        assistant_texts,
        suppress_output=True,
    )

    assert assistant_texts == []


def test_opencode_parser_captures_error_diagnostics() -> None:
    assistant_texts: list[str] = []
    error_events: list[str] = []

    _process_opencode_json_line(
        json.dumps(
            {
                "type": "error",
                "error": {
                    "name": "APIError",
                    "data": {"message": "rate limited", "isRetryable": True},
                },
            }
        ),
        assistant_texts,
        suppress_output=True,
        error_events=error_events,
    )

    assert assistant_texts == []
    assert error_events == ["[error] rate limited"]


def test_opencode_model_resolution_preserves_nested_provider_model() -> None:
    assert resolve_model_provider("opencode/anthropic/claude-sonnet-4-5") == (
        "opencode",
        "anthropic/claude-sonnet-4-5",
    )
    assert resolve_model_provider("anthropic/claude-sonnet-4-5") == (
        "opencode",
        "anthropic/claude-sonnet-4-5",
    )
