"""Tests for core Claude and base LLM provider behavior."""

from __future__ import annotations

import json
import os
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from sase.llm_provider.base import LLMProvider
from sase.llm_provider.claude import ClaudeCodeProvider, _SINGLE_TURN_DIRECTIVE
from sase.llm_provider.types import InvokeResult, ModelTier


def test_llm_provider_invoke_agent_importable() -> None:
    """Test that invoke_agent can be imported from llm_provider."""
    from sase.llm_provider import invoke_agent as llm_invoke_agent

    assert callable(llm_invoke_agent)


def test_claude_provider_is_llm_provider() -> None:
    """Test that ClaudeCodeProvider is a proper LLMProvider subclass."""
    provider = ClaudeCodeProvider()
    assert isinstance(provider, LLMProvider)


@patch.dict(os.environ, {"SASE_CLAUDE_SMALL_ARGS": "--max-tokens 1000"})
@patch("sase.llm_provider.claude.stream_and_parse_json_output")
@patch("sase.llm_provider.claude.subprocess.Popen")
@patch("sase.llm_provider.claude.provider_timer")
def test_claude_provider_extra_args_from_env_small(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    """Test that SASE_CLAUDE_SMALL_ARGS env var is parsed into command."""
    mock_process = MagicMock()
    mock_popen.return_value = mock_process
    mock_stream.return_value = (
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

    provider = ClaudeCodeProvider()
    provider.invoke("test", model_tier="small", suppress_output=True)

    call_args = mock_popen.call_args
    cmd = call_args[0][0]
    assert "--max-tokens" in cmd
    assert "1000" in cmd
    assert "--output-format" in cmd
    assert "stream-json" in cmd
    assert "--include-hook-events" not in cmd
    assert cmd[cmd.index("--append-system-prompt") + 1] == _SINGLE_TURN_DIRECTIVE
    denied_tools = set(cmd[cmd.index("--disallowedTools") + 1].split(","))
    assert denied_tools == {
        "ScheduleWakeup",
        "ListAgents",
        "Workflow",
        "Monitor",
        "CronCreate",
        "CronDelete",
        "RemoteTrigger",
    }
    assert "SendMessage" not in denied_tools
    settings = json.loads(cmd[cmd.index("--settings") + 1])
    assert settings["crossSessionInbound"] == "refuse"
    assert settings["hooks"]["PreToolUse"]


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
        ) -> InvokeResult:
            return InvokeResult(content="")

    provider = MinimalProvider()
    assert provider.resolve_model_name() == "unknown"


def test_claude_provider_resolve_model_name() -> None:
    """Test that ClaudeCodeProvider.resolve_model_name() returns correct names."""
    provider = ClaudeCodeProvider()
    assert provider.resolve_model_name() == "opus"
    assert provider.resolve_model_name("large") == "opus"
    assert provider.resolve_model_name("small") == "sonnet"


@patch("sase.llm_provider.claude.stream_and_parse_json_output")
@patch("sase.llm_provider.claude.subprocess.Popen")
@patch("sase.llm_provider.claude.provider_timer")
def test_claude_provider_raises_on_failure(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    """Test that ClaudeCodeProvider raises CalledProcessError on non-zero exit."""
    mock_process = MagicMock()
    mock_popen.return_value = mock_process
    mock_stream.return_value = (
        "",
        "some error",
        1,
        {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        },
    )

    provider = ClaudeCodeProvider()
    with pytest.raises(subprocess.CalledProcessError) as exc_info:
        provider.invoke("test", model_tier="large", suppress_output=True)

    assert exc_info.value.returncode == 1
    assert exc_info.value.stderr == "some error"
