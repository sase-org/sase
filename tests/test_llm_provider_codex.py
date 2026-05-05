"""Tests for CodexProvider invoke/command construction."""

import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.llm_provider.base import LLMProvider
from sase.llm_provider.codex import CodexProvider, _real_codex_home


def test_codex_provider_is_llm_provider() -> None:
    """Test that CodexProvider is a proper LLMProvider subclass."""
    provider = CodexProvider()
    assert isinstance(provider, LLMProvider)


def test_codex_provider_resolve_model_name() -> None:
    """Test that CodexProvider.resolve_model_name() returns correct names."""
    provider = CodexProvider()
    assert provider.resolve_model_name() == "gpt-5.5"
    assert provider.resolve_model_name("large") == "gpt-5.5"
    assert provider.resolve_model_name("small") == "codex-mini-latest"


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
    assert "gpt-5.5" not in cmd


@patch.dict(os.environ, {"SASE_CODEX_PATH": "/opt/openai/bin/codex"})
@patch("sase.llm_provider.codex.stream_and_parse_codex_json_output")
@patch("sase.llm_provider.codex.subprocess.Popen")
@patch("sase.llm_provider.codex.gemini_timer")
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
@patch("sase.llm_provider.codex.gemini_timer")
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
@patch("sase.llm_provider.codex.gemini_timer")
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
    assert "gpt-5.5" in cmd
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


def test_real_codex_home_ignores_sase_managed_shadow_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A nested SASE Codex shadow home is not treated as the real home."""
    inherited_shadow = tmp_path / ".cache" / "sase" / "codex_home" / "123-deadbeef"
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CODEX_HOME", str(inherited_shadow))

    assert _real_codex_home() == tmp_path / ".codex"


def test_real_codex_home_honors_non_sase_custom_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """User-managed custom CODEX_HOME values remain supported."""
    custom_home = tmp_path / "custom-codex"
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CODEX_HOME", str(custom_home))

    assert _real_codex_home() == custom_home


@patch("sase.llm_provider.codex.stream_and_parse_codex_json_output")
@patch("sase.llm_provider.codex.subprocess.Popen")
@patch("sase.llm_provider.codex.gemini_timer")
def test_codex_provider_uses_shadow_codex_home_by_default(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that Codex subprocesses receive a disposable CODEX_HOME."""
    real_home = tmp_path / "real-codex"
    real_home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(real_home))
    monkeypatch.setenv("HOME", str(tmp_path))

    mock_process = MagicMock()
    mock_popen.return_value = mock_process
    mock_stream.return_value = ("response", "", 0)

    provider = CodexProvider()
    provider.invoke("test", model_tier="large", suppress_output=True)

    env = mock_popen.call_args.kwargs["env"]
    shadow_home = Path(env["CODEX_HOME"])
    assert shadow_home != real_home
    assert shadow_home.parent == tmp_path / ".cache" / "sase" / "codex_home"
    assert not shadow_home.exists()


@patch("sase.llm_provider.codex.stream_and_parse_codex_json_output")
@patch("sase.llm_provider.codex.subprocess.Popen")
@patch("sase.llm_provider.codex.gemini_timer")
def test_codex_provider_sets_project_dir_with_shadow_home(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test Codex subprocesses receive shadow home and current project dir."""
    real_home = tmp_path / "real-codex"
    real_home.mkdir()
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(real_home))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(project_dir)

    mock_process = MagicMock()
    mock_popen.return_value = mock_process
    mock_stream.return_value = ("response", "", 0)

    provider = CodexProvider()
    provider.invoke("test", model_tier="large", suppress_output=True)

    env = mock_popen.call_args.kwargs["env"]
    assert Path(env["CODEX_HOME"]).parent == (
        tmp_path / ".cache" / "sase" / "codex_home"
    )
    assert env["CODEX_PROJECT_DIR"] == str(project_dir)


@patch("sase.llm_provider.codex.stream_and_parse_codex_json_output")
@patch("sase.llm_provider.codex.subprocess.Popen")
@patch("sase.llm_provider.codex.gemini_timer")
def test_codex_provider_shadow_home_copies_config_and_symlinks_state(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test shadow config isolation and symlinks for non-config entries."""
    real_home = tmp_path / "real-codex"
    real_home.mkdir()
    real_config = real_home / "config.toml"
    real_config.write_text('model = "gpt-5.5"\n')
    auth_file = real_home / "auth.json"
    auth_file.write_text("{}\n")
    skills_dir = real_home / "skills"
    skills_dir.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(real_home))
    monkeypatch.setenv("HOME", str(tmp_path))

    mock_process = MagicMock()
    mock_popen.return_value = mock_process
    observed_shadow_home: Path | None = None

    def mutate_shadow_config(
        process: MagicMock, suppress_output: bool
    ) -> tuple[str, str, int]:
        nonlocal observed_shadow_home
        observed_shadow_home = Path(mock_popen.call_args.kwargs["env"]["CODEX_HOME"])
        shadow_config = observed_shadow_home / "config.toml"

        assert shadow_config.read_text() == 'model = "gpt-5.5"\n'
        assert not shadow_config.is_symlink()
        assert (observed_shadow_home / "auth.json").is_symlink()
        assert (observed_shadow_home / "auth.json").resolve() == auth_file
        assert (observed_shadow_home / "skills").is_symlink()
        assert (observed_shadow_home / "skills").resolve() == skills_dir

        shadow_config.write_text('model = "mutated"\n')
        return "response", "", 0

    mock_stream.side_effect = mutate_shadow_config

    provider = CodexProvider()
    provider.invoke("test", model_tier="large", suppress_output=True)

    assert real_config.read_text() == 'model = "gpt-5.5"\n'
    assert observed_shadow_home is not None
    assert not observed_shadow_home.exists()


