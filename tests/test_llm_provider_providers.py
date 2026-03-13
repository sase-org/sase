"""Tests for llm_provider implementations (Claude, Gemini, Codex, subprocess, backward compat)."""

import json
import os
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest
from pathlib import Path

from sase.llm_provider._subprocess import (
    _flush_codex_reasoning,
    _format_codex_action,
    _process_codex_json_line,
    _write_codex_thinking,
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
    assert provider.resolve_model_name() == "gpt-5.4"
    assert provider.resolve_model_name("large") == "gpt-5.4"
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
    assert "gpt-5.4" not in cmd


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
    assert "gpt-5.4" in cmd
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
                    "id": "item_0",
                    "type": "agent_message",
                    "text": "Hello world",
                },
            }
        ),
        json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "id": "item_1",
                    "type": "agent_message",
                    "text": "Second response",
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
                    "id": "item_0",
                    "type": "agent_message",
                    "text": "valid text",
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


def test_codex_json_parser_ignores_non_agent_message_items() -> None:
    """Test that item.completed with type != 'agent_message' is ignored."""
    assistant_texts: list[str] = []
    error_events: list[str] = []

    line = json.dumps(
        {
            "type": "item.completed",
            "item": {
                "id": "item_0",
                "type": "error",
                "message": "some error",
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


# --- codex reasoning / thinking tests ---


def test_codex_reasoning_captured_to_thinking_file(tmp_path: Path) -> None:
    """Test that reasoning items from Codex NDJSON are written to codex_thinking.jsonl."""
    thinking_path = tmp_path / "codex_thinking.jsonl"

    ndjson_lines = [
        json.dumps({"type": "thread.started", "thread_id": "t1"}),
        json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "type": "reasoning",
                    "id": "rs_001",
                    "summary": [
                        {"type": "summary_text", "text": "Let me think about this..."},
                    ],
                },
            }
        ),
        json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "type": "agent_message",
                    "text": "Here is my answer",
                },
            }
        ),
    ]

    with patch.dict(os.environ, {"SASE_ARTIFACTS_DIR": str(tmp_path)}):
        script = "import sys; " + "; ".join(f"print({line!r})" for line in ndjson_lines)
        process = subprocess.Popen(
            [sys.executable, "-c", script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        text, stderr, rc = stream_and_parse_codex_json_output(
            process, suppress_output=True
        )

    assert rc == 0
    assert "Here is my answer" in text

    # Verify thinking file was written
    assert thinking_path.exists()
    entries = [
        json.loads(line) for line in thinking_path.read_text().strip().splitlines()
    ]
    assert len(entries) == 1
    assert entries[0]["text"] == "Let me think about this..."
    assert "timestamp" in entries[0]


def test_write_codex_thinking_extracts_summary_text() -> None:
    """Test that _write_codex_thinking extracts text from summary parts."""
    from io import StringIO

    f = StringIO()
    item = {
        "type": "reasoning",
        "id": "rs_001",
        "summary": [
            {"type": "summary_text", "text": "First thought"},
            {"type": "summary_text", "text": "Second thought"},
        ],
    }
    _write_codex_thinking(item, f)

    entries = [json.loads(line) for line in f.getvalue().strip().splitlines()]
    assert len(entries) == 1
    assert "First thought" in entries[0]["text"]
    assert "Second thought" in entries[0]["text"]


def test_write_codex_thinking_ignores_empty_summary() -> None:
    """Test that _write_codex_thinking skips items with no summary text."""
    from io import StringIO

    f = StringIO()
    _write_codex_thinking({"type": "reasoning", "summary": []}, f)
    assert f.getvalue() == ""

    f2 = StringIO()
    _write_codex_thinking({"type": "reasoning"}, f2)
    assert f2.getvalue() == ""


def test_process_codex_json_line_writes_reasoning_to_thinking_file() -> None:
    """Test that _process_codex_json_line routes reasoning items to thinking_file."""
    from io import StringIO

    assistant_texts: list[str] = []
    error_events: list[str] = []
    thinking_file = StringIO()

    line = json.dumps(
        {
            "type": "item.completed",
            "item": {
                "type": "reasoning",
                "id": "rs_001",
                "summary": [{"type": "summary_text", "text": "deep thoughts"}],
            },
        }
    )
    _process_codex_json_line(
        line, assistant_texts, True, error_events, None, thinking_file
    )

    assert len(assistant_texts) == 0  # Reasoning is not assistant text
    entries = [json.loads(ln) for ln in thinking_file.getvalue().strip().splitlines()]
    assert len(entries) == 1
    assert entries[0]["text"] == "deep thoughts"


def test_codex_reasoning_following_action_from_function_call() -> None:
    """Test that reasoning gets following_action when a function_call follows."""
    from io import StringIO

    assistant_texts: list[str] = []
    thinking_file = StringIO()
    pending: list[dict[str, object]] = []

    # Send reasoning
    reasoning_line = json.dumps(
        {
            "type": "item.completed",
            "item": {
                "type": "reasoning",
                "summary": [{"type": "summary_text", "text": "thinking..."}],
            },
        }
    )
    _process_codex_json_line(
        reasoning_line, assistant_texts, True, None, None, thinking_file, pending
    )
    # Reasoning should be buffered, not written yet
    assert thinking_file.getvalue() == ""
    assert len(pending) == 1

    # Send function_call
    func_line = json.dumps(
        {
            "type": "item.completed",
            "item": {
                "type": "function_call",
                "name": "read_file",
                "arguments": '{"path": "/home/user/config.py"}',
            },
        }
    )
    _process_codex_json_line(
        func_line, assistant_texts, True, None, None, thinking_file, pending
    )

    # Reasoning should now be written with following_action
    entries = [json.loads(ln) for ln in thinking_file.getvalue().strip().splitlines()]
    assert len(entries) == 1
    assert entries[0]["text"] == "thinking..."
    assert entries[0]["following_action"] == "Read config.py"
    assert len(pending) == 0


def test_codex_reasoning_following_action_from_agent_message() -> None:
    """Test that reasoning gets text following_action when agent_message follows."""
    from io import StringIO

    assistant_texts: list[str] = []
    thinking_file = StringIO()
    pending: list[dict[str, object]] = []

    # Send reasoning
    reasoning_line = json.dumps(
        {
            "type": "item.completed",
            "item": {
                "type": "reasoning",
                "summary": [{"type": "summary_text", "text": "deep thought"}],
            },
        }
    )
    _process_codex_json_line(
        reasoning_line, assistant_texts, True, None, None, thinking_file, pending
    )

    # Send agent_message
    msg_line = json.dumps(
        {
            "type": "item.completed",
            "item": {"type": "agent_message", "text": "Here is the answer"},
        }
    )
    _process_codex_json_line(
        msg_line, assistant_texts, True, None, None, thinking_file, pending
    )

    entries = [json.loads(ln) for ln in thinking_file.getvalue().strip().splitlines()]
    assert len(entries) == 1
    assert entries[0]["following_action"] == "Here is the answer"


def test_codex_consecutive_reasoning_flushes_previous() -> None:
    """Test that consecutive reasoning items flush the previous without action."""
    from io import StringIO

    assistant_texts: list[str] = []
    thinking_file = StringIO()
    pending: list[dict[str, object]] = []

    # Send first reasoning
    r1 = json.dumps(
        {
            "type": "item.completed",
            "item": {
                "type": "reasoning",
                "summary": [{"type": "summary_text", "text": "thought 1"}],
            },
        }
    )
    _process_codex_json_line(
        r1, assistant_texts, True, None, None, thinking_file, pending
    )
    assert thinking_file.getvalue() == ""

    # Send second reasoning (should flush first without action)
    r2 = json.dumps(
        {
            "type": "item.completed",
            "item": {
                "type": "reasoning",
                "summary": [{"type": "summary_text", "text": "thought 2"}],
            },
        }
    )
    _process_codex_json_line(
        r2, assistant_texts, True, None, None, thinking_file, pending
    )

    entries = [json.loads(ln) for ln in thinking_file.getvalue().strip().splitlines()]
    assert len(entries) == 1
    assert entries[0]["text"] == "thought 1"
    assert "following_action" not in entries[0]

    # Flush remaining
    _flush_codex_reasoning(pending, thinking_file, None)
    entries = [json.loads(ln) for ln in thinking_file.getvalue().strip().splitlines()]
    assert len(entries) == 2
    assert entries[1]["text"] == "thought 2"


def test_format_codex_action_shell() -> None:
    """Test formatting of Codex shell/container.exec function calls."""
    item = {"name": "shell", "arguments": '{"command": "ls -la /tmp"}'}
    assert _format_codex_action(item) == "Bash `ls`"

    item2 = {"name": "container.exec", "arguments": '{"command": ["git", "status"]}'}
    assert _format_codex_action(item2) == "Bash `git`"


def test_format_codex_action_read_write() -> None:
    """Test formatting of Codex read/write function calls."""
    item = {"name": "read_file", "arguments": '{"path": "/home/user/src/main.py"}'}
    assert _format_codex_action(item) == "Read main.py"

    item2 = {
        "name": "write_file",
        "arguments": '{"path": "/home/user/config.yml"}',
    }
    assert _format_codex_action(item2) == "Edit config.yml"


def test_format_codex_action_unknown() -> None:
    """Test that unknown Codex tool names are returned as-is."""
    item = {"name": "web_search", "arguments": "{}"}
    assert _format_codex_action(item) == "web_search"


def test_format_codex_action_empty_name() -> None:
    """Test that empty/missing name returns None."""
    assert _format_codex_action({}) is None
    assert _format_codex_action({"name": ""}) is None


def test_write_codex_thinking_with_following_action() -> None:
    """Test that _write_codex_thinking includes following_action in JSONL."""
    from io import StringIO

    f = StringIO()
    item = {
        "type": "reasoning",
        "summary": [{"type": "summary_text", "text": "reasoning text"}],
    }
    _write_codex_thinking(item, f, following_action="Read config.py")

    entries = [json.loads(ln) for ln in f.getvalue().strip().splitlines()]
    assert len(entries) == 1
    assert entries[0]["following_action"] == "Read config.py"


def test_write_codex_thinking_omits_following_action_when_none() -> None:
    """Test that following_action key is absent when None."""
    from io import StringIO

    f = StringIO()
    item = {
        "type": "reasoning",
        "summary": [{"type": "summary_text", "text": "text"}],
    }
    _write_codex_thinking(item, f)

    entries = [json.loads(ln) for ln in f.getvalue().strip().splitlines()]
    assert "following_action" not in entries[0]


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
