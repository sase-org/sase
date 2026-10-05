"""GrokProvider command construction, effort, and CLI parse-probe tests."""

from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.llm_provider.grok import GrokProvider
from sase.llm_provider.types import LLMInvocationError, LLMInvocationOptions

from ._grok_provider_core_helpers import (
    clear_grok_env_vars,
    invoke_and_capture,
    require_grok_build,
)

_GROK_CONTROL_FLAGS = (
    "--no-plan",
    "--no-ask-user",
    "--no-auto-update",
    "--no-leader",
)


@pytest.fixture(autouse=True)
def _clear_grok_env(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_grok_env_vars(monkeypatch)


def test_grok_command_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cmd, kwargs, mock_process = invoke_and_capture(GrokProvider(), monkeypatch)

    assert cmd[:2] == ["/opt/grok/bin/grok", "--prompt-file"]
    assert cmd[cmd.index("--prompt-file") + 1] == "/dev/stdin"
    assert cmd[cmd.index("--output-format") + 1] == "streaming-messages-json"
    assert cmd[cmd.index("--permission-mode") + 1] == "bypassPermissions"
    assert cmd[cmd.index("--model") + 1] == "grok-4.7"
    assert cmd[cmd.index("--cwd") + 1] == os.getcwd()
    uuid.UUID(cmd[cmd.index("--session-id") + 1])
    for flag in _GROK_CONTROL_FLAGS:
        assert flag in cmd
    assert "--effort" not in cmd
    assert kwargs["stdin"] is subprocess.PIPE
    assert kwargs["stdout"] is subprocess.PIPE
    assert kwargs["stderr"] is subprocess.PIPE
    assert kwargs["text"] is True
    mock_process.stdin.write.assert_called_once_with("test prompt")
    mock_process.stdin.close.assert_called_once()


def test_grok_model_override_wins_over_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cmd, _, _ = invoke_and_capture(
        GrokProvider(), monkeypatch, model_override="grok-next"
    )

    assert cmd[cmd.index("--model") + 1] == "grok-next"
    assert "grok-4.7" not in cmd


@pytest.mark.parametrize("level", ["low", "medium", "high", "xhigh"])
def test_grok_accepts_the_verified_effort_table(level: str) -> None:
    args = GrokProvider().invocation_option_args(
        LLMInvocationOptions(reasoning_effort=level, explicit=True)
    )
    assert args == ["--effort", level]


@pytest.mark.parametrize("level", ["none", "minimal", "max"])
def test_grok_rejects_explicit_unsupported_effort(level: str) -> None:
    with pytest.raises(LLMInvocationError, match="Grok Build does not support"):
        GrokProvider().invocation_option_args(
            LLMInvocationOptions(reasoning_effort=level, explicit=True)
        )


@pytest.mark.parametrize("level", ["none", "minimal", "max"])
def test_grok_skips_config_default_unsupported_effort(
    level: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("WARNING", logger="sase.llm_provider._effort_args"):
        args = GrokProvider().invocation_option_args(
            LLMInvocationOptions(reasoning_effort=level, explicit=False)
        )
    assert args == []
    assert "Grok Build does not support" in caplog.text


def test_grok_appends_effort_flag_to_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cmd, _, _ = invoke_and_capture(
        GrokProvider(),
        monkeypatch,
        options=LLMInvocationOptions(reasoning_effort="xhigh", explicit=True),
    )

    assert cmd[cmd.index("--effort") + 1] == "xhigh"


def test_grok_generic_extra_args_take_precedence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_GROK_LARGE_ARGS", "--from-provider-env")
    monkeypatch.setenv("SASE_LLM_LARGE_ARGS", "--max-turns 5")

    cmd, _, _ = invoke_and_capture(GrokProvider(), monkeypatch)

    assert "--from-provider-env" not in cmd
    assert cmd[cmd.index("--max-turns") + 1] == "5"


def test_grok_provider_specific_extra_args_are_used_as_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_GROK_LARGE_ARGS", "--disable-web-search")

    cmd, _, _ = invoke_and_capture(GrokProvider(), monkeypatch)

    assert "--disable-web-search" in cmd


def test_grok_missing_executable_names_env_var_and_install_command() -> None:
    with (
        patch("sase.llm_provider.grok.subprocess.Popen", side_effect=FileNotFoundError),
        patch("sase.llm_provider.grok.provider_timer"),
        pytest.raises(FileNotFoundError) as excinfo,
    ):
        GrokProvider().invoke("prompt", model_tier="large", suppress_output=True)

    message = str(excinfo.value)
    assert "SASE_GROK_PATH" in message
    assert "PATH" in message
    assert "sase agent-cli install grok" in message


def test_grok_nonzero_exit_raises_called_process_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with (
        patch(
            "sase.llm_provider.grok.stream_and_parse_messages_json_output"
        ) as mock_stream,
        patch("sase.llm_provider.grok.subprocess.Popen") as mock_popen,
        patch("sase.llm_provider.grok.provider_timer"),
    ):
        mock_popen.return_value = MagicMock()
        mock_stream.return_value = ("partial", "boom", 1, {})
        with pytest.raises(subprocess.CalledProcessError) as excinfo:
            GrokProvider().invoke("prompt", model_tier="large", suppress_output=True)

    assert excinfo.value.returncode == 1
    assert excinfo.value.output == "partial"
    assert excinfo.value.stderr == "boom"


def test_grok_interrupt_preserves_partial_output_and_continues() -> None:
    provider = GrokProvider()
    prompts: list[str] = []
    timer_entries: list[str] = []

    class SingleUseTimer:
        def __init__(self, label: str) -> None:
            self.label = label
            self.entered = False

        def __enter__(self) -> None:
            if self.entered:
                raise AssertionError("timer context was reused")
            self.entered = True
            timer_entries.append(self.label)

        def __exit__(self, *args: object) -> None:
            return None

    def _fake_run(
        args: list[str],
        prompt: str,
        suppress_output: bool,
    ) -> tuple[str, str, int, dict[str, int]]:
        del args, suppress_output
        prompts.append(prompt)
        if len(prompts) == 1:
            provider._pending_interrupt_message = "also update the tests"
            return ("first pass", "", -15, {"input_tokens": 2})
        return ("second pass", "", 0, {"output_tokens": 3})

    with (
        patch(
            "sase.llm_provider.grok.provider_timer",
            side_effect=lambda label: SingleUseTimer(label),
        ),
        patch.object(GrokProvider, "_run_subprocess", side_effect=_fake_run),
    ):
        result = provider.invoke(
            "original task", model_tier="large", suppress_output=False
        )

    assert prompts[0] == "original task"
    assert "--- Work So Far ---\nfirst pass" in prompts[1]
    assert "--- User Message ---\nalso update the tests" in prompts[1]
    assert timer_entries == ["Waiting for Grok", "Waiting for Grok"]
    assert result.content == "first pass\n\nsecond pass"
    assert result.usage["input_tokens"] == 2
    assert result.usage["output_tokens"] == 3


@pytest.mark.parametrize("flag", _GROK_CONTROL_FLAGS)
def test_grok_cli_parse_probe_accepts_control_flag(
    flag: str,
    tmp_path: Path,
) -> None:
    grok = require_grok_build()
    result = subprocess.run(
        [
            grok,
            "--prompt-file",
            "/dev/stdin",
            "--output-format",
            "streaming-messages-json",
            "--permission-mode",
            "bypassPermissions",
            "--model",
            "definitely-not-a-model",
            "--cwd",
            str(tmp_path),
            flag,
        ],
        input="parse-probe",
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    output = f"{result.stdout}\n{result.stderr}"

    assert result.returncode != 0
    assert "unexpected argument" not in output


def test_grok_cli_parse_probe_rejects_unknown_flag(tmp_path: Path) -> None:
    grok = require_grok_build()
    result = subprocess.run(
        [
            grok,
            "--prompt-file",
            "/dev/stdin",
            "--output-format",
            "streaming-messages-json",
            "--permission-mode",
            "bypassPermissions",
            "--model",
            "definitely-not-a-model",
            "--cwd",
            str(tmp_path),
            "--bogus-flag-xyz",
        ],
        input="parse-probe",
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    output = f"{result.stdout}\n{result.stderr}"

    assert result.returncode != 0
    assert "unexpected argument '--bogus-flag-xyz'" in output
