"""Tests for durable chop-launched agent tracking."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.agent.launcher import spawn_agent_subprocess
from sase.axe.chop_agents import (
    ENV_CHOP_LUMBERJACK,
    ENV_CHOP_NAME,
    ENV_CHOP_PROMPT_HASH,
    ENV_CHOP_RUN_ID,
    agent_meta_from_chop_env,
    build_chop_launch_env,
    get_live_chop_agent_records,
    prompt_hash,
)


def _spawn_agent_for_env_test(
    *,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mock_popen: MagicMock,
    extra_env: dict[str, str] | None = None,
) -> None:
    output_path = tmp_path / "out.txt"
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    tmp_dir = tmp_path / "tmp"
    tmp_dir.mkdir()
    mock_proc = MagicMock()
    mock_proc.pid = 4321
    mock_popen.return_value = mock_proc
    monkeypatch.setattr("sase.core.paths.get_sase_tmpdir", lambda: str(tmp_dir))
    monkeypatch.setattr("sase.core.paths.sharded_path", lambda *_args: str(output_path))

    spawn_agent_subprocess(
        cl_name="proj",
        project_file="/tmp/projects/proj/proj.gp",
        workspace_dir=str(workspace_dir),
        workspace_num=3,
        workflow_name="ace(run)-260101_120000",
        prompt="do work",
        timestamp="260101_120000",
        project_name="proj",
        extra_env=extra_env,
    )


def test_build_chop_launch_env() -> None:
    """Both scheduled and one-shot paths can build matching chop env vars."""
    env = build_chop_launch_env(
        lumberjack_name="recurring",
        chop_name="my_agent",
        prompt="#!refresh_docs",
    )

    assert env[ENV_CHOP_LUMBERJACK] == "recurring"
    assert env[ENV_CHOP_NAME] == "my_agent"
    assert env[ENV_CHOP_RUN_ID]
    assert env[ENV_CHOP_PROMPT_HASH] == prompt_hash("#!refresh_docs")
    assert "SASE_AGENT_AUTO_DISMISS" not in env


def test_build_chop_launch_env_unique_run_ids() -> None:
    """Each invocation produces a fresh run id."""
    env_a = build_chop_launch_env(lumberjack_name="lj", chop_name="c", prompt="prompt")
    env_b = build_chop_launch_env(lumberjack_name="lj", chop_name="c", prompt="prompt")
    assert env_a[ENV_CHOP_RUN_ID] != env_b[ENV_CHOP_RUN_ID]


def test_agent_meta_from_chop_env() -> None:
    """Chop env vars are represented in agent_meta.json fields."""
    meta = agent_meta_from_chop_env(
        {
            ENV_CHOP_LUMBERJACK: "hooks",
            ENV_CHOP_NAME: "split",
            ENV_CHOP_RUN_ID: "run-1",
        }
    )

    assert meta == {
        "chop_lumberjack": "hooks",
        "chop_name": "split",
        "chop_run_id": "run-1",
    }


@patch("sase.running_field.claim_workspace", return_value=True)
@patch("sase.agent.launcher.subprocess.Popen")
def test_spawn_agent_subprocess_removes_inherited_sase_codex_home(
    mock_popen: MagicMock,
    mock_claim: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Detached agents do not inherit a parent SASE Codex shadow home."""
    inherited_shadow = tmp_path / ".cache" / "sase" / "codex_home" / "123-deadbeef"
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CODEX_HOME", str(inherited_shadow))

    _spawn_agent_for_env_test(
        tmp_path=tmp_path, monkeypatch=monkeypatch, mock_popen=mock_popen
    )

    env = mock_popen.call_args.kwargs["env"]
    assert "CODEX_HOME" not in env


