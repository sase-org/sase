"""Tests for llm_provider implementations (Claude, Gemini, Codex, subprocess, backward compat)."""

import json
import os
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest
from pathlib import Path

from sase.llm_provider._subprocess import (
    _process_codex_json_line,
    stream_and_parse_codex_json_output,
    stream_process_output,
)
from sase.llm_provider.base import LLMProvider
from sase.llm_provider.claude import ClaudeCodeProvider
from sase.llm_provider.codex import CodexProvider, _find_codex_plan_file
from sase.llm_provider.gemini import GeminiProvider
from sase.llm_provider.types import ModelTier


# --- gemini.py / subprocess tests ---


def test_stream_process_output_stderr() -> None:
    """Test streaming of process stderr."""
    process = subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.stderr.write('error message\\n')"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    stdout, stderr, return_code = stream_process_output(process, suppress_output=True)

    assert stdout == ""
    assert "error message" in stderr
    assert return_code == 0


def test_gemini_provider_is_llm_provider() -> None:
    """Test that GeminiProvider is a proper LLMProvider subclass."""
    provider = GeminiProvider()
    assert isinstance(provider, LLMProvider)


# --- Backward compatibility tests ---


def test_gemini_wrapper_invoke_agent_still_importable() -> None:
    """Test that invoke_agent can still be imported from gemini_wrapper."""
    from sase.gemini_wrapper import invoke_agent as gw_invoke_agent

    assert callable(gw_invoke_agent)


def test_gemini_wrapper_log_prompt_still_importable() -> None:
    """Test that _log_prompt_and_response is still importable from wrapper."""
    from sase.gemini_wrapper.wrapper import _log_prompt_and_response as log_fn

    assert callable(log_fn)


def test_gemini_wrapper_stream_output_still_importable() -> None:
    """Test that _stream_process_output is still importable from wrapper."""
    from sase.gemini_wrapper.wrapper import _stream_process_output as stream_fn

    assert callable(stream_fn)


def test_llm_provider_invoke_agent_importable() -> None:
    """Test that invoke_agent can be imported from llm_provider."""
    from sase.llm_provider import invoke_agent as llm_invoke_agent

    assert callable(llm_invoke_agent)


# --- claude.py tests ---


def test_claude_provider_is_llm_provider() -> None:
    """Test that ClaudeCodeProvider is a proper LLMProvider subclass."""
    provider = ClaudeCodeProvider()
    assert isinstance(provider, LLMProvider)


