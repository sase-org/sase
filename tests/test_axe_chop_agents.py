"""Tests for durable chop-launched agent tracking."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.agent.launcher import spawn_agent_subprocess
from sase.axe.chop_agents import (
    ENV_CHOP_LUMBERJACK,
    ENV_CHOP_NAME,
    ENV_CHOP_PROMPT_HASH,
    ENV_CHOP_RUN_ID,
    build_chop_launch_env,
    get_chop_agent_records,
)
from sase.linked_repos import LinkedRepoResolution
from sase.running_field import ClaimResult

from tests._axe_chop_agents_helpers import (
    _fake_spawn_success,
    _redirect_managed_tmpdir,
    _spawn_agent_for_env_test,
)

pytest_plugins = ["tests.axe_chop_agents_fixtures"]


@patch(
    "sase.running_field.transfer_workspace_claim",
    return_value=ClaimResult(success=True),
)
@patch("sase.core.agent_launch_facade.spawn_prepared_agent_process")
def test_spawn_agent_subprocess_preserves_chop_linkage_for_retry_continuation(
    mock_spawn: MagicMock,
    mock_transfer: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A retry handoff re-links its child without forwarding other chop state."""
    monkeypatch.setenv(ENV_CHOP_LUMBERJACK, "hooks")
    monkeypatch.setenv(ENV_CHOP_NAME, "split")
    monkeypatch.setenv(ENV_CHOP_RUN_ID, "run-1")
    monkeypatch.setenv(ENV_CHOP_PROMPT_HASH, "prompt-hash")
    monkeypatch.setenv("SASE_CHOP_RESULT_FILE", "/tmp/ambient-result.json")

    _spawn_agent_for_env_test(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        mock_spawn=mock_spawn,
        retry_transfer_from_pid=1234,
    )

    env = mock_spawn.call_args.kwargs["env"]
    assert env[ENV_CHOP_LUMBERJACK] == "hooks"
    assert env[ENV_CHOP_NAME] == "split"
    assert env[ENV_CHOP_RUN_ID] == "run-1"
    assert env[ENV_CHOP_PROMPT_HASH] == "prompt-hash"
    assert "SASE_CHOP_RESULT_FILE" not in env
    assert env["SASE_JOB_ROUTINE"] == "hooks"
    assert env["SASE_JOB_NAME"] == "split"
    assert env["SASE_JOB_RUN_ID"] == "run-1"
    assert "SASE_JOB_RESULT_FILE" not in env
    records = get_chop_agent_records("hooks", chop_name="split", run_id="run-1")
    assert [record.pid for record in records] == [4321]
    mock_transfer.assert_called_once()


