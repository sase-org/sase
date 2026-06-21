"""Core AgyProvider (Antigravity CLI) command/model behavior tests."""

import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.llm_provider.agy import (
    AgyProvider,
    _AGY_PRINT_PROMPT_ARGV_BYTE_LIMIT,
    _wrap_agy_print_prompt,
)
from sase.llm_provider.base import LLMProvider
from sase.llm_provider.registry import resolve_model_provider
from sase.llm_provider.types import LLMInvocationError


def test_agy_provider_is_llm_provider() -> None:
    provider = AgyProvider()
    assert isinstance(provider, LLMProvider)


def test_agy_provider_resolve_model_name() -> None:
    provider = AgyProvider()
    assert provider.resolve_model_name() == "Gemini 3.5 Flash (High)"
    assert provider.resolve_model_name("large") == "Gemini 3.5 Flash (High)"
    assert provider.resolve_model_name("small") == "Gemini 3.5 Flash (Low)"


def test_agy_provider_metadata_hooks() -> None:
    provider = AgyProvider()
    assert provider.llm_provider_name() == "agy"
    assert provider.llm_provider_short_name() == "agy"
    assert provider.llm_autodetect_cli_name() == "agy"
    assert provider.llm_autodetect_priority() == 30
    assert provider.llm_skill_deploy_subpath() == ".gemini/antigravity-cli"
    assert provider.llm_cli_status_color() != "#4285F4"  # not Gemini blue
    context = provider.llm_skill_template_context()
    assert context["provider_name"] == "Antigravity"
    assert context["provider_tool_name"] == "Antigravity CLI"
    # Exact `agy models` display names with spaces/parens are preserved.
    assert "Gemini 3.5 Flash (High)" in provider.llm_known_model_names()
    assert "Claude Opus 4.6 (Thinking)" in provider.llm_known_model_names()
    aliases = provider.llm_model_short_aliases()
    assert aliases["Gemini 3.5 Flash (High)"] == "flash35h"