@patch.dict(os.environ, {"SASE_CLAUDE_SMALL_ARGS": "--max-tokens 1000"})
@patch("sase.llm_provider.claude.stream_and_parse_json_output")
@patch("sase.llm_provider.claude.subprocess.Popen")
@patch("sase.llm_provider.claude.gemini_timer")
def test_claude_provider_extra_args_from_env_small(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    """Test that SASE_CLAUDE_SMALL_ARGS env var is parsed into command."""
    mock_process = MagicMock()
    mock_popen.return_value = mock_process
    mock_stream.return_value = ("response", "", 0)

    provider = ClaudeCodeProvider()
    provider.invoke("test", model_tier="small", suppress_output=True)

    call_args = mock_popen.call_args
    cmd = call_args[0][0]
    assert "--max-tokens" in cmd
    assert "1000" in cmd


def test_base_provider_resolve_model_name_returns_unknown() -> None:
    """Test that the base LLMProvider.resolve_model_name() returns 'unknown'."""

    class MinimalProvider(LLMProvider):
        def invoke(
            self,
            prompt: str,
            *,
            model_tier: ModelTier,
            suppress_output: bool = False,
            model_override: str | None = None,
        ) -> str:
            return ""

    provider = MinimalProvider()
    assert provider.resolve_model_name() == "unknown"


def test_claude_provider_resolve_model_name() -> None:
    """Test that ClaudeCodeProvider.resolve_model_name() returns correct names."""
    provider = ClaudeCodeProvider()
    assert provider.resolve_model_name() == "opus"
    assert provider.resolve_model_name("large") == "opus"
    assert provider.resolve_model_name("small") == "sonnet"


def test_gemini_provider_resolve_model_name() -> None:
    """Test that GeminiProvider.resolve_model_name() returns the default model."""
    provider = GeminiProvider()
    assert provider.resolve_model_name() == "gemini-3-flash-preview"
    assert provider.resolve_model_name("large") == "gemini-3-flash-preview"
    assert provider.resolve_model_name("small") == "gemini-3-flash-preview"


# --- codex.py tests ---


def test_codex_provider_is_llm_provider() -> None:
    """Test that CodexProvider is a proper LLMProvider subclass."""
    provider = CodexProvider()
    assert isinstance(provider, LLMProvider)


def test_codex_provider_resolve_model_name() -> None:
    """Test that CodexProvider.resolve_model_name() returns correct names."""
    provider = CodexProvider()
    assert provider.resolve_model_name() == "o3"
    assert provider.resolve_model_name("large") == "o3"
    assert provider.resolve_model_name("small") == "o4-mini"


@patch.dict(os.environ, {"SASE_CODEX_SMALL_ARGS": "--max-tokens 2000"})
@patch("sase.llm_provider.codex.stream_and_parse_codex_json_output")
@patch("sase.llm_provider.codex.subprocess.Popen")
@patch("sase.llm_provider.codex.gemini_timer")
def test_codex_provider_extra_args_from_env_small(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    """Test that SASE_CODEX_SMALL_ARGS env var is parsed into command."""
    mock_process = MagicMock()
    mock_popen.return_value = mock_process
    mock_stream.return_value = ("response", "", 0)

    provider = CodexProvider()
    provider.invoke("test", model_tier="small", suppress_output=True)

    call_args = mock_popen.call_args
    cmd = call_args[0][0]
    assert "--max-tokens" in cmd
    assert "2000" in cmd


@patch("sase.llm_provider.codex.stream_and_parse_codex_json_output")
@patch("sase.llm_provider.codex.subprocess.Popen")
@patch("sase.llm_provider.codex.gemini_timer")
def test_codex_provider_raises_on_failure(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    """Test that CodexProvider raises CalledProcessError on non-zero exit."""
    mock_process = MagicMock()
    mock_popen.return_value = mock_process
    mock_stream.return_value = ("", "some error", 1)

    provider = CodexProvider()
    with pytest.raises(subprocess.CalledProcessError) as exc_info:
        provider.invoke("test", model_tier="large", suppress_output=True)

    assert exc_info.value.returncode == 1
    assert exc_info.value.stderr == "some error"


@patch("sase.llm_provider.codex.stream_and_parse_codex_json_output")
@patch("sase.llm_provider.codex.subprocess.Popen")
@patch("sase.llm_provider.codex.gemini_timer")
def test_codex_provider_model_override(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    """Test that model_override bypasses tier mapping."""
    mock_process = MagicMock()
    mock_popen.return_value = mock_process
    mock_stream.return_value = ("response", "", 0)

    provider = CodexProvider()
    provider.invoke(
        "test", model_tier="large", suppress_output=True, model_override="custom-model"
    )

    call_args = mock_popen.call_args
    cmd = call_args[0][0]
    assert "custom-model" in cmd
    assert "o3" not in cmd


@patch("sase.llm_provider.codex.stream_and_parse_codex_json_output")
@patch("sase.llm_provider.codex.subprocess.Popen")
@patch("sase.llm_provider.codex.gemini_timer")
def test_codex_provider_normal_mode_command_construction(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    """Test full base_args construction in normal mode."""
    mock_process = MagicMock()
    mock_popen.return_value = mock_process
    mock_stream.return_value = ("response", "", 0)

    provider = CodexProvider()
    provider.invoke("test", model_tier="large", suppress_output=True)

    call_args = mock_popen.call_args
    cmd = call_args[0][0]
    assert cmd[0] == "codex"
    assert cmd[1] == "exec"
    assert "--model" in cmd
    assert "o3" in cmd
    assert "--dangerously-bypass-approvals-and-sandbox" in cmd
    assert "--json" in cmd
    assert "--color" in cmd
    assert "never" in cmd
    assert "--skip-git-repo-check" in cmd
    assert "-" in cmd


@patch.dict(
    os.environ,
    {
        "SASE_LLM_LARGE_ARGS": "--generic-arg val1",
        "SASE_CODEX_LARGE_ARGS": "--codex-arg val2",
    },
)
@patch("sase.llm_provider.codex.stream_and_parse_codex_json_output")
@patch("sase.llm_provider.codex.subprocess.Popen")
@patch("sase.llm_provider.codex.gemini_timer")
def test_codex_provider_generic_env_args_precedence(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    """Test that SASE_LLM_LARGE_ARGS takes precedence over SASE_CODEX_LARGE_ARGS."""
    mock_process = MagicMock()
    mock_popen.return_value = mock_process
    mock_stream.return_value = ("response", "", 0)

    provider = CodexProvider()
    provider.invoke("test", model_tier="large", suppress_output=True)

    call_args = mock_popen.call_args
    cmd = call_args[0][0]
    assert "--generic-arg" in cmd
    assert "val1" in cmd
    assert "--codex-arg" not in cmd


# --- codex NDJSON parser tests ---


def test_codex_json_parser_extracts_text() -> None:
    """Test that the Codex NDJSON parser extracts assistant text correctly."""
    ndjson_lines = [
        json.dumps({"type": "thread.started", "thread_id": "t1"}),
        json.dumps({"type": "turn.started"}),
        json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "id": "msg1",
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "Hello world"}],
                },
            }
        ),
        json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "id": "msg2",
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "Second response"}],
                },
            }
        ),
        json.dumps({"type": "turn.completed"}),
    ]
    script = "import sys; " + "; ".join(f"print({line!r})" for line in ndjson_lines)
    process = subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    text, stderr, rc = stream_and_parse_codex_json_output(process, suppress_output=True)

    assert rc == 0
    assert "Hello world" in text
    assert "Second response" in text


