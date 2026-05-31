"""Tests for CodexProvider shadow CODEX_HOME handling."""

import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.llm_provider.codex import (
    CodexProvider,
    _create_shadow_codex_home,
    _real_codex_home,
)


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


def test_create_shadow_codex_home_links_home_agents_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Home AGENTS.md is exposed when Codex-global files are absent."""
    home_agents = tmp_path / "AGENTS.md"
    home_agents.write_text("# Home Instructions\n", encoding="utf-8")
    real_home = tmp_path / ".codex"
    monkeypatch.setenv("HOME", str(tmp_path))

    shadow_home = _create_shadow_codex_home(real_home)

    shadow_agents = shadow_home / "AGENTS.md"
    assert shadow_agents.is_symlink()
    assert shadow_agents.resolve() == home_agents
    assert shadow_agents.read_text(encoding="utf-8") == "# Home Instructions\n"
    assert not real_home.exists()


def test_create_shadow_codex_home_preserves_real_codex_agents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A native Codex AGENTS.md remains the shadow global instruction file."""
    real_home = tmp_path / ".codex"
    real_home.mkdir()
    real_agents = real_home / "AGENTS.md"
    real_agents.write_text("# Codex Instructions\n", encoding="utf-8")
    home_agents = tmp_path / "AGENTS.md"
    home_agents.write_text("# Home Instructions\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(tmp_path))

    shadow_home = _create_shadow_codex_home(real_home)

    shadow_agents = shadow_home / "AGENTS.md"
    assert shadow_agents.is_symlink()
    assert shadow_agents.resolve() == real_agents
    assert shadow_agents.read_text(encoding="utf-8") == "# Codex Instructions\n"


def test_create_shadow_codex_home_preserves_real_codex_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A native Codex override suppresses the home AGENTS.md fallback."""
    real_home = tmp_path / ".codex"
    real_home.mkdir()
    real_override = real_home / "AGENTS.override.md"
    real_override.write_text("# Override Instructions\n", encoding="utf-8")
    home_agents = tmp_path / "AGENTS.md"
    home_agents.write_text("# Home Instructions\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(tmp_path))

    shadow_home = _create_shadow_codex_home(real_home)

    shadow_override = shadow_home / "AGENTS.override.md"
    shadow_agents = shadow_home / "AGENTS.md"
    assert shadow_override.is_symlink()
    assert shadow_override.resolve() == real_override
    assert not shadow_agents.exists()
    assert not shadow_agents.is_symlink()


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
    monkeypatch.delenv("CODEX_PROJECT_DIR", raising=False)
    monkeypatch.delenv("SASE_ACTIVE_PROJECT_DIR", raising=False)
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
def test_codex_provider_preserves_artifacts_dir_with_shadow_home(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Shadow CODEX_HOME isolation still passes SASE artifacts through."""
    real_home = tmp_path / "real-codex"
    artifacts_dir = tmp_path / "artifacts"
    real_home.mkdir()
    artifacts_dir.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(real_home))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))

    mock_process = MagicMock()
    mock_popen.return_value = mock_process
    mock_stream.return_value = ("response", "", 0)

    provider = CodexProvider()
    provider.invoke("test", model_tier="large", suppress_output=True)

    env = mock_popen.call_args.kwargs["env"]
    assert env["SASE_ARTIFACTS_DIR"] == str(artifacts_dir)
    assert Path(env["CODEX_HOME"]).parent == (
        tmp_path / ".cache" / "sase" / "codex_home"
    )


@patch("sase.llm_provider.codex.stream_and_parse_codex_json_output")
@patch("sase.llm_provider.codex.subprocess.Popen")
@patch("sase.llm_provider.codex.gemini_timer")
def test_codex_provider_sets_project_dir_from_active_project_dir(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Codex subprocesses inherit the workflow-assigned project dir."""
    real_home = tmp_path / "real-codex"
    real_home.mkdir()
    cwd = tmp_path / "cwd"
    active_project = tmp_path / "active-project"
    cwd.mkdir()
    active_project.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(real_home))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("CODEX_PROJECT_DIR", raising=False)
    monkeypatch.setenv("SASE_ACTIVE_PROJECT_DIR", str(active_project))
    monkeypatch.chdir(cwd)

    mock_process = MagicMock()
    mock_popen.return_value = mock_process
    mock_stream.return_value = ("response", "", 0)

    provider = CodexProvider()
    provider.invoke("test", model_tier="large", suppress_output=True)

    env = mock_popen.call_args.kwargs["env"]
    assert env["CODEX_PROJECT_DIR"] == str(active_project)


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
    config_text = 'model = "gpt-5.5"\n\n[features]\nhooks = true\n'
    real_config.write_text(config_text)
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

        assert shadow_config.read_text() == config_text
        assert "codex_hooks" not in shadow_config.read_text()
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

    assert real_config.read_text() == config_text
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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Opt-out skips shadow home while still passing Codex a project dir."""
    monkeypatch.delenv("CODEX_PROJECT_DIR", raising=False)
    monkeypatch.delenv("SASE_ACTIVE_PROJECT_DIR", raising=False)
    mock_process = MagicMock()
    mock_popen.return_value = mock_process
    mock_stream.return_value = ("response", "", 0)

    provider = CodexProvider()
    provider.invoke("test", model_tier="large", suppress_output=True)

    env = mock_popen.call_args.kwargs["env"]
    if "CODEX_HOME" in os.environ:
        assert env["CODEX_HOME"] == os.environ["CODEX_HOME"]
    else:
        assert "CODEX_HOME" not in env
    assert env["CODEX_PROJECT_DIR"] == os.getcwd()