@patch("sase.llm_provider.agy.stream_process_output")
@patch("sase.llm_provider.agy.subprocess.Popen")
@patch("sase.llm_provider.agy.provider_timer")
def test_agy_provider_command_construction(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    mock_popen.return_value = MagicMock()
    mock_stream.return_value = ("response", "", 0)

    provider = AgyProvider()
    provider.invoke("test prompt", model_tier="large", suppress_output=True)

    cmd = mock_popen.call_args.args[0]
    assert cmd[0] == "agy"
    assert "--print-timeout" in cmd
    assert cmd[cmd.index("--print-timeout") + 1] == "24h"
    assert "--model" in cmd
    assert cmd[cmd.index("--model") + 1] == "Gemini 3.5 Flash (High)"
    assert "--dangerously-skip-permissions" in cmd
    assert "--add-dir" in cmd
    assert cmd[cmd.index("--add-dir") + 1] == str(Path.cwd().resolve())
    # The prompt is the value of --print and must be the final pair.
    assert cmd[-2] == "--print"
    assert "SASE Antigravity print-mode instructions" in cmd[-1]
    assert "Run commands synchronously" in cmd[-1]
    assert "never ask the user to approve" in cmd[-1]
    assert "--- User Prompt ---\ntest prompt" in cmd[-1]
    assert mock_popen.call_args.kwargs["text"] is True
    assert mock_popen.call_args.kwargs["cwd"] == str(Path.cwd().resolve())
    assert "stdin" not in mock_popen.call_args.kwargs


@patch("sase.llm_provider.agy.stream_process_output")
@patch("sase.llm_provider.agy.subprocess.Popen")
@patch("sase.llm_provider.agy.provider_timer")
def test_agy_provider_model_override_preserves_spaces(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    mock_popen.return_value = MagicMock()
    mock_stream.return_value = ("response", "", 0)

    provider = AgyProvider()
    provider.invoke(
        "test",
        model_tier="large",
        suppress_output=True,
        model_override="Claude Opus 4.6 (Thinking)",
    )

    cmd = mock_popen.call_args.args[0]
    assert cmd[cmd.index("--model") + 1] == "Claude Opus 4.6 (Thinking)"
    assert "Gemini 3.5 Flash (High)" not in cmd


@patch.dict(os.environ, {"SASE_AGY_PATH": "/opt/antigravity/bin/agy"})
@patch("sase.llm_provider.agy.stream_process_output")
@patch("sase.llm_provider.agy.subprocess.Popen")
@patch("sase.llm_provider.agy.provider_timer")
def test_agy_provider_uses_sase_agy_path(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    mock_popen.return_value = MagicMock()
    mock_stream.return_value = ("response", "", 0)

    provider = AgyProvider()
    provider.invoke("test", model_tier="large", suppress_output=True)

    assert mock_popen.call_args.args[0][0] == "/opt/antigravity/bin/agy"


@patch("sase.llm_provider.agy.stream_process_output")
@patch("sase.llm_provider.agy.subprocess.Popen")
@patch("sase.llm_provider.agy.provider_timer")
def test_agy_provider_pins_workspace_cwd_and_add_dir(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.delenv("CODEX_PROJECT_DIR", raising=False)
    monkeypatch.setenv("SASE_ACTIVE_PROJECT_DIR", str(workspace))
    mock_popen.return_value = MagicMock()
    mock_stream.return_value = ("response", "", 0)

    AgyProvider().invoke("test", model_tier="large", suppress_output=True)

    expected = str(workspace.resolve())
    cmd = mock_popen.call_args.args[0]
    assert cmd[cmd.index("--add-dir") + 1] == expected
    assert mock_popen.call_args.kwargs["cwd"] == expected


@patch.dict(os.environ, {"SASE_AGY_PRINT_TIMEOUT": "45m"})
@patch("sase.llm_provider.agy.stream_process_output")
@patch("sase.llm_provider.agy.subprocess.Popen")
@patch("sase.llm_provider.agy.provider_timer")
def test_agy_provider_print_timeout_env_override(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    mock_popen.return_value = MagicMock()
    mock_stream.return_value = ("response", "", 0)

    provider = AgyProvider()
    provider.invoke("test", model_tier="large", suppress_output=True)

    cmd = mock_popen.call_args.args[0]
    assert cmd[cmd.index("--print-timeout") + 1] == "45m"


@patch.dict(os.environ, {"SASE_AGY_SMALL_ARGS": "--sandbox"})
@patch("sase.llm_provider.agy.stream_process_output")
@patch("sase.llm_provider.agy.subprocess.Popen")
@patch("sase.llm_provider.agy.provider_timer")
def test_agy_provider_extra_args_from_env_small(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    mock_popen.return_value = MagicMock()
    mock_stream.return_value = ("response", "", 0)

    provider = AgyProvider()
    provider.invoke("test", model_tier="small", suppress_output=True)

    cmd = mock_popen.call_args.args[0]
    assert "--sandbox" in cmd
    assert cmd[cmd.index("--model") + 1] == "Gemini 3.5 Flash (Low)"


@patch.dict(
    os.environ,
    {
        "SASE_LLM_LARGE_ARGS": "--generic val1",
        "SASE_AGY_LARGE_ARGS": "--agy val2",
    },
)
@patch("sase.llm_provider.agy.stream_process_output")
@patch("sase.llm_provider.agy.subprocess.Popen")
@patch("sase.llm_provider.agy.provider_timer")
def test_agy_provider_generic_env_args_precedence(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    mock_popen.return_value = MagicMock()
    mock_stream.return_value = ("response", "", 0)

    provider = AgyProvider()
    provider.invoke("test", model_tier="large", suppress_output=True)

    cmd = mock_popen.call_args.args[0]
    assert "--generic" in cmd
    assert "val1" in cmd
    assert "--agy" not in cmd


@patch("sase.llm_provider.agy.subprocess.Popen")
def test_agy_provider_missing_executable_error_mentions_resolution_paths(
    mock_popen: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SASE_AGY_PATH", raising=False)
    mock_popen.side_effect = FileNotFoundError("missing")

    provider = AgyProvider()
    with pytest.raises(FileNotFoundError) as exc_info:
        provider.invoke("test", model_tier="large", suppress_output=True)

    message = str(exc_info.value)
    assert "SASE_AGY_PATH" in message
    assert "PATH" in message


@patch("sase.llm_provider.agy.subprocess.Popen")
def test_agy_provider_rejects_oversized_print_prompt_before_spawn(
    mock_popen: MagicMock,
) -> None:
    provider = AgyProvider()
    prompt = "x" * (_AGY_PRINT_PROMPT_ARGV_BYTE_LIMIT + 1)

    with pytest.raises(LLMInvocationError) as exc_info:
        provider.invoke(prompt, model_tier="large", suppress_output=True)

    mock_popen.assert_not_called()
    message = str(exc_info.value)
    assert "argv transport" in message
    assert "stdin/prompt-file" in message
    assert "Antigravity CLI" in message


@patch("sase.llm_provider.agy.subprocess.Popen")
def test_agy_provider_rejects_prompt_when_wrapped_prompt_is_oversized(
    mock_popen: MagicMock,
) -> None:
    provider = AgyProvider()
    wrapper_bytes = len(_wrap_agy_print_prompt("").encode("utf-8"))
    prompt = "x" * (_AGY_PRINT_PROMPT_ARGV_BYTE_LIMIT - wrapper_bytes + 1)

    with pytest.raises(LLMInvocationError) as exc_info:
        provider.invoke(prompt, model_tier="large", suppress_output=True)

    mock_popen.assert_not_called()
    assert "argv transport" in str(exc_info.value)


@patch("sase.llm_provider.agy.stream_process_output")
@patch("sase.llm_provider.agy.subprocess.Popen")
@patch("sase.llm_provider.agy.provider_timer")
def test_agy_provider_raises_called_process_error_on_failure(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    mock_popen.return_value = MagicMock()
    mock_stream.return_value = ("", "agy failed", 2)

    provider = AgyProvider()
    with pytest.raises(subprocess.CalledProcessError) as exc_info:
        provider.invoke("test", model_tier="large", suppress_output=True)

    assert exc_info.value.returncode == 2
    assert exc_info.value.stderr == "agy failed"


@patch("sase.llm_provider.agy.stream_process_output")
@patch("sase.llm_provider.agy.subprocess.Popen")
@patch("sase.llm_provider.agy.provider_timer")
def test_agy_provider_interrupt_resume_prompt_construction(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    mock_popen.return_value = MagicMock()
    provider = AgyProvider()
    calls = {"n": 0}

    def _stream_side_effect(
        process: object, suppress_output: bool = False, clean_ansi: bool = False
    ) -> tuple[str, str, int]:
        calls["n"] += 1
        if calls["n"] == 1:
            # Simulate the interrupt monitor firing during the first cycle.
            provider._pending_interrupt_message = "please also add logging"
            return ("partial work", "", 0)
        return ("final answer", "", 0)

    mock_stream.side_effect = _stream_side_effect

    result = provider.invoke("original task", model_tier="large", suppress_output=True)

    assert calls["n"] == 2
    second_prompt = mock_popen.call_args_list[1].args[0][-1]
    assert "original task" in second_prompt
    assert "--- Work So Far ---" in second_prompt
    assert "partial work" in second_prompt
    assert "--- User Message ---" in second_prompt
    assert "please also add logging" in second_prompt
    assert result.content == "partial work\n\nfinal answer"
    assert result.usage is None


def test_agy_model_resolution_preserves_nested_provider_model() -> None:
    # Explicit provider/model syntax keeps the full model name (with spaces)
    # after the first slash.
    assert resolve_model_provider("agy/Gemini 3.5 Flash (High)") == (
        "agy",
        "Gemini 3.5 Flash (High)",
    )
    # Bare known model name resolves to the agy provider.
    assert resolve_model_provider("Gemini 3.5 Flash (High)") == (
        "agy",
        "Gemini 3.5 Flash (High)",
    )