def test_codex_json_parser_handles_malformed_lines() -> None:
    """Test that the Codex NDJSON parser gracefully handles non-JSON lines."""
    lines = [
        "not json at all",
        json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "id": "msg1",
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "valid text"}],
                },
            }
        ),
        "{broken json",
    ]
    script = "import sys; " + "; ".join(f"print({line!r})" for line in lines)
    process = subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    text, stderr, rc = stream_and_parse_codex_json_output(process, suppress_output=True)

    assert rc == 0
    assert "valid text" in text


def test_codex_json_parser_captures_error_events() -> None:
    """Test that _process_codex_json_line captures error events."""
    assistant_texts: list[str] = []
    error_events: list[str] = []

    line = json.dumps({"type": "error", "message": "something went wrong"})
    _process_codex_json_line(line, assistant_texts, True, error_events)

    assert len(error_events) == 1
    assert "[error] something went wrong" in error_events[0]
    assert len(assistant_texts) == 0


def test_codex_json_parser_captures_turn_failed_events() -> None:
    """Test that _process_codex_json_line captures turn.failed events."""
    assistant_texts: list[str] = []
    error_events: list[str] = []

    line = json.dumps({"type": "turn.failed", "error": {"message": "turn failed"}})
    _process_codex_json_line(line, assistant_texts, True, error_events)

    assert len(error_events) == 1
    assert "[turn.failed] turn failed" in error_events[0]


def test_codex_json_parser_ignores_non_assistant_messages() -> None:
    """Test that item.completed with role != 'assistant' is ignored."""
    assistant_texts: list[str] = []
    error_events: list[str] = []

    line = json.dumps(
        {
            "type": "item.completed",
            "item": {
                "type": "message",
                "role": "user",
                "content": [{"type": "output_text", "text": "user message"}],
            },
        }
    )
    _process_codex_json_line(line, assistant_texts, True, error_events)

    assert len(assistant_texts) == 0


