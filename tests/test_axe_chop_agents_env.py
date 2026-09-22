"""Tests for managed scratch/build env wiring during agent launch."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.agent.launch_spawn import _managed_agent_scratch_env
from sase.config._settings import (
    DEFAULT_MANAGED_TMP_AGENT_CARGO_INCREMENTAL,
    get_managed_tmp_agent_cargo_incremental,
)
from sase.env_contracts import SASE_LAUNCH_SCRATCH_KEY_ENV
from sase.running_field import ClaimResult

from tests._axe_chop_agents_helpers import (
    _redirect_managed_tmpdir,
    _spawn_agent_for_env_test,
)

pytest_plugins = ["tests.axe_chop_agents_fixtures"]


def test_managed_agent_scratch_env_roots_cargo_target_under_managed_tmp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _redirect_managed_tmpdir(monkeypatch, tmp_path / "tmp")

    env = _managed_agent_scratch_env(
        safe_name="proj",
        workspace_num=3,
        timestamp="260101_120000",
    )

    scratch_key = "proj-ws3-260101_120000"
    cargo_target = tmp_path / "tmp" / "cargo-targets" / scratch_key
    assert env[SASE_LAUNCH_SCRATCH_KEY_ENV] == scratch_key
    assert env["CARGO_TARGET_DIR"] == str(cargo_target)
    assert env["CARGO_BUILD_BUILD_DIR"] == str(cargo_target / "build")
    assert env["CARGO_INCREMENTAL"] == "0"
    assert env["CARGO_PROFILE_DEV_DEBUG"] == "line-tables-only"
    assert env["CARGO_PROFILE_TEST_DEBUG"] == "line-tables-only"
    assert env["TMPDIR"] == str(tmp_path / "tmp" / "agent-tmp" / scratch_key)
    assert env["TMP"] == env["TMPDIR"]
    assert env["TEMP"] == env["TMPDIR"]
    assert Path(env["CARGO_TARGET_DIR"]).is_dir()


@patch("sase.running_field.claim_workspace", return_value=ClaimResult(success=True))
@patch("sase.core.agent_launch_facade.spawn_prepared_agent_process")
def test_spawn_agent_subprocess_removes_inherited_sase_codex_home(
    mock_spawn: MagicMock,
    mock_claim: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Detached agents do not inherit a parent SASE Codex shadow home."""
    inherited_shadow = tmp_path / ".cache" / "sase" / "codex_home" / "123-deadbeef"
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CODEX_HOME", str(inherited_shadow))

    _spawn_agent_for_env_test(
        tmp_path=tmp_path, monkeypatch=monkeypatch, mock_spawn=mock_spawn
    )

    env = mock_spawn.call_args.kwargs["env"]
    assert "CODEX_HOME" not in env


