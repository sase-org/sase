"""Multi-prompt launch tests for built-in ``#cd`` launch resolution."""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.workspace_provider._hookspec import ResolvedRef
from tests._cd_launch_resolution_helpers import (
    patch_cd_git_metadata,
    patch_cd_metadata,
)


def test_launch_multi_prompt_agents_resolves_cd_per_segment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_cd_metadata(monkeypatch)
    from sase.agent.multi_prompt_launcher import launch_multi_prompt_agents

    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()

    with (
        patch("sase.agent.launcher.spawn_agent_subprocess") as spawn,
        patch("sase.agent.multi_prompt_launcher._wait_for_agent_naming"),
        patch("sase.core.time.generate_timestamp", return_value="260501_120000"),
        patch(
            "sase.artifacts.create_artifacts_directory",
            return_value="/artifacts",
        ) as create_artifacts,
        patch("sase.running_field.get_first_available_axe_workspace") as first_ws,
    ):
        spawn.return_value = MagicMock(pid=1)
        launch_multi_prompt_agents(
            segments=[f"#cd:{dir_a} first", f"#cd:{dir_b} second"],
            local_xprompts={},
            cl_name="base",
            project_file="/projects/base/base.sase",
            project_name="base",
            is_home_mode=False,
            vcs_ref=None,
            default_bare_segments_to_home=True,
        )

    calls = spawn.call_args_list
    assert [c.kwargs["workspace_dir"] for c in calls] == [
        str(dir_a.resolve()),
        str(dir_b.resolve()),
    ]
    assert [c.kwargs["workspace_num"] for c in calls] == [0, 0]
    assert [c.kwargs["is_home_mode"] for c in calls] == [True, True]
    assert [c.kwargs["update_target"] for c in calls] == ["", ""]
    assert [c.kwargs["vcs_ref"] for c in calls] == [
        ("cd", str(dir_a)),
        ("cd", str(dir_b)),
    ]
    create_artifacts.assert_not_called()
    first_ws.assert_not_called()