def test_codex_json_parser_error_events_appended_to_stderr_on_failure() -> None:
    """Test that error events are appended to stderr when return_code != 0."""
    ndjson_lines = [
        json.dumps({"type": "error", "message": "API error occurred"}),
    ]
    script = (
        "import sys; "
        + "; ".join(f"print({line!r})" for line in ndjson_lines)
        + "; sys.exit(1)"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    text, stderr, rc = stream_and_parse_codex_json_output(process, suppress_output=True)

    assert rc == 1
    assert "[error] API error occurred" in stderr


# --- _find_codex_plan_file tests ---


def test_find_codex_plan_file_returns_most_recent(tmp_path: Path) -> None:
    """Test that _find_codex_plan_file finds the newest .md file."""
    plans_dir = tmp_path / ".codex" / "plans"
    plans_dir.mkdir(parents=True)

    old_file = plans_dir / "old_plan.md"
    old_file.write_text("old plan")
    os.utime(old_file, (1000, 1000))

    new_file = plans_dir / "new_plan.md"
    new_file.write_text("new plan")
    os.utime(new_file, (2000, 2000))

    with patch.object(Path, "home", return_value=tmp_path):
        result = _find_codex_plan_file()

    assert result == str(new_file)


def test_find_codex_plan_file_filters_by_after(tmp_path: Path) -> None:
    """Test that _find_codex_plan_file respects after timestamp filter."""
    plans_dir = tmp_path / ".codex" / "plans"
    plans_dir.mkdir(parents=True)

    old_file = plans_dir / "old_plan.md"
    old_file.write_text("old")
    os.utime(old_file, (1000, 1000))

    new_file = plans_dir / "new_plan.md"
    new_file.write_text("new")
    os.utime(new_file, (2000, 2000))

    with patch.object(Path, "home", return_value=tmp_path):
        result = _find_codex_plan_file(after=1500)
    assert result == str(new_file)

    with patch.object(Path, "home", return_value=tmp_path):
        result = _find_codex_plan_file(after=2500)
    assert result is None


def test_find_codex_plan_file_returns_none_when_empty(tmp_path: Path) -> None:
    """Test that _find_codex_plan_file returns None with no matching files."""
    with patch.object(Path, "home", return_value=tmp_path):
        result = _find_codex_plan_file()

    assert result is None


# --- registry auto-detect tests ---


@patch("sase.llm_provider.registry.shutil.which")
@patch("sase.llm_provider.registry.get_llm_provider_config", return_value={})
def test_registry_auto_detect_codex(
    mock_config: MagicMock,
    mock_which: MagicMock,
) -> None:
    """Test that codex is auto-detected when claude is absent."""
    mock_which.side_effect = lambda name: "/usr/bin/codex" if name == "codex" else None

    from sase.llm_provider.registry import get_default_provider_name

    assert get_default_provider_name() == "codex"


@patch("sase.llm_provider.registry.shutil.which")
@patch("sase.llm_provider.registry.get_llm_provider_config", return_value={})
def test_registry_auto_detect_priority(
    mock_config: MagicMock,
    mock_which: MagicMock,
) -> None:
    """Test that claude wins over codex when both are available."""
    mock_which.side_effect = lambda name: f"/usr/bin/{name}"

    from sase.llm_provider.registry import get_default_provider_name

    assert get_default_provider_name() == "claude"


@patch("sase.llm_provider.claude.stream_and_parse_json_output")
@patch("sase.llm_provider.claude.subprocess.Popen")
@patch("sase.llm_provider.claude.gemini_timer")
def test_claude_provider_raises_on_failure(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    """Test that ClaudeCodeProvider raises CalledProcessError on non-zero exit."""
    mock_process = MagicMock()
    mock_popen.return_value = mock_process
    mock_stream.return_value = ("", "some error", 1)

    provider = ClaudeCodeProvider()
    with pytest.raises(subprocess.CalledProcessError) as exc_info:
        provider.invoke("test", model_tier="large", suppress_output=True)

    assert exc_info.value.returncode == 1
    assert exc_info.value.stderr == "some error"
