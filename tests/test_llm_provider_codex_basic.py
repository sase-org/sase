"""Tests for CodexProvider command construction and invocation basics."""

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.feature_flags import override_flags
from sase.llm_provider.base import LLMProvider
from sase.llm_provider.codex import CodexProvider
from sase.llm_provider._subprocess_codex import CodexStreamResult
from sase.llm_provider.instruction_delivery import (
    CHANNEL_CODEX_ROOT,
    ActiveInstructionDelivery,
    ActiveSlot,
    SlotPlan,
    bind_instruction_delivery,
    legacy_instruction_delivery,
    reset_instruction_delivery,
)


def test_codex_provider_is_llm_provider() -> None:
    """Test that CodexProvider is a proper LLMProvider subclass."""
    provider = CodexProvider()
    assert isinstance(provider, LLMProvider)


def test_codex_provider_resolve_model_name() -> None:
    """Test that CodexProvider.resolve_model_name() returns correct names."""
    provider = CodexProvider()
    assert provider.resolve_model_name() == "gpt-6.1-sol"
    assert provider.resolve_model_name("large") == "gpt-6.1-sol"
    assert provider.resolve_model_name("small") == "codex-mini-latest"


def test_codex_provider_explicit_legacy_sol_override_passes_through() -> None:
    """An explicit GPT-5.6 Sol override still selects the legacy model."""
    with (
        patch(
            "sase.llm_provider.codex.stream_and_parse_codex_json_output"
        ) as mock_stream,
        patch("sase.llm_provider.codex.subprocess.Popen") as mock_popen,
        patch("sase.llm_provider.codex.provider_timer"),
    ):
        mock_popen.return_value = MagicMock()
        mock_stream.return_value = ("response", "", 0)
        provider = CodexProvider()
        provider.invoke(
            "test",
            model_tier="large",
            suppress_output=True,
            model_override="gpt-5.6-sol",
        )
        cmd = mock_popen.call_args[0][0]
        assert "gpt-5.6-sol" in cmd
        assert "gpt-6.1-sol" not in cmd


@patch.dict(os.environ, {"SASE_CODEX_SMALL_ARGS": "--max-tokens 2000"})
@patch("sase.llm_provider.codex.stream_and_parse_codex_json_output")
@patch("sase.llm_provider.codex.subprocess.Popen")
@patch("sase.llm_provider.codex.provider_timer")
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
@patch("sase.llm_provider.codex.provider_timer")
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