@patch("sase.llm_provider.codex.stream_and_parse_codex_json_output")
@patch("sase.llm_provider.codex.subprocess.Popen")
@patch("sase.llm_provider.codex.gemini_timer")
def test_codex_provider_deleted_inherited_shadow_uses_real_home_auth(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale inherited SASE shadow still links auth from the real ~/.codex."""
    real_home = tmp_path / ".codex"
    real_home.mkdir()
    auth_file = real_home / "auth.json"
    auth_file.write_text("{}\n")
    inherited_shadow = tmp_path / ".cache" / "sase" / "codex_home" / "123-deadbeef"
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CODEX_HOME", str(inherited_shadow))

    mock_process = MagicMock()
    mock_popen.return_value = mock_process
    observed_shadow_home: Path | None = None

    def inspect_shadow_home(
        process: MagicMock, suppress_output: bool
    ) -> tuple[str, str, int]:
        nonlocal observed_shadow_home
        observed_shadow_home = Path(mock_popen.call_args.kwargs["env"]["CODEX_HOME"])

        assert observed_shadow_home != inherited_shadow
        assert (observed_shadow_home / "auth.json").is_symlink()
        assert (observed_shadow_home / "auth.json").resolve() == auth_file
        return "response", "", 0

    mock_stream.side_effect = inspect_shadow_home

    provider = CodexProvider()
    provider.invoke("test", model_tier="large", suppress_output=True)

    assert observed_shadow_home is not None
    assert not observed_shadow_home.exists()


@patch("sase.llm_provider.codex.stream_and_parse_codex_json_output")
@patch("sase.llm_provider.codex.subprocess.Popen")
@patch("sase.llm_provider.codex.gemini_timer")
def test_codex_provider_cleans_shadow_home_after_failure(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that nonzero Codex results still clean up the shadow home."""
    real_home = tmp_path / "real-codex"
    real_home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(real_home))
    monkeypatch.setenv("HOME", str(tmp_path))

    mock_process = MagicMock()
    mock_popen.return_value = mock_process
    mock_stream.return_value = ("", "some error", 1)

    provider = CodexProvider()
    with pytest.raises(subprocess.CalledProcessError):
        provider.invoke("test", model_tier="large", suppress_output=True)

    shadow_home = Path(mock_popen.call_args.kwargs["env"]["CODEX_HOME"])
    assert not shadow_home.exists()


@patch.dict(os.environ, {"SASE_CODEX_DISABLE_SHADOW_HOME": "1"})
@patch("sase.llm_provider.codex.stream_and_parse_codex_json_output")
@patch("sase.llm_provider.codex.subprocess.Popen")
@patch("sase.llm_provider.codex.gemini_timer")
def test_codex_provider_shadow_home_opt_out_preserves_inherited_env(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
) -> None:
    """Test that SASE_CODEX_DISABLE_SHADOW_HOME=1 keeps Popen env inherited."""
    mock_process = MagicMock()
    mock_popen.return_value = mock_process
    mock_stream.return_value = ("response", "", 0)

    provider = CodexProvider()
    provider.invoke("test", model_tier="large", suppress_output=True)

    assert "env" not in mock_popen.call_args.kwargs