@patch("sase.running_field.claim_workspace", return_value=True)
@patch("sase.agent.launcher.subprocess.Popen")
def test_spawn_agent_subprocess_preserves_custom_codex_home(
    mock_popen: MagicMock,
    mock_claim: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Detached agents keep user-managed custom CODEX_HOME values."""
    custom_home = tmp_path / "custom-codex"
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CODEX_HOME", str(custom_home))

    _spawn_agent_for_env_test(
        tmp_path=tmp_path, monkeypatch=monkeypatch, mock_popen=mock_popen
    )

    env = mock_popen.call_args.kwargs["env"]
    assert env["CODEX_HOME"] == str(custom_home)


@patch("sase.running_field.claim_workspace", return_value=True)
@patch("sase.agent.launcher.subprocess.Popen")
def test_spawn_agent_subprocess_extra_env_codex_home_wins(
    mock_popen: MagicMock,
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
        mock_popen=mock_popen,
        extra_env={"CODEX_HOME": str(explicit_shadow)},
    )

    env = mock_popen.call_args.kwargs["env"]
    assert env["CODEX_HOME"] == str(explicit_shadow)


@patch("sase.running_field.claim_workspace", return_value=True)
@patch("sase.agent.launcher.subprocess.Popen")
def test_spawn_agent_subprocess_records_chop_launch_and_detaches(
    mock_popen: MagicMock,
    mock_claim: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Launcher records every agent spawned under SASE_CHOP_* env vars."""
    output_path = tmp_path / "out.txt"
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    tmp_dir = tmp_path / "tmp"
    tmp_dir.mkdir()
    mock_proc = MagicMock()
    mock_proc.pid = 4321
    mock_popen.return_value = mock_proc
    monkeypatch.setenv(ENV_CHOP_LUMBERJACK, "hooks")
    monkeypatch.setenv(ENV_CHOP_NAME, "split")
    monkeypatch.setenv(ENV_CHOP_RUN_ID, "run-1")
    monkeypatch.setattr("sase.core.paths.get_sase_tmpdir", lambda: str(tmp_dir))
    monkeypatch.setattr("sase.core.paths.sharded_path", lambda *_args: str(output_path))
    monkeypatch.setattr("sase.axe.chop_agents.is_process_running", lambda _pid: True)

    result = spawn_agent_subprocess(
        cl_name="proj",
        project_file="/tmp/projects/proj/proj.gp",
        workspace_dir=str(workspace_dir),
        workspace_num=3,
        workflow_name="ace(run)-260101_120000",
        prompt="do work",
        timestamp="260101_120000",
        project_name="proj",
    )

    assert result.pid == 4321
    popen_kwargs = mock_popen.call_args.kwargs
    assert popen_kwargs["stdin"] == subprocess.DEVNULL
    assert popen_kwargs["stdout"].name == str(output_path)
    assert popen_kwargs["stderr"] == subprocess.STDOUT
    assert popen_kwargs["start_new_session"] is True
    records = get_live_chop_agent_records("hooks", chop_name="split")
    assert len(records) == 1
    assert records[0].pid == 4321
    assert records[0].project_name == "proj"
    assert records[0].workflow_name == "ace(run)-260101_120000"


def test_live_records_prune_when_done_marker_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A done.json marker makes a registry record no longer live."""
    from sase.axe.chop_agents import _record_chop_agent_launch

    monkeypatch.setattr("sase.axe.chop_agents.is_process_running", lambda _pid: True)
    _record_chop_agent_launch(
        lumberjack_name="hooks",
        chop_name="split",
        pid=os.getpid(),
        project_file="/tmp/projects/proj/proj.gp",
        project_name="proj",
        workspace_num=1,
        workflow_name="ace(run)-260101_120000",
        cl_name="proj",
        timestamp="260101_120000",
        prompt="do work",
    )

    done_dir = (
        Path("~/.sase/projects").expanduser()
        / "proj"
        / "artifacts"
        / "ace-run"
        / "20260101120000"
    )
    done_dir.mkdir(parents=True)
    (done_dir / "done.json").write_text(json.dumps({"outcome": "ok"}))

    assert get_live_chop_agent_records("hooks", chop_name="split") == []


@patch("sase.running_field.claim_workspace", return_value=True)
@patch("sase.agent.launcher.subprocess.Popen")
def test_spawn_agent_subprocess_does_not_record_without_chop_env(
    mock_popen: MagicMock,
    mock_claim: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Normal launches are not added to a chop registry."""
    output_path = tmp_path / "out.txt"
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    tmp_dir = tmp_path / "tmp"
    tmp_dir.mkdir()
    mock_proc = MagicMock()
    mock_proc.pid = 4321
    mock_popen.return_value = mock_proc
    monkeypatch.setattr("sase.core.paths.get_sase_tmpdir", lambda: str(tmp_dir))
    monkeypatch.setattr("sase.core.paths.sharded_path", lambda *_args: str(output_path))

    spawn_agent_subprocess(
        cl_name="proj",
        project_file="/tmp/projects/proj/proj.gp",
        workspace_dir=str(workspace_dir),
        workspace_num=3,
        workflow_name="ace(run)-260101_120000",
        prompt="do work",
        timestamp="260101_120000",
        project_name="proj",
    )

    assert get_live_chop_agent_records("hooks", chop_name="split") == []
