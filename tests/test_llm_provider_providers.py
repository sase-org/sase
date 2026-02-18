"""Tests for llm_provider implementations (Claude, Gemini, subprocess, backward compat)."""

import os
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest
from sase.llm_provider._subprocess import stream_process_output
from sase.llm_provider.base import LLMProvider
from sase.llm_provider.claude import ClaudeCodeProvider
from sase.llm_provider.gemini import GeminiProvider
from sase.llm_provider.registry import get_provider
from sase.llm_provider.types import ModelTier


# --- gemini.py / subprocess tests ---


def test_stream_process_output_basic() -> None:
    """Test basic streaming of process output."""
    process = subprocess.Popen(
        ["echo", "hello world"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    stdout, stderr, return_code = stream_process_output(process, suppress_output=True)

    assert "hello world" in stdout
    assert stderr == ""
    assert return_code == 0


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


def test_stream_process_output_nonzero_exit() -> None:
    """Test streaming when process exits with non-zero code."""
    process = subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.exit(42)"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    stdout, stderr, return_code = stream_process_output(process, suppress_output=True)

    assert return_code == 42


def test_gemini_provider_is_llm_provider() -> None:
    """Test that GeminiProvider is a proper LLMProvider subclass."""
    provider = GeminiProvider()
    assert isinstance(provider, LLMProvider)


# --- Backward compatibility tests ---


def test_gemini_wrapper_invoke_agent_still_importable() -> None:
    """Test that invoke_agent can still be imported from gemini_wrapper."""
    from sase.gemini_wrapper import invoke_agent as gw_invoke_agent

    assert callable(gw_invoke_agent)


def test_gemini_wrapper_command_wrapper_still_importable() -> None:
    """Test that GeminiCommandWrapper can still be imported from gemini_wrapper."""
    from sase.gemini_wrapper import GeminiCommandWrapper

    wrapper = GeminiCommandWrapper()
    assert wrapper.model_size == "big"
    assert wrapper.agent_type == "agent"


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


def test_claude_provider_registered() -> None:
    """Test that ClaudeCodeProvider is registered as 'claude'."""
    provider = get_provider("claude")
    assert isinstance(provider, ClaudeCodeProvider)


@patch("sase.llm_provider.claude.stream_and_parse_json_output")
@patch("sase.llm_provider.claude.subprocess.Popen")
@patch("sase.llm_provider.claude.gemini_timer")
def test_claude_provider_builds_correct_command_large(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    """Test that ClaudeCodeProvider builds the correct command for large tier."""
    mock_process = MagicMock()
    mock_popen.return_value = mock_process
    mock_stream.return_value = ("response text", "", 0)

    provider = ClaudeCodeProvider()
    result = provider.invoke("test prompt", model_tier="large", suppress_output=True)

    # Verify Popen was called with correct args
    call_args = mock_popen.call_args
    cmd = call_args[0][0]
    assert cmd[0] == "claude"
    assert "-p" in cmd
    assert "--model" in cmd
    model_idx = cmd.index("--model")
    assert cmd[model_idx + 1] == "opus"
    assert "--output-format" in cmd
    fmt_idx = cmd.index("--output-format")
    assert cmd[fmt_idx + 1] == "stream-json"
    assert "--dangerously-skip-permissions" in cmd

    assert result == "response text"


@patch("sase.llm_provider.claude.stream_and_parse_json_output")
@patch("sase.llm_provider.claude.subprocess.Popen")
@patch("sase.llm_provider.claude.gemini_timer")
def test_claude_provider_builds_correct_command_small(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    """Test that ClaudeCodeProvider uses sonnet for small tier."""
    mock_process = MagicMock()
    mock_popen.return_value = mock_process
    mock_stream.return_value = ("response text", "", 0)

    provider = ClaudeCodeProvider()
    provider.invoke("test prompt", model_tier="small", suppress_output=True)

    call_args = mock_popen.call_args
    cmd = call_args[0][0]
    model_idx = cmd.index("--model")
    assert cmd[model_idx + 1] == "sonnet"


@patch.dict(os.environ, {"SASE_CLAUDE_LARGE_ARGS": "--verbose --debug"})
@patch("sase.llm_provider.claude.stream_and_parse_json_output")
@patch("sase.llm_provider.claude.subprocess.Popen")
@patch("sase.llm_provider.claude.gemini_timer")
def test_claude_provider_extra_args_from_env_large(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    """Test that SASE_CLAUDE_LARGE_ARGS env var is parsed into command."""
    mock_process = MagicMock()
    mock_popen.return_value = mock_process
    mock_stream.return_value = ("response", "", 0)

    provider = ClaudeCodeProvider()
    provider.invoke("test", model_tier="large", suppress_output=True)

    call_args = mock_popen.call_args
    cmd = call_args[0][0]
    assert "--verbose" in cmd
    assert "--debug" in cmd


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
    """Test that GeminiProvider.resolve_model_name() returns 'gemini'."""
    provider = GeminiProvider()
    assert provider.resolve_model_name() == "gemini"
    assert provider.resolve_model_name("large") == "gemini"
    assert provider.resolve_model_name("small") == "gemini"


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
