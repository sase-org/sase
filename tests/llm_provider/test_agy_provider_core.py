"""Core AgyProvider (Antigravity CLI) command/model behavior tests."""

import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.llm_provider.agy import (
    AgyProvider,
    _AGY_PRINT_PROMPT_ARGV_BYTE_LIMIT,
    _AGY_WORKSPACE_ENV_VARS,
    _wrap_agy_print_prompt,
)
from sase.llm_provider.base import LLMProvider
from sase.llm_provider.registry import resolve_model_provider
from sase.llm_provider.types import LLMInvocationError

_AGY_MODELS = [
    "gemini-3.8-flash-high",
    "gemini-3.8-flash-medium",
    "gemini-3.8-flash-low",
    "gemini-3.7-flash-high",
    "gemini-3.7-flash-medium",
    "gemini-3.7-flash-low",
    "gemini-3.6-flash-high",
    "gemini-3.6-flash-medium",
    "gemini-3.6-flash-low",
    "gemini-3.5-flash-high",
    "gemini-3.5-flash-medium",
    "gemini-3.5-flash-low",
    "gemini-3.1-pro-high",
    "gemini-3.1-pro-low",
    "claude-sonnet-4-6",
    "claude-opus-4-6-thinking",
    "gpt-oss-120b-medium",
]


def test_agy_provider_is_llm_provider() -> None:
    provider = AgyProvider()
    assert isinstance(provider, LLMProvider)


def test_agy_provider_resolve_model_name() -> None:
    provider = AgyProvider()
    assert provider.resolve_model_name() == "gemini-3.7-flash-high"
    assert provider.resolve_model_name("large") == "gemini-3.7-flash-high"
    assert provider.resolve_model_name("small") == "gemini-3.7-flash-low"


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
    assert provider.llm_known_model_names() == _AGY_MODELS
    aliases = provider.llm_model_short_aliases()
    assert aliases == {
        "gemini-3.8-flash-high": "flash38h",
        "gemini-3.8-flash-medium": "flash38m",
        "gemini-3.8-flash-low": "flash38l",
        "gemini-3.7-flash-high": "flash37h",
        "gemini-3.7-flash-medium": "flash37m",
        "gemini-3.7-flash-low": "flash37l",
        "gemini-3.6-flash-high": "flash36h",
        "gemini-3.6-flash-medium": "flash36m",
        "gemini-3.6-flash-low": "flash36l",
        "gemini-3.5-flash-high": "flash35h",
        "gemini-3.5-flash-medium": "flash35m",
        "gemini-3.5-flash-low": "flash35l",
        "gemini-3.1-pro-high": "pro31h",
        "gemini-3.1-pro-low": "pro31l",
        "claude-sonnet-4-6": "sonnet46",
        "claude-opus-4-6-thinking": "opus46t",
        "gpt-oss-120b-medium": "gptoss120m",
    }


@patch("sase.llm_provider.agy.stream_process_output")
@patch("sase.llm_provider.agy.subprocess.Popen")
@patch("sase.llm_provider.agy.provider_timer")
def test_agy_provider_command_construction(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # This test pins the no-env fallback contract (`--add-dir`/`cwd` default to
    # the current directory), so scrub every workspace-resolution env var that
    # `AgyProvider` honors. Otherwise an inherited or xdist-sibling-mutated value
    # (e.g. SASE_ACTIVE_PROJECT_DIR) makes the assertions flaky under CI.
    for env_name in _AGY_WORKSPACE_ENV_VARS:
        monkeypatch.delenv(env_name, raising=False)
    mock_popen.return_value = MagicMock()
    mock_stream.return_value = ("response", "", 0)

    provider = AgyProvider()
    provider.invoke("test prompt", model_tier="large", suppress_output=True)

    cmd = mock_popen.call_args.args[0]
    assert cmd[0] == "agy"
    assert "--print-timeout" in cmd
    assert cmd[cmd.index("--print-timeout") + 1] == "24h"
    assert "--model" in cmd
    assert cmd[cmd.index("--model") + 1] == "gemini-3.7-flash-high"
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
def test_agy_provider_model_override_preserves_slug(
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
        model_override="claude-opus-4-6-thinking",
    )

    cmd = mock_popen.call_args.args[0]
    assert cmd[cmd.index("--model") + 1] == "claude-opus-4-6-thinking"
    assert "gemini-3.7-flash-high" not in cmd


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


@patch("sase.llm_provider.agy.stream_process_output")
@patch("sase.llm_provider.agy.subprocess.Popen")
@patch("sase.llm_provider.agy.provider_timer")
def test_agy_provider_skips_missing_workspace_pin(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for env_name in _AGY_WORKSPACE_ENV_VARS:
        monkeypatch.delenv(env_name, raising=False)
    monkeypatch.setenv("SASE_ACTIVE_PROJECT_DIR", str(tmp_path / "deleted-workspace"))
    mock_popen.return_value = MagicMock()
    mock_stream.return_value = ("response", "", 0)

    AgyProvider().invoke("test", model_tier="large", suppress_output=True)

    expected = str(Path.cwd().resolve())
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
    assert cmd[cmd.index("--model") + 1] == "gemini-3.7-flash-low"


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
def test_agy_provider_missing_cwd_error_mentions_workspace_not_binary(
    mock_popen: MagicMock,
    tmp_path: Path,
) -> None:
    missing_workspace = tmp_path / "deleted-workspace"
    mock_popen.side_effect = FileNotFoundError("missing cwd")

    with pytest.raises(FileNotFoundError) as exc_info:
        AgyProvider()._run_subprocess(
            ["agy", "--print", "test"],
            suppress_output=True,
            cwd=str(missing_workspace),
        )

    message = str(exc_info.value)
    assert str(missing_workspace) in message
    assert "workspace directory" in message
    assert "SASE_AGY_PATH" not in message


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
    # Explicit provider/model syntax keeps the model slug after the first slash.
    assert resolve_model_provider("agy/gemini-3.6-flash-high") == (
        "agy",
        "gemini-3.6-flash-high",
    )
    # Bare known model name resolves to the agy provider.
    assert resolve_model_provider("gemini-3.6-flash-high") == (
        "agy",
        "gemini-3.6-flash-high",
    )


def test_agy_model_resolution_preserves_nested_provider_model_gemini_37() -> None:
    # Explicit provider/model syntax keeps the model slug after the first slash.
    assert resolve_model_provider("agy/gemini-3.7-flash-high") == (
        "agy",
        "gemini-3.7-flash-high",
    )
    # Bare known model name resolves to the agy provider.
    assert resolve_model_provider("gemini-3.7-flash-high") == (
        "agy",
        "gemini-3.7-flash-high",
    )