def test_launch_multi_prompt_agents_activates_inactive_known_project_later_segment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_cd_metadata(monkeypatch)
    from sase.agent.multi_prompt_launcher import launch_multi_prompt_agents

    dir_a = tmp_path / "a"
    dir_a.mkdir()
    workspace = tmp_path / "sase"
    workspace.mkdir()
    allocated_workspace = tmp_path / "sase_101"
    allocated_workspace.mkdir()
    projects_dir = tmp_path / ".sase" / "projects" / "sase"
    projects_dir.mkdir(parents=True)
    project_file = projects_dir / "sase.sase"
    project_file.write_text(
        f"PROJECT_STATE: inactive\nWORKSPACE_DIR: {workspace}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    from sase.core.project_lifecycle_wire import ProjectRecordWire

    known_record = ProjectRecordWire(
        schema_version=1,
        project_name="sase",
        project_dir=str(projects_dir),
        project_file=str(project_file),
        archive_file=None,
        workspace_dir=str(workspace),
        state="inactive",
        state_explicit=True,
        system_managed=False,
        active_claim_count=0,
        launchable=True,
    )

    def activate_known_project(ref: str) -> ProjectRecordWire:
        assert ref == "sase-org/sase"
        project_file.write_text(
            f"PROJECT_STATE: active\nWORKSPACE_DIR: {workspace}\n",
            encoding="utf-8",
        )
        return replace(known_record, state="active")

    with (
        patch("sase.agent.launcher.spawn_agent_subprocess") as spawn,
        patch(
            "sase.agent.launch_projects.extract_known_project_vcs_launch_ref",
            side_effect=lambda prompt: (
                ("gh", "sase-org/sase") if "#gh:" in prompt else None
            ),
        ),
        patch(
            "sase.agent.launch_projects.activate_known_project_for_launch_ref",
            side_effect=activate_known_project,
        ),
        patch(
            "sase.xprompt.loader.get_known_project_workspaces",
            return_value={"sase": str(workspace)},
        ),
        patch("sase.agent.multi_prompt_launcher._wait_for_agent_naming"),
        patch("sase.core.time.generate_timestamp", return_value="260501_120000"),
        patch(
            "sase.artifacts.create_artifacts_directory",
            return_value="/artifacts",
        ),
        patch(
            "sase.running_field.claim_next_axe_workspace",
            return_value=101,
        ) as claim_ws,
        patch(
            "sase.running_field.get_workspace_directory_for_num",
            return_value=(str(allocated_workspace), None),
        ) as ws_dir,
    ):
        spawn.return_value = MagicMock(pid=1)
        launch_multi_prompt_agents(
            segments=[f"#cd:{dir_a} first", "#gh:sase-org/sase second"],
            local_xprompts={},
            cl_name="base",
            project_file="/projects/base/base.sase",
            project_name="base",
            is_home_mode=False,
            vcs_ref=None,
            default_bare_segments_to_home=True,
        )

    calls = spawn.call_args_list
    assert [c.kwargs["project_name"] for c in calls] == [dir_a.name, "sase"]
    assert [c.kwargs["workspace_dir"] for c in calls] == [
        str(dir_a.resolve()),
        str(allocated_workspace),
    ]
    assert [c.kwargs["vcs_ref"] for c in calls] == [
        ("cd", str(dir_a)),
        ("gh", "sase"),
    ]
    claim_ws.assert_called_once()
    assert claim_ws.call_args.args[0] == str(project_file)
    ws_dir.assert_called_once_with(101, "sase")
    assert "PROJECT_STATE: active" in project_file.read_text(encoding="utf-8")


def test_launch_multi_prompt_agents_owner_repo_ref_uses_duplicate_workspace_match(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_cd_metadata(monkeypatch)
    from sase.agent.multi_prompt_launcher import launch_multi_prompt_agents

    monkeypatch.setenv("HOME", str(tmp_path))
    dir_a = tmp_path / "a"
    dir_a.mkdir()
    foo_workspace = tmp_path / "projects" / "github" / "foo-org" / "foo"
    bar_workspace = tmp_path / "projects" / "github" / "bar-org" / "foo"
    foo_workspace.mkdir(parents=True)
    bar_workspace.mkdir(parents=True)
    allocated_workspace = tmp_path / "gh_bar_org__foo_101"
    allocated_workspace.mkdir()
    project_file = str(
        tmp_path / ".sase" / "projects" / "gh_bar_org__foo" / "gh_bar_org__foo.sase"
    )
    monkeypatch.setattr(
        "sase.xprompt.loader.get_known_project_workspaces",
        lambda *_args, **_kwargs: {
            "gh_foo_org__foo": foo_workspace,
            "gh_bar_org__foo": bar_workspace,
        },
    )

    with (
        patch("sase.agent.launcher.spawn_agent_subprocess") as spawn,
        patch("sase.agent.multi_prompt_launcher._wait_for_agent_naming"),
        patch("sase.core.time.generate_timestamp", return_value="260501_120000"),
        patch(
            "sase.artifacts.create_artifacts_directory",
            return_value="/artifacts",
        ),
        patch(
            "sase.running_field.claim_next_axe_workspace",
            return_value=101,
        ) as claim_ws,
        patch(
            "sase.running_field.get_workspace_directory_for_num",
            return_value=(str(allocated_workspace), None),
        ) as ws_dir,
    ):
        spawn.return_value = MagicMock(pid=1)
        launch_multi_prompt_agents(
            segments=[f"#cd:{dir_a} first", "#gh:bar-org/foo second"],
            local_xprompts={},
            cl_name="base",
            project_file="/projects/base/base.sase",
            project_name="base",
            is_home_mode=False,
            vcs_ref=None,
            default_bare_segments_to_home=True,
        )

    calls = spawn.call_args_list
    assert [c.kwargs["project_name"] for c in calls] == [
        dir_a.name,
        "gh_bar_org__foo",
    ]
    assert [c.kwargs["workspace_dir"] for c in calls] == [
        str(dir_a.resolve()),
        str(allocated_workspace),
    ]
    assert [c.kwargs["vcs_ref"] for c in calls] == [
        ("cd", str(dir_a)),
        ("gh", "gh_bar_org__foo"),
    ]
    claim_ws.assert_called_once()
    assert claim_ws.call_args.args[0] == project_file
    ws_dir.assert_called_once_with(101, "gh_bar_org__foo")


def test_launch_multi_prompt_agents_defaults_bare_segment_to_git_home(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_cd_git_metadata(monkeypatch)
    from sase.agent.multi_prompt_launcher import launch_multi_prompt_agents

    dir_a = tmp_path / "a"
    dir_a.mkdir()
    primary_workspace = tmp_path / "home"
    allocated_workspace = tmp_path / "home_101"
    project_file = str(tmp_path / "home.sase")

    def resolve_ref(ref: str, workflow_type: str) -> ResolvedRef:
        if workflow_type == "cd":
            return ResolvedRef(
                project_file=str(
                    Path.home() / ".sase" / "projects" / "home" / "home.sase"
                ),
                project_name=Path(ref).name,
                primary_workspace_dir=str(Path(ref).expanduser().resolve()),
                checkout_target="",
            )
        return ResolvedRef(
            project_file=project_file,
            project_name="home",
            primary_workspace_dir=str(primary_workspace),
            checkout_target="main",
        )

    with (
        patch("sase.agent.launcher.spawn_agent_subprocess") as spawn,
        patch("sase.agent.multi_prompt_launcher._wait_for_agent_naming"),
        patch("sase.core.time.generate_timestamp", return_value="260501_120000"),
        patch(
            "sase.artifacts.create_artifacts_directory",
            return_value="/artifacts",
        ) as create_artifacts,
        patch(
            "sase.workspace_provider.resolve_ref",
            side_effect=resolve_ref,
        ) as resolve_ref_mock,
        patch("sase.running_field.get_first_available_axe_workspace") as first_ws,
        patch("sase.workspace_provider.get_workspace_directory") as provider_ws_dir,
        patch(
            "sase.running_field.claim_next_axe_workspace",
            return_value=101,
        ) as claim_ws,
        patch(
            "sase.running_field.get_workspace_directory_for_num",
            return_value=(str(allocated_workspace), None),
        ) as ws_dir,
    ):
        spawn.return_value = MagicMock(pid=1)
        launch_multi_prompt_agents(
            segments=[f"#cd:{dir_a} first", "second"],
            local_xprompts={},
            cl_name="base",
            project_file="/projects/base/base.sase",
            project_name="base",
            is_home_mode=False,
            vcs_ref=None,
            default_bare_segments_to_home=True,
        )

    calls = spawn.call_args_list
    assert [c.kwargs["prompt"] for c in calls] == [
        f"#cd:{dir_a} first",
        "#git:home second",
    ]
    assert [c.kwargs["workspace_dir"] for c in calls] == [
        str(dir_a.resolve()),
        str(allocated_workspace),
    ]
    assert [c.kwargs["workspace_num"] for c in calls] == [0, 101]
    assert [c.kwargs["is_home_mode"] for c in calls] == [True, False]
    assert [c.kwargs["vcs_ref"] for c in calls] == [
        ("cd", str(dir_a)),
        ("git", "home"),
    ]
    assert [c.kwargs["retry_transfer_from_pid"] for c in calls] == [
        None,
        os.getpid(),
    ]
    resolve_ref_mock.assert_any_call(str(dir_a), "cd")
    resolve_ref_mock.assert_any_call("home", "git")
    first_ws.assert_not_called()
    provider_ws_dir.assert_not_called()
    claim_ws.assert_called_once()
    assert claim_ws.call_args.args[0] == project_file
    ws_dir.assert_called_once_with(101, "home")
    create_artifacts.assert_not_called()


def test_launch_multi_prompt_bare_git_home_wait_uses_home_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_cd_git_metadata(monkeypatch)
    from sase.agent.multi_prompt_launcher import launch_multi_prompt_agents

    primary_workspace = tmp_path / "home"
    allocated_workspace = tmp_path / "home_101"
    project_file = str(tmp_path / "home.sase")

    with (
        patch("sase.agent.launcher.spawn_agent_subprocess") as spawn,
        patch("sase.agent.multi_prompt_launcher._wait_for_agent_naming") as wait,
        patch("sase.core.time.generate_timestamp", return_value="260501_120000"),
        patch(
            "sase.artifacts.create_artifacts_directory",
            return_value="/artifacts/home",
        ) as create_artifacts,
        patch(
            "sase.workspace_provider.resolve_ref",
            return_value=ResolvedRef(
                project_file=project_file,
                project_name="home",
                primary_workspace_dir=str(primary_workspace),
                checkout_target="main",
            ),
        ),
        patch("sase.running_field.get_first_available_axe_workspace") as first_ws,
        patch("sase.workspace_provider.get_workspace_directory") as provider_ws_dir,
        patch(
            "sase.running_field.claim_next_axe_workspace",
            return_value=101,
        ) as claim_ws,
        patch(
            "sase.running_field.get_workspace_directory_for_num",
            return_value=(str(allocated_workspace), None),
        ) as ws_dir,
    ):
        spawn.return_value = MagicMock(pid=1)
        wait.return_value = "home-agent"
        launch_multi_prompt_agents(
            segments=["first", "%wait\nsecond"],
            local_xprompts={},
            cl_name="base",
            project_file="/projects/base/base.sase",
            project_name="base",
            is_home_mode=False,
            vcs_ref=None,
            default_bare_segments_to_home=True,
        )

    assert [c.kwargs["prompt"] for c in spawn.call_args_list] == [
        "#git:home first",
        "%wait:home-agent\n#git:home second",
    ]
    assert [c.kwargs["workspace_dir"] for c in spawn.call_args_list] == [
        str(allocated_workspace),
        str(primary_workspace),
    ]
    assert [c.kwargs["workspace_num"] for c in spawn.call_args_list] == [101, 0]
    assert [c.kwargs["is_home_mode"] for c in spawn.call_args_list] == [False, False]
    assert [c.kwargs["retry_transfer_from_pid"] for c in spawn.call_args_list] == [
        os.getpid(),
        None,
    ]
    create_artifacts.assert_called_once_with(
        "ace-run",
        project_name="home",
        timestamp="260501_120000",
    )
    wait.assert_called_once_with("/artifacts/home")
    first_ws.assert_not_called()
    provider_ws_dir.assert_not_called()
    claim_ws.assert_called_once()
    assert claim_ws.call_args.args[0] == project_file
    ws_dir.assert_called_once_with(101, "home")
