"""Spawn environment tests for built-in ``#cd`` launch resolution."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.running_field import ClaimResult
from tests._cd_launch_resolution_helpers import patch_cd_git_metadata


def test_spawn_cd_sets_resolved_directory_env_without_claim(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from sase.agent.launcher import spawn_agent_subprocess

    target = tmp_path / "target"
    target.mkdir()
    output = tmp_path / "agent.log"
    captured_env: dict[str, str] = {}
    monkeypatch.setenv("SASE_CD_PRE_ALLOCATED", "1")
    monkeypatch.setenv("SASE_CD_WORKSPACE_NUM", "999")
    monkeypatch.setenv("SASE_CD_WORKSPACE_DIR", "/stale/cd")
    monkeypatch.setenv("SASE_GIT_PRE_ALLOCATED", "1")
    monkeypatch.setenv("SASE_GIT_WORKSPACE_NUM", "998")
    monkeypatch.setenv("SASE_GIT_WORKSPACE_DIR", "/stale/git")

    def fake_spawn(
        _prepared: object,
        *,
        env: dict[str, str],
        claim_callback: Callable[[int], bool] | None = None,
    ) -> int:
        captured_env.update(env)
        if claim_callback is not None:
            assert callable(claim_callback)
            assert claim_callback(12345) is True
        return 12345

    with (
        patch("sase.core.paths.sharded_path", return_value=str(output)),
        patch(
            "sase.core.agent_launch_facade.spawn_prepared_agent_process",
            side_effect=fake_spawn,
        ),
        patch("sase.running_field.claim_workspace") as claim,
        patch("sase.running_field.transfer_workspace_claim") as transfer,
        patch("sase.axe.chop_agents.record_chop_agent_launch_from_env"),
    ):
        spawn_agent_subprocess(
            cl_name=str(target),
            project_file=str(tmp_path / "home.gp"),
            workspace_dir=str(target),
            workspace_num=0,
            workflow_name="ace(run)-ts",
            prompt=f"#cd:{target} do work",
            timestamp="20260430120000",
            project_name="home",
            is_home_mode=True,
            vcs_ref=("cd", str(target)),
        )

    assert captured_env["SASE_CD_PRE_ALLOCATED"] == "1"
    assert captured_env["SASE_CD_WORKSPACE_NUM"] == "0"
    assert captured_env["SASE_CD_WORKSPACE_DIR"] == str(target)
    assert "SASE_GIT_PRE_ALLOCATED" not in captured_env
    assert "SASE_GIT_WORKSPACE_NUM" not in captured_env
    assert "SASE_GIT_WORKSPACE_DIR" not in captured_env
    claim.assert_not_called()
    transfer.assert_not_called()


def test_spawn_git_home_sets_preallocated_workspace_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_cd_git_metadata(monkeypatch)
    from sase.agent.launcher import spawn_agent_subprocess

    workspace = tmp_path / "home_101"
    workspace.mkdir()
    output = tmp_path / "agent.log"
    captured_env: dict[str, str] = {}

    def fake_spawn(
        _prepared: object,
        *,
        env: dict[str, str],
        claim_callback: Callable[[int], bool] | None = None,
    ) -> int:
        captured_env.update(env)
        if claim_callback is not None:
            assert claim_callback(12345) is True
        return 12345

    with (
        patch("sase.core.paths.sharded_path", return_value=str(output)),
        patch(
            "sase.core.agent_launch_facade.spawn_prepared_agent_process",
            side_effect=fake_spawn,
        ),
        patch(
            "sase.running_field.claim_workspace",
            return_value=ClaimResult(success=True),
        ) as claim,
        patch(
            "sase.running_field.transfer_workspace_claim",
            return_value=ClaimResult(success=True),
        ) as transfer,
        patch("sase.axe.chop_agents.record_chop_agent_launch_from_env"),
    ):
        spawn_agent_subprocess(
            cl_name="home",
            project_file=str(tmp_path / "home.gp"),
            workspace_dir=str(workspace),
            workspace_num=101,
            workflow_name="ace(run)-ts",
            prompt="#git:home do work",
            timestamp="20260430120000",
            project_name="home",
            is_home_mode=False,
            vcs_ref=("git", "home"),
        )

    assert captured_env["SASE_GIT_PRE_ALLOCATED"] == "1"
    assert captured_env["SASE_GIT_WORKSPACE_NUM"] == "101"
    assert captured_env["SASE_GIT_WORKSPACE_DIR"] == str(workspace)
    claim.assert_called_once()
    transfer.assert_not_called()


def test_default_git_home_reports_incomplete_home_project(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    project_dir = tmp_path / ".sase" / "projects" / "home"
    project_dir.mkdir(parents=True)
    (project_dir / "home.gp").write_text("NAME: home\n")

    from sase.workspace_provider.plugins.bare_git_ref import resolve_git_ref

    with pytest.raises(ValueError, match="Default bare-git project 'home'"):
        resolve_git_ref("home")