@patch("sase.running_field.claim_workspace", return_value=ClaimResult(success=True))
@patch("sase.core.agent_launch_facade.spawn_prepared_agent_process")
def test_spawn_agent_subprocess_records_chop_launch_and_detaches(
    mock_spawn: MagicMock,
    mock_claim: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Launcher records every agent spawned under SASE_CHOP_* env vars."""
    output_path = tmp_path / "proj_ace-run-260101_120000.txt"
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    tmp_dir = tmp_path / "tmp"
    tmp_dir.mkdir()
    sase_home = tmp_path / ".sase"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    mock_spawn.side_effect = _fake_spawn_success
    _redirect_managed_tmpdir(monkeypatch, tmp_dir)
    monkeypatch.setattr("sase.core.paths.sharded_path", lambda *_args: str(output_path))
    monkeypatch.setattr(
        "sase.linked_repos.resolve_linked_repos_for_project",
        lambda **_: LinkedRepoResolution(()),
    )

    result = spawn_agent_subprocess(
        cl_name="proj",
        project_file="/tmp/projects/proj/proj.sase",
        workspace_dir=str(workspace_dir),
        workspace_num=3,
        workflow_name="ace(run)-260101_120000",
        prompt="do work",
        timestamp="260101_120000",
        project_name="proj",
        extra_env=build_chop_launch_env(
            lumberjack_name="hooks",
            chop_name="split",
            prompt="do work",
            run_id="run-1",
        ),
    )

    assert result.pid == 4321
    assert result.artifacts_dir == str(
        sase_home
        / "projects"
        / "proj"
        / "artifacts"
        / "ace-run"
        / "202601"
        / "01"
        / "20260101120000"
    )
    prepared = mock_spawn.call_args.args[0]
    assert prepared.argv[2:9] == [
        "proj",
        "/tmp/projects/proj/proj.sase",
        str(workspace_dir),
        str(output_path),
        "3",
        "ace(run)-260101_120000",
        prepared.argv[8],
    ]
    assert Path(prepared.argv[8]).read_text() == "do work"
    # The prompt file lands in a managed subdirectory a reaper can own, never
    # directly in the managed temp root.
    assert Path(prepared.argv[8]).parent == tmp_dir / "launch-prompts"
    assert Path(prepared.argv[8]).name.startswith("sase_ace_prompt_")
    assert mock_spawn.call_args.kwargs["claim_callback"] is not None
    child_env = mock_spawn.call_args.kwargs["env"]
    assert child_env[ENV_CHOP_LUMBERJACK] == "hooks"
    assert child_env[ENV_CHOP_NAME] == "split"
    assert child_env[ENV_CHOP_RUN_ID] == "run-1"
    assert child_env["SASE_JOB_ROUTINE"] == "hooks"
    assert child_env["SASE_JOB_NAME"] == "split"
    assert child_env["SASE_JOB_RUN_ID"] == "run-1"
    records = get_chop_agent_records("hooks", chop_name="split")
    assert len(records) == 1
    assert records[0].pid == 4321
    assert records[0].project_name == "proj"
    assert records[0].workflow_name == "ace(run)-260101_120000"


@patch("sase.running_field.claim_workspace", return_value=ClaimResult(success=True))
@patch("sase.core.agent_launch_facade.spawn_prepared_agent_process")
def test_spawn_agent_subprocess_ignores_post_spawn_chop_record_failure(
    mock_spawn: MagicMock,
    mock_claim: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A chop-registry write failure after spawn does not fail the launch."""
    output_path = tmp_path / "proj_ace-run-260101_120000.txt"
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    tmp_dir = tmp_path / "tmp"
    tmp_dir.mkdir()
    sase_home = tmp_path / ".sase"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    mock_spawn.side_effect = _fake_spawn_success
    _redirect_managed_tmpdir(monkeypatch, tmp_dir)
    monkeypatch.setattr("sase.core.paths.sharded_path", lambda *_args: str(output_path))
    monkeypatch.setattr(
        "sase.linked_repos.resolve_linked_repos_for_project",
        lambda **_: LinkedRepoResolution(()),
    )

    with patch(
        "sase.axe.chop_agents.record_chop_agent_launch_from_env",
        side_effect=OSError("registry busy"),
    ) as record:
        result = spawn_agent_subprocess(
            cl_name="proj",
            project_file="/tmp/projects/proj/proj.sase",
            workspace_dir=str(workspace_dir),
            workspace_num=3,
            workflow_name="ace(run)-260101_120000",
            prompt="do work",
            timestamp="260101_120000",
            project_name="proj",
            extra_env=build_chop_launch_env(
                lumberjack_name="hooks",
                chop_name="split",
                prompt="do work",
                run_id="run-1",
            ),
        )

    assert result.pid == 4321
    record.assert_called_once()


@patch("sase.running_field.claim_workspace", return_value=ClaimResult(success=True))
@patch("sase.core.agent_launch_facade.spawn_prepared_agent_process")
def test_spawn_agent_subprocess_prepares_vcs_and_local_xprompt_env(
    mock_spawn: MagicMock,
    mock_claim: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rust preparation preserves launch env for VCS and local xprompts."""
    output_path = tmp_path / "out.txt"
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    tmp_dir = tmp_path / "tmp"
    tmp_dir.mkdir()
    xprompts_file = tmp_path / "xprompts.json"
    xprompts_file.write_text("{}")
    sase_home = tmp_path / ".sase"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    mock_spawn.side_effect = _fake_spawn_success
    _redirect_managed_tmpdir(monkeypatch, tmp_dir)
    monkeypatch.setattr("sase.core.paths.sharded_path", lambda *_args: str(output_path))
    monkeypatch.setattr(
        "sase.workspace_provider.get_pre_allocated_env_prefix",
        lambda _workflow_type: "GH",
    )

    spawn_agent_subprocess(
        cl_name="feature/test",
        project_file="/tmp/projects/proj/proj.sase",
        workspace_dir=str(workspace_dir),
        workspace_num=8,
        workflow_name="ace(run)-260101_120000",
        prompt="do work",
        timestamp="260101_120000",
        project_name="proj",
        vcs_ref=("gh", "feature/test"),
        deferred_workspace=True,
        local_xprompts_file=str(xprompts_file),
        extra_env={"SASE_REPEAT_NAME": "task.1"},
    )

    env = mock_spawn.call_args.kwargs["env"]
    assert env["SASE_AGENT"] == "1"
    assert env["SASE_AGENT_VCS_WORKFLOW_TYPE"] == "gh"
    assert env["SASE_AGENT_DEFERRED_WORKSPACE"] == "1"
    assert env["GH_PRE_ALLOCATED"] == "1"
    assert env["GH_WORKSPACE_NUM"] == "8"
    assert env["GH_WORKSPACE_DIR"] == str(workspace_dir)
    assert env["SASE_AGENT_LOCAL_XPROMPTS"] == str(xprompts_file)
    assert env["SASE_REPEAT_NAME"] == "task.1"
    mock_claim.assert_called_once()
    assert mock_claim.call_args.args[1] == 0


@patch("sase.running_field.claim_workspace", return_value=ClaimResult(success=True))
@patch("sase.core.agent_launch_facade.spawn_prepared_agent_process")
def test_spawn_agent_subprocess_does_not_record_without_chop_env(
    mock_spawn: MagicMock,
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
    sase_home = tmp_path / ".sase"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    mock_spawn.side_effect = _fake_spawn_success
    _redirect_managed_tmpdir(monkeypatch, tmp_dir)
    monkeypatch.setattr("sase.core.paths.sharded_path", lambda *_args: str(output_path))

    spawn_agent_subprocess(
        cl_name="proj",
        project_file="/tmp/projects/proj/proj.sase",
        workspace_dir=str(workspace_dir),
        workspace_num=3,
        workflow_name="ace(run)-260101_120000",
        prompt="do work",
        timestamp="260101_120000",
        project_name="proj",
    )

    assert get_chop_agent_records("hooks", chop_name="split") == []
