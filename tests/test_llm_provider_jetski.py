"""Tests for JetskiProvider invoke/command construction."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.llm_provider import jetski as jetski_mod
from sase.llm_provider.base import LLMProvider
from sase.llm_provider.jetski import JetskiProvider, _jetski_bin


def test_jetski_provider_is_llm_provider() -> None:
    """JetskiProvider must be an LLMProvider subclass."""
    provider = JetskiProvider()
    assert isinstance(provider, LLMProvider)


def test_jetski_provider_resolve_model_name() -> None:
    """resolve_model_name() returns the default Jetski model."""
    provider = JetskiProvider()
    default = jetski_mod._DEFAULT_MODEL
    assert provider.resolve_model_name() == default
    assert provider.resolve_model_name("large") == default
    assert provider.resolve_model_name("small") == default


def test_jetski_bin_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """SASE_JETSKI_PATH overrides the hardcoded default binary."""
    monkeypatch.setenv("SASE_JETSKI_PATH", "/custom/path/to/jetski")
    assert _jetski_bin() == "/custom/path/to/jetski"


def test_jetski_bin_falls_back_to_path_lookup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """With no env var and a missing default path, return 'jetski-cli'."""
    monkeypatch.delenv("SASE_JETSKI_PATH", raising=False)
    monkeypatch.setattr(jetski_mod, "_DEFAULT_BINARY", str(tmp_path / "does-not-exist"))
    assert _jetski_bin() == "jetski-cli"


def test_jetski_bin_uses_default_binary_when_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When the default binary path exists on disk, return it."""
    monkeypatch.delenv("SASE_JETSKI_PATH", raising=False)
    fake_bin = tmp_path / "jetski-binary"
    fake_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(jetski_mod, "_DEFAULT_BINARY", str(fake_bin))
    assert _jetski_bin() == str(fake_bin)


@patch("sase.llm_provider.jetski.stream_process_output")
@patch("sase.llm_provider.jetski.subprocess.Popen")
@patch("sase.llm_provider.jetski.gemini_timer")
def test_jetski_provider_model_override_not_in_argv(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    """Regression guard: ``model_override`` must NOT leak into argv.

    Jetski CLI has no ``--model`` flag — passing one corrupts the prompt.
    """
    mock_popen.return_value = MagicMock()
    mock_stream.return_value = ("response", "", 0)

    provider = JetskiProvider()
    provider.invoke(
        "test",
        model_tier="large",
        suppress_output=True,
        model_override="my-custom-jetski-model",
    )

    cmd = mock_popen.call_args[0][0]
    assert "my-custom-jetski-model" not in cmd
    assert not any(tok.startswith("--model") for tok in cmd)


@patch("sase.llm_provider.jetski.stream_process_output")
@patch("sase.llm_provider.jetski.subprocess.Popen")
@patch("sase.llm_provider.jetski.gemini_timer")
def test_jetski_provider_command_uses_p_mode(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    """``-p`` is present with the prompt as the positional arg; no ``--model``."""
    mock_popen.return_value = MagicMock()
    mock_stream.return_value = ("response", "", 0)

    provider = JetskiProvider()
    provider.invoke("my-test-prompt", model_tier="large", suppress_output=True)

    cmd = mock_popen.call_args[0][0]
    assert "-p" in cmd
    p_index = cmd.index("-p")
    assert cmd[p_index + 1] == "my-test-prompt"
    assert not any(tok.startswith("--model") for tok in cmd)


@patch("sase.llm_provider.jetski.stream_process_output")
@patch("sase.llm_provider.jetski.subprocess.Popen")
@patch("sase.llm_provider.jetski.gemini_timer")
def test_jetski_provider_does_not_write_to_stdin(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    """Regression guard: Jetski reads prompt from argv, so we must not write stdin."""
    mock_process = MagicMock()
    mock_popen.return_value = mock_process
    mock_stream.return_value = ("response", "", 0)

    provider = JetskiProvider()
    provider.invoke("test", model_tier="large", suppress_output=True)

    mock_process.stdin.write.assert_not_called()
    mock_process.stdin.close.assert_not_called()


@patch("sase.llm_provider.jetski.stream_process_output")
@patch("sase.llm_provider.jetski.subprocess.Popen")
@patch("sase.llm_provider.jetski.gemini_timer")
def test_jetski_provider_raises_on_failure(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    """Non-zero exit raises CalledProcessError carrying stderr."""
    mock_popen.return_value = MagicMock()
    mock_stream.return_value = ("", "boom", 1)

    provider = JetskiProvider()
    with pytest.raises(subprocess.CalledProcessError) as exc_info:
        provider.invoke("test", model_tier="large", suppress_output=True)

    assert exc_info.value.returncode == 1
    assert exc_info.value.stderr == "boom"


def test_jetski_provider_interrupt_cycle_rebuilds_prompt() -> None:
    """One interrupt → second invocation sees rebuilt prompt with prior response."""
    provider = JetskiProvider()

    call_count = {"n": 0}
    seen_prompts: list[str] = []

    def fake_run_subprocess(
        args: list[str], prompt: str, suppress_output: bool
    ) -> tuple[str, str, int]:
        seen_prompts.append(prompt)
        call_count["n"] += 1
        if call_count["n"] == 1:
            # Simulate the interrupt monitor setting the pending message.
            provider._pending_interrupt_message = "stop and do X"
            return ("first response", "", 0)
        return ("final response", "", 0)

    with patch.object(provider, "_run_subprocess", side_effect=fake_run_subprocess):
        result = provider.invoke(
            "original ask", model_tier="large", suppress_output=True
        )

    assert call_count["n"] == 2
    assert seen_prompts[0] == "original ask"
    rebuilt = seen_prompts[1]
    assert "original ask" in rebuilt
    assert "--- Your Previous Response ---" in rebuilt
    assert "first response" in rebuilt
    assert "--- User Follow-up ---" in rebuilt
    assert "stop and do X" in rebuilt

    assert "first response" in result.content
    assert "final response" in result.content
    assert result.usage is None
