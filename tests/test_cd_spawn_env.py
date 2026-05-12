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
            project_file=str(tmp_path / "home.sase"),
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
            project_file=str(tmp_path / "home.sase"),
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


def _spawn_with_captured_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    workspace: Path,
) -> dict[str, str]:
    """Drive ``spawn_agent_subprocess`` and return the env passed to the child."""
    patch_cd_git_metadata(monkeypatch)
    from sase.agent.launcher import spawn_agent_subprocess

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
        ),
        patch(
            "sase.running_field.transfer_workspace_claim",
            return_value=ClaimResult(success=True),
        ),
        patch("sase.axe.chop_agents.record_chop_agent_launch_from_env"),
    ):
        spawn_agent_subprocess(
            cl_name="home",
            project_file=str(tmp_path / "home.sase"),
            workspace_dir=str(workspace),
            workspace_num=101,
            workflow_name="ace(run)-ts",
            prompt="#git:home do work",
            timestamp="20260512190000",
            project_name="home",
            is_home_mode=False,
            vcs_ref=("git", "home"),
        )
    return captured_env


def test_spawn_agent_subprocess_overwrites_stale_active_project_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Parent's stale SASE_ACTIVE_PROJECT_DIR must not leak into the child."""
    stale_dir = tmp_path / "stale-parent-workspace"
    stale_dir.mkdir()
    workspace = tmp_path / "child-workspace"
    workspace.mkdir()
    monkeypatch.setenv("SASE_ACTIVE_PROJECT_DIR", str(stale_dir))

    captured_env = _spawn_with_captured_env(monkeypatch, tmp_path, workspace)

    assert captured_env["SASE_ACTIVE_PROJECT_DIR"] == str(workspace)


def test_spawn_agent_subprocess_strips_stale_codex_project_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Inherited CODEX_PROJECT_DIR must be stripped at the spawn boundary."""
    stale_dir = tmp_path / "stale-parent-workspace"
    stale_dir.mkdir()
    workspace = tmp_path / "child-workspace"
    workspace.mkdir()
    monkeypatch.setenv("CODEX_PROJECT_DIR", str(stale_dir))

    captured_env = _spawn_with_captured_env(monkeypatch, tmp_path, workspace)

    assert "CODEX_PROJECT_DIR" not in captured_env


def test_default_git_home_auto_initializes_incomplete_home_project(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    project_dir = tmp_path / ".sase" / "projects" / "home"
    project_file = project_dir / "home.sase"
    bare_dir = tmp_path / ".sase" / "repos" / "home.git"
    workspace_dir = str(tmp_path / "projects" / "git" / "home") + "/"
    project_dir.mkdir(parents=True)
    project_file.write_text("NAME: home\n")

    from sase.workspace_provider.plugins.bare_git_ref import resolve_git_ref

    def init_project(project_name: str) -> str:
        assert project_name == "home"
        project_file.write_text(
            f"BARE_REPO_DIR: {bare_dir}\nWORKSPACE_DIR: {workspace_dir}\n",
            encoding="utf-8",
        )
        return str(project_file)

    with (
        patch(
            "sase.workspace_provider.plugins.bare_git_ref.find_all_changespecs",
            return_value=[],
        ) as find_all,
        patch(
            "sase.workspace_provider.plugins.bare_git_init.init_bare_git_project",
            side_effect=init_project,
        ) as init,
        patch(
            "sase.workspace_provider.plugins.bare_git_ref.get_default_branch",
            return_value="origin/main",
        ),
    ):
        result = resolve_git_ref("home")

    assert result.project_name == "home"
    assert result.primary_workspace_dir == workspace_dir
    assert result.bare_repo_dir == str(bare_dir)
    assert result.checkout_target == "origin/main"
    find_all.assert_called_once()
    init.assert_called_once_with("home")