@patch.dict(os.environ, {"SASE_CODEX_PATH": "/opt/openai/bin/codex"})
@patch("sase.llm_provider.codex.stream_and_parse_codex_json_output")
@patch("sase.llm_provider.codex.subprocess.Popen")
@patch("sase.llm_provider.codex.provider_timer")
def test_codex_version_rejection_names_launched_executable(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    """A stale-CLI rejection keeps the original message and names the binary."""
    mock_process = MagicMock()
    mock_popen.return_value = mock_process
    original = (
        "The 'gpt-6-astra' model requires a newer version of Codex. Please update."
    )
    mock_stream.return_value = ("", original, 1)

    provider = CodexProvider()
    with pytest.raises(subprocess.CalledProcessError) as exc_info:
        provider.invoke("test", model_tier="large", suppress_output=True)

    stderr = exc_info.value.stderr
    assert original in stderr
    assert "SASE launched /opt/openai/bin/codex" in stderr
    assert "sase agent-cli list" in stderr
    assert "SASE_CODEX_PATH" in stderr


@patch("sase.llm_provider.codex.stream_and_parse_codex_json_output")
@patch("sase.llm_provider.codex.subprocess.Popen")
@patch("sase.llm_provider.codex.provider_timer")
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
    assert "gpt-6.1-sol" not in cmd


@patch.dict(os.environ, {"SASE_CODEX_PATH": "/opt/openai/bin/codex"})
@patch("sase.llm_provider.codex.stream_and_parse_codex_json_output")
@patch("sase.llm_provider.codex.subprocess.Popen")
@patch("sase.llm_provider.codex.provider_timer")
def test_codex_provider_uses_sase_codex_path(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    """Test that SASE_CODEX_PATH overrides Codex executable resolution."""
    mock_process = MagicMock()
    mock_popen.return_value = mock_process
    mock_stream.return_value = ("response", "", 0)

    provider = CodexProvider()
    provider.invoke("test", model_tier="large", suppress_output=True)

    cmd = mock_popen.call_args.args[0]
    assert cmd[0] == "/opt/openai/bin/codex"


@patch("sase.llm_provider.codex.stream_and_parse_codex_json_output")
@patch("sase.llm_provider.codex.subprocess.Popen")
@patch("sase.llm_provider.codex.provider_timer")
def test_codex_provider_uses_nvm_bin_fallback(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that NVM_BIN/codex is used when PATH lookup fails."""
    nvm_bin = tmp_path / "nvm" / "bin"
    nvm_bin.mkdir(parents=True)
    nvm_codex = nvm_bin / "codex"
    nvm_codex.write_text("#!/bin/sh\n")
    monkeypatch.delenv("SASE_CODEX_PATH", raising=False)
    monkeypatch.setenv("NVM_BIN", str(nvm_bin))
    monkeypatch.setattr("sase.llm_provider.codex.shutil.which", lambda _: None)

    mock_process = MagicMock()
    mock_popen.return_value = mock_process
    mock_stream.return_value = ("response", "", 0)

    provider = CodexProvider()
    provider.invoke("test", model_tier="large", suppress_output=True)

    cmd = mock_popen.call_args.args[0]
    assert cmd[0] == str(nvm_codex)


@patch("sase.llm_provider.codex.subprocess.Popen")
def test_codex_provider_missing_executable_error_mentions_resolution_paths(
    mock_popen: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test missing Codex executable errors name supported resolution paths."""
    monkeypatch.delenv("SASE_CODEX_PATH", raising=False)
    monkeypatch.delenv("NVM_BIN", raising=False)
    monkeypatch.setattr("sase.llm_provider.codex.shutil.which", lambda _: None)
    mock_popen.side_effect = FileNotFoundError("missing")

    provider = CodexProvider()
    with pytest.raises(FileNotFoundError) as exc_info:
        provider.invoke("test", model_tier="large", suppress_output=True)

    message = str(exc_info.value)
    assert "SASE_CODEX_PATH" in message
    assert "PATH" in message
    assert "NVM_BIN/codex" in message


@patch("sase.llm_provider.codex.stream_and_parse_codex_json_output")
@patch("sase.llm_provider.codex.subprocess.Popen")
@patch("sase.llm_provider.codex.provider_timer")
def test_codex_provider_normal_mode_command_construction(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test full base_args construction in normal mode."""
    monkeypatch.delenv("SASE_CODEX_PATH", raising=False)
    monkeypatch.delenv("NVM_BIN", raising=False)
    monkeypatch.setattr("sase.llm_provider.codex.shutil.which", lambda _: None)
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
    assert "gpt-6.1-sol" in cmd
    assert "--dangerously-bypass-approvals-and-sandbox" in cmd
    assert "--json" in cmd
    assert "--color" in cmd
    assert "never" in cmd
    assert "--skip-git-repo-check" in cmd
    developer_instruction = next(
        arg for arg in cmd if arg.startswith("developer_instructions=")
    )
    assert "yield_time_ms" in developer_instruction
    assert "write_stdin" in developer_instruction
    assert "-" in cmd


def test_codex_delivery_plan_obeys_sunset_flag() -> None:
    """Both provider plans remain reachable through the sunset flag."""
    provider = CodexProvider()
    with override_flags(codex_explicit_instructions=True):
        assert provider.instruction_delivery() == {
            "root": {
                "status": "explicit",
                "channel": CHANNEL_CODEX_ROOT,
                "max_bytes": 32 * 1024,
            },
            "subagent": {"status": "inherits_root"},
        }
    with override_flags(codex_explicit_instructions=False):
        assert provider.instruction_delivery() == legacy_instruction_delivery(
            reason="flag_disabled"
        )


@pytest.mark.parametrize("managed", [True, False])
def test_codex_explicit_argv_uses_bundle_and_scopes_project_doc_suppression(
    managed: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit root delivery replaces the directive and only suppresses managed docs."""
    bundle = (
        "# Root bundle\n<!-- sase-instructions bundle=123456789abc invocation=inv-1 -->"
    )
    delivery = ActiveInstructionDelivery(
        invocation_id="inv-1",
        provider="codex",
        root=ActiveSlot(
            SlotPlan("explicit", channel=CHANNEL_CODEX_ROOT, max_bytes=32 * 1024),
            text=bundle,
        ),
        subagent=ActiveSlot(SlotPlan("inherits_root")),
    )
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / ".codex"))
    monkeypatch.setattr(
        "sase.llm_provider.codex.project_is_sase_managed", lambda _cwd: managed
    )
    token = bind_instruction_delivery(delivery)
    try:
        with (
            override_flags(codex_explicit_instructions=True),
            patch(
                "sase.llm_provider.codex.stream_and_parse_codex_json_output",
                return_value=CodexStreamResult(
                    "response", "", 0, thread_id="thread-42"
                ),
            ),
            patch("sase.llm_provider.codex.subprocess.Popen") as mock_popen,
            patch("sase.llm_provider.codex.provider_timer"),
        ):
            mock_popen.return_value = MagicMock()
            CodexProvider().invoke("test", model_tier="large", suppress_output=True)
    finally:
        reset_instruction_delivery(token)

    command = mock_popen.call_args.args[0]
    developer_arg = next(
        arg for arg in command if arg.startswith("developer_instructions=")
    )
    assert json.loads(developer_arg.partition("=")[2]) == bundle
    assert ("project_doc_max_bytes=0" in command) is managed
    assert delivery.session_ids == ["thread-42"]


def test_codex_explicit_argv_stays_identical_on_interrupt_continuation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Interrupt reconstruction reuses one argv with one explicit bundle."""
    bundle = (
        "# Root bundle\n<!-- sase-instructions bundle=123456789abc invocation=inv-1 -->"
    )
    delivery = ActiveInstructionDelivery(
        invocation_id="inv-1",
        provider="codex",
        root=ActiveSlot(
            SlotPlan("explicit", channel=CHANNEL_CODEX_ROOT, max_bytes=32 * 1024),
            text=bundle,
        ),
        subagent=ActiveSlot(SlotPlan("inherits_root")),
    )
    provider = CodexProvider()
    provider._pending_interrupt_message = "Use this new direction."
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / ".codex"))
    monkeypatch.setattr(
        "sase.llm_provider.codex.project_is_sase_managed", lambda _cwd: True
    )
    token = bind_instruction_delivery(delivery)
    try:
        with (
            override_flags(codex_explicit_instructions=True),
            patch(
                "sase.llm_provider.codex.stream_and_parse_codex_json_output",
                side_effect=[
                    CodexStreamResult("first answer", "", 0),
                    CodexStreamResult("final answer", "", 0),
                ],
            ),
            patch("sase.llm_provider.codex.subprocess.Popen") as mock_popen,
            patch("sase.llm_provider.codex.provider_timer"),
        ):
            mock_popen.return_value = MagicMock()
            provider.invoke("test", model_tier="large", suppress_output=True)
    finally:
        reset_instruction_delivery(token)

    commands = [call.args[0] for call in mock_popen.call_args_list]
    assert len(commands) == 2
    assert commands[0] == commands[1]
    developer_arg = next(
        arg for arg in commands[0] if arg.startswith("developer_instructions=")
    )
    assert json.loads(developer_arg.partition("=")[2]) == bundle
    assert commands[0].count("project_doc_max_bytes=0") == 1


@patch.dict(
    os.environ,
    {
        "SASE_LLM_LARGE_ARGS": "--generic-arg val1",
        "SASE_CODEX_LARGE_ARGS": "--codex-arg val2",
    },
)
@patch("sase.llm_provider.codex.stream_and_parse_codex_json_output")
@patch("sase.llm_provider.codex.subprocess.Popen")
@patch("sase.llm_provider.codex.provider_timer")
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