@patch("sase.running_field.claim_workspace", return_value=ClaimResult(success=True))
@patch("sase.core.agent_launch_facade.spawn_prepared_agent_process")
def test_spawn_agent_subprocess_preserves_custom_codex_home(
    mock_spawn: MagicMock,
    mock_claim: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Detached agents keep user-managed custom CODEX_HOME values."""
    custom_home = tmp_path / "custom-codex"
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CODEX_HOME", str(custom_home))

    _spawn_agent_for_env_test(
        tmp_path=tmp_path, monkeypatch=monkeypatch, mock_spawn=mock_spawn
    )

    env = mock_spawn.call_args.kwargs["env"]
    assert env["CODEX_HOME"] == str(custom_home)


@patch("sase.running_field.claim_workspace", return_value=ClaimResult(success=True))
@patch("sase.core.agent_launch_facade.spawn_prepared_agent_process")
def test_spawn_agent_subprocess_extra_env_codex_home_wins(
    mock_spawn: MagicMock,
    mock_claim: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit caller CODEX_HOME overrides are applied after sanitization."""
    inherited_shadow = tmp_path / ".cache" / "sase" / "codex_home" / "123-deadbeef"
    explicit_shadow = tmp_path / ".cache" / "sase" / "codex_home" / "explicit"
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CODEX_HOME", str(inherited_shadow))

    _spawn_agent_for_env_test(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        mock_spawn=mock_spawn,
        extra_env={"CODEX_HOME": str(explicit_shadow)},
    )

    env = mock_spawn.call_args.kwargs["env"]
    assert env["CODEX_HOME"] == str(explicit_shadow)


@patch("sase.running_field.claim_workspace", return_value=ClaimResult(success=True))
@patch("sase.core.agent_launch_facade.spawn_prepared_agent_process")
def test_spawn_agent_subprocess_routes_default_build_scratch_to_managed_tmp(
    mock_spawn: MagicMock,
    mock_claim: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Launched agents do not inherit host-global ``/tmp`` build scratch."""
    monkeypatch.setenv("TMPDIR", "/tmp/inherited")
    monkeypatch.setenv("TMP", "/tmp/inherited")
    monkeypatch.setenv("TEMP", "/tmp/inherited")
    monkeypatch.setenv("CARGO_TARGET_DIR", "/tmp/inherited-cargo-target")
    monkeypatch.setenv("CARGO_BUILD_BUILD_DIR", "/tmp/inherited-cargo-build")
    monkeypatch.setenv("CARGO_INCREMENTAL", "1")
    monkeypatch.setenv("CARGO_PROFILE_DEV_DEBUG", "2")
    monkeypatch.setenv("CARGO_PROFILE_TEST_DEBUG", "2")

    _spawn_agent_for_env_test(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        mock_spawn=mock_spawn,
    )

    env = mock_spawn.call_args.kwargs["env"]
    scratch_key = "proj-ws3-260101_120000"
    cargo_target = tmp_path / "tmp" / "cargo-targets" / scratch_key
    assert env[SASE_LAUNCH_SCRATCH_KEY_ENV] == scratch_key
    assert env["TMPDIR"] == str(tmp_path / "tmp" / "agent-tmp" / scratch_key)
    assert env["TMP"] == env["TMPDIR"]
    assert env["TEMP"] == env["TMPDIR"]
    assert env["CARGO_TARGET_DIR"] == str(cargo_target)
    assert env["CARGO_BUILD_BUILD_DIR"] == str(cargo_target / "build")
    assert env["CARGO_INCREMENTAL"] == "0"
    assert env["CARGO_PROFILE_DEV_DEBUG"] == "line-tables-only"
    assert env["CARGO_PROFILE_TEST_DEBUG"] == "line-tables-only"
    assert Path(env["TMPDIR"]).is_dir()
    assert Path(env["CARGO_TARGET_DIR"]).is_dir()


@patch("sase.running_field.claim_workspace", return_value=ClaimResult(success=True))
@patch("sase.core.agent_launch_facade.spawn_prepared_agent_process")
def test_spawn_agent_subprocess_preserves_explicit_build_scratch_env(
    mock_spawn: MagicMock,
    mock_claim: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Caller-provided launch env still wins over managed defaults."""
    explicit_tmp = tmp_path / "explicit-tmp"
    explicit_cargo = tmp_path / "explicit-cargo"

    _spawn_agent_for_env_test(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        mock_spawn=mock_spawn,
        extra_env={
            SASE_LAUNCH_SCRATCH_KEY_ENV: "spoofed",
            "TMPDIR": str(explicit_tmp),
            "TMP": str(explicit_tmp),
            "TEMP": str(explicit_tmp),
            "CARGO_TARGET_DIR": str(explicit_cargo),
        },
    )

    env = mock_spawn.call_args.kwargs["env"]
    assert env[SASE_LAUNCH_SCRATCH_KEY_ENV] == "proj-ws3-260101_120000"
    assert env["TMPDIR"] == str(explicit_tmp)
    assert env["TMP"] == str(explicit_tmp)
    assert env["TEMP"] == str(explicit_tmp)
    assert env["CARGO_TARGET_DIR"] == str(explicit_cargo)
    assert env["CARGO_BUILD_BUILD_DIR"] == str(explicit_cargo / "build")


@patch("sase.running_field.claim_workspace", return_value=ClaimResult(success=True))
@patch("sase.core.agent_launch_facade.spawn_prepared_agent_process")
def test_spawn_agent_subprocess_preserves_explicit_cargo_build_dir(
    mock_spawn: MagicMock,
    mock_claim: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    explicit_cargo = tmp_path / "explicit-cargo"
    explicit_build = tmp_path / "explicit-build"

    _spawn_agent_for_env_test(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        mock_spawn=mock_spawn,
        extra_env={
            "CARGO_TARGET_DIR": str(explicit_cargo),
            "CARGO_BUILD_BUILD_DIR": str(explicit_build),
        },
    )

    env = mock_spawn.call_args.kwargs["env"]
    assert env["CARGO_TARGET_DIR"] == str(explicit_cargo)
    assert env["CARGO_BUILD_BUILD_DIR"] == str(explicit_build)


@patch("sase.running_field.claim_workspace", return_value=ClaimResult(success=True))
@patch("sase.core.agent_launch_facade.spawn_prepared_agent_process")
def test_spawn_agent_subprocess_preserves_empty_cargo_build_dir_override(
    mock_spawn: MagicMock,
    mock_claim: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    explicit_cargo = tmp_path / "explicit-cargo"

    _spawn_agent_for_env_test(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        mock_spawn=mock_spawn,
        extra_env={
            "CARGO_TARGET_DIR": str(explicit_cargo),
            "CARGO_BUILD_BUILD_DIR": "",
        },
    )

    env = mock_spawn.call_args.kwargs["env"]
    assert env["CARGO_TARGET_DIR"] == str(explicit_cargo)
    assert env["CARGO_BUILD_BUILD_DIR"] == ""


@patch("sase.running_field.claim_workspace", return_value=ClaimResult(success=True))
@patch("sase.core.agent_launch_facade.spawn_prepared_agent_process")
def test_spawn_agent_subprocess_preserves_explicit_cargo_profile_overrides(
    mock_spawn: MagicMock,
    mock_claim: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _spawn_agent_for_env_test(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        mock_spawn=mock_spawn,
        extra_env={
            "CARGO_INCREMENTAL": "1",
            "CARGO_PROFILE_DEV_DEBUG": "2",
            "CARGO_PROFILE_TEST_DEBUG": "2",
        },
    )

    env = mock_spawn.call_args.kwargs["env"]
    assert env["CARGO_INCREMENTAL"] == "1"
    assert env["CARGO_PROFILE_DEV_DEBUG"] == "2"
    assert env["CARGO_PROFILE_TEST_DEBUG"] == "2"


def test_managed_agent_scratch_env_incremental_opt_in(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Opted-in hosts export CARGO_INCREMENTAL=1 for launched agents."""
    _redirect_managed_tmpdir(monkeypatch, tmp_path / "tmp")

    with patch(
        "sase.config.core.load_merged_config",
        return_value={"managed_tmp": {"agent_cargo_incremental": True}},
    ):
        env = _managed_agent_scratch_env(
            safe_name="proj",
            workspace_num=3,
            timestamp="260101_120000",
        )

    assert env["CARGO_INCREMENTAL"] == "1"


def test_managed_agent_scratch_env_incremental_opt_out_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unset and malformed opt-ins keep today's CARGO_INCREMENTAL=0."""
    _redirect_managed_tmpdir(monkeypatch, tmp_path / "tmp")

    with patch("sase.config.core.load_merged_config", return_value={}):
        env = _managed_agent_scratch_env(
            safe_name="proj",
            workspace_num=3,
            timestamp="260101_120000",
        )
    assert env["CARGO_INCREMENTAL"] == "0"

    with patch(
        "sase.config.core.load_merged_config",
        return_value={"managed_tmp": {"agent_cargo_incremental": "yes"}},
    ):
        env = _managed_agent_scratch_env(
            safe_name="proj",
            workspace_num=3,
            timestamp="260101_120000",
        )
    assert env["CARGO_INCREMENTAL"] == "0"


def test_managed_tmp_agent_cargo_incremental_accessor_defaults() -> None:
    assert DEFAULT_MANAGED_TMP_AGENT_CARGO_INCREMENTAL is False
    with patch("sase.config.core.load_merged_config", return_value={}):
        assert get_managed_tmp_agent_cargo_incremental() is False
    with patch(
        "sase.config.core.load_merged_config",
        return_value={"managed_tmp": {"agent_cargo_incremental": True}},
    ):
        assert get_managed_tmp_agent_cargo_incremental() is True
    with patch(
        "sase.config.core.load_merged_config",
        return_value={"managed_tmp": {"agent_cargo_incremental": 1}},
    ):
        assert get_managed_tmp_agent_cargo_incremental() is False


@patch("sase.running_field.claim_workspace", return_value=ClaimResult(success=True))
@patch("sase.core.agent_launch_facade.spawn_prepared_agent_process")
def test_spawn_agent_subprocess_explicit_incremental_wins_over_opt_in(
    mock_spawn: MagicMock,
    mock_claim: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit extra_env CARGO_INCREMENTAL still wins when opted in."""
    with patch(
        "sase.config.core.load_merged_config",
        return_value={"managed_tmp": {"agent_cargo_incremental": True}},
    ):
        _spawn_agent_for_env_test(
            tmp_path=tmp_path,
            monkeypatch=monkeypatch,
            mock_spawn=mock_spawn,
            extra_env={"CARGO_INCREMENTAL": "0"},
        )

    env = mock_spawn.call_args.kwargs["env"]
    assert env["CARGO_INCREMENTAL"] == "0"
