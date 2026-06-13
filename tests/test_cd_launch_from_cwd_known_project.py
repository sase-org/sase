"""Known-project launch tests for built-in ``#cd`` launch resolution."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tests._cd_launch_resolution_helpers import patch_cd_metadata


def test_launch_agent_from_cwd_known_project_ref_without_provider_is_not_home_wrapped(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_cd_metadata(monkeypatch)
    from sase.agent.launcher import launch_agent_from_cwd
    from sase.vcs_provider import VCS_DEFAULT_REVISION

    monkeypatch.setenv("HOME", str(tmp_path))
    workspace = tmp_path / "sase"
    workspace.mkdir()
    allocated_workspace = tmp_path / "sase_101"
    allocated_workspace.mkdir()
    project_file = str(tmp_path / ".sase" / "projects" / "sase" / "sase.sase")
    spawn_result = MagicMock(
        pid=123, workspace_dir=str(allocated_workspace), workspace_num=101
    )
    monkeypatch.setattr(
        "sase.xprompt.loader.get_known_project_workspaces",
        lambda: {"sase": workspace},
    )

    with (
        patch(
            "sase.main.utils.ensure_project_file_and_get_workspace_num",
            return_value=(None, None, None),
        ),
        patch("sase.history.prompt.add_or_update_prompt"),
        patch(
            "sase.core.agent_launch_facade.reserve_launch_timestamp_batch",
            return_value=["260501_120000"],
        ),
        patch(
            "sase.agent.launcher.spawn_agent_subprocess",
            return_value=spawn_result,
        ) as spawn,
        patch(
            "sase.running_field.claim_next_axe_workspace",
            return_value=101,
        ) as first_ws,
        patch(
            "sase.running_field.get_workspace_directory_for_num",
            return_value=(str(allocated_workspace), None),
        ) as ws_dir,
    ):
        result = launch_agent_from_cwd("#gh:sase #!sase/fix_just")

    assert result is spawn_result
    kwargs = spawn.call_args.kwargs
    assert kwargs["prompt"] == "#gh:sase #!sase/fix_just"
    assert kwargs["project_name"] == "sase"
    assert kwargs["project_file"] == project_file
    assert kwargs["workspace_dir"] == str(allocated_workspace)
    assert kwargs["workspace_num"] == 101
    assert kwargs["is_home_mode"] is False
    assert kwargs["update_target"] == VCS_DEFAULT_REVISION
    assert kwargs["cl_name"] == "sase"
    assert kwargs["history_sort_key"] == "sase"
    assert kwargs["vcs_ref"] == ("gh", "sase")
    assert kwargs["retry_transfer_from_pid"] == os.getpid()
    # Pre-claim under parent PID: atomic find+claim under the project lock.
    first_ws.assert_called_once()
    assert first_ws.call_args.args[0] == project_file
    ws_dir.assert_called_once_with(101, "sase")


def test_launch_agent_from_cwd_canonicalizes_project_alias_before_spawn(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_cd_metadata(monkeypatch)
    from sase.agent.launcher import launch_agent_from_cwd
    from sase.vcs_provider import VCS_DEFAULT_REVISION

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(
        "sase.project_aliases.load_project_alias_map",
        lambda projects_root=None: {"bob": "bob-cli"},
    )
    workspace = tmp_path / "bob-cli"
    workspace.mkdir()
    allocated_workspace = tmp_path / "bob-cli_101"
    allocated_workspace.mkdir()
    project_file = str(tmp_path / ".sase" / "projects" / "bob-cli" / "bob-cli.sase")
    spawn_result = MagicMock(
        pid=123, workspace_dir=str(allocated_workspace), workspace_num=101
    )
    monkeypatch.setattr(
        "sase.xprompt.loader.get_known_project_workspaces",
        lambda: {"bob-cli": workspace},
    )

    with (
        patch(
            "sase.main.utils.ensure_project_file_and_get_workspace_num",
            return_value=(None, None, None),
        ),
        patch("sase.history.prompt.add_or_update_prompt") as history,
        patch(
            "sase.core.agent_launch_facade.reserve_launch_timestamp_batch",
            return_value=["260501_120000"],
        ),
        patch(
            "sase.agent.launcher.spawn_agent_subprocess",
            return_value=spawn_result,
        ) as spawn,
        patch(
            "sase.running_field.claim_next_axe_workspace",
            return_value=101,
        ),
        patch(
            "sase.running_field.get_workspace_directory_for_num",
            return_value=(str(allocated_workspace), None),
        ),
    ):
        result = launch_agent_from_cwd("#gh:bob #!bob/fix")

    assert result is spawn_result
    kwargs = spawn.call_args.kwargs
    assert kwargs["prompt"] == "#gh:bob-cli #!bob/fix"
    assert kwargs["project_name"] == "bob-cli"
    assert kwargs["project_file"] == project_file
    assert kwargs["workspace_dir"] == str(allocated_workspace)
    assert kwargs["workspace_num"] == 101
    assert kwargs["is_home_mode"] is False
    assert kwargs["update_target"] == VCS_DEFAULT_REVISION
    assert kwargs["cl_name"] == "bob-cli"
    assert kwargs["history_sort_key"] == "bob-cli"
    assert kwargs["vcs_ref"] == ("gh", "bob-cli")
    history.assert_called_once_with("#gh:bob-cli #!bob/fix")


def test_resolve_known_project_vcs_launch_ref_activates_inactive_owner_repo_ref(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_cd_metadata(monkeypatch)
    from sase.agent.launcher import resolve_known_project_vcs_launch_ref

    workspace = tmp_path / "sase"
    workspace.mkdir()
    projects_dir = tmp_path / ".sase" / "projects" / "sase"
    projects_dir.mkdir(parents=True)
    project_file = projects_dir / "sase.sase"
    project_file.write_text(
        f"PROJECT_STATE: inactive\nWORKSPACE_DIR: {workspace}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))

    known_ref = resolve_known_project_vcs_launch_ref("#gh:sase-org/sase do work")

    assert known_ref is not None
    assert known_ref.workflow_type == "gh"
    assert known_ref.ref == "sase"
    assert known_ref.workspace_dir == str(workspace)
    assert known_ref.project_file == str(project_file)
    assert "PROJECT_STATE: active" in project_file.read_text(encoding="utf-8")


def test_launch_agent_from_cwd_inactive_known_project_ref_activates(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_cd_metadata(monkeypatch)
    from sase.agent.launcher import launch_agent_from_cwd
    from sase.vcs_provider import VCS_DEFAULT_REVISION

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
    spawn_result = MagicMock(
        pid=123, workspace_dir=str(allocated_workspace), workspace_num=101
    )

    with (
        patch(
            "sase.main.utils.ensure_project_file_and_get_workspace_num",
            return_value=(None, None, None),
        ),
        patch("sase.history.prompt.add_or_update_prompt"),
        patch(
            "sase.core.agent_launch_facade.reserve_launch_timestamp_batch",
            return_value=["260501_120000"],
        ),
        patch(
            "sase.agent.launcher.spawn_agent_subprocess",
            return_value=spawn_result,
        ) as spawn,
        patch(
            "sase.running_field.claim_next_axe_workspace",
            return_value=101,
        ),
        patch(
            "sase.running_field.get_workspace_directory_for_num",
            return_value=(str(allocated_workspace), None),
        ),
    ):
        result = launch_agent_from_cwd("#gh:sase #!sase/fix_just")

    assert result is spawn_result
    kwargs = spawn.call_args.kwargs
    assert kwargs["project_name"] == "sase"
    assert kwargs["project_file"] == str(project_file)
    assert kwargs["workspace_dir"] == str(allocated_workspace)
    assert kwargs["is_home_mode"] is False
    assert kwargs["update_target"] == VCS_DEFAULT_REVISION
    assert kwargs["vcs_ref"] == ("gh", "sase")
    assert "PROJECT_STATE: active" in project_file.read_text(encoding="utf-8")


def test_launch_agent_from_cwd_explicit_known_ref_ignores_invalid_inferred_project(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_cd_metadata(monkeypatch)
    from sase.agent.launcher import launch_agent_from_cwd
    from sase.vcs_provider import VCS_DEFAULT_REVISION

    monkeypatch.setenv("HOME", str(tmp_path))
    workspace = tmp_path / "sase"
    workspace.mkdir()
    allocated_workspace = tmp_path / "sase_101"
    allocated_workspace.mkdir()
    project_file = str(tmp_path / ".sase" / "projects" / "sase" / "sase.sase")
    spawn_result = MagicMock(
        pid=123, workspace_dir=str(allocated_workspace), workspace_num=101
    )
    monkeypatch.setattr(
        "sase.xprompt.loader.get_known_project_workspaces",
        lambda *_args, **_kwargs: {"sase": workspace},
    )

    with (
        patch("sase.main.utils.get_workspace_name", return_value=".sase"),
        patch("sase.history.prompt.add_or_update_prompt"),
        patch(
            "sase.core.agent_launch_facade.reserve_launch_timestamp_batch",
            return_value=["260501_120000"],
        ),
        patch(
            "sase.agent.launcher.spawn_agent_subprocess",
            return_value=spawn_result,
        ) as spawn,
        patch(
            "sase.running_field.claim_next_axe_workspace",
            return_value=101,
        ),
        patch(
            "sase.running_field.get_workspace_directory_for_num",
            return_value=(str(allocated_workspace), None),
        ),
    ):
        result = launch_agent_from_cwd("#gh:sase #!sase/fix_just")

    assert result is spawn_result
    kwargs = spawn.call_args.kwargs
    assert kwargs["project_name"] == "sase"
    assert kwargs["project_file"] == project_file
    assert kwargs["workspace_dir"] == str(allocated_workspace)
    assert kwargs["is_home_mode"] is False
    assert kwargs["update_target"] == VCS_DEFAULT_REVISION
    assert kwargs["vcs_ref"] == ("gh", "sase")
    assert not (tmp_path / ".sase" / "projects" / ".sase").exists()


def test_launch_agent_from_cwd_owner_repo_ref_resolves_to_known_project(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """``#gh:sase-org/sase`` launches in the known ``sase`` workspace."""
    patch_cd_metadata(monkeypatch)
    from sase.agent.launcher import launch_agent_from_cwd
    from sase.vcs_provider import VCS_DEFAULT_REVISION

    monkeypatch.setenv("HOME", str(tmp_path))
    workspace = tmp_path / "sase"
    workspace.mkdir()
    allocated_workspace = tmp_path / "sase_101"
    allocated_workspace.mkdir()
    project_file = str(tmp_path / ".sase" / "projects" / "sase" / "sase.sase")
    spawn_result = MagicMock(
        pid=123, workspace_dir=str(allocated_workspace), workspace_num=101
    )
    monkeypatch.setattr(
        "sase.xprompt.loader.get_known_project_workspaces",
        lambda: {"sase": workspace},
    )

    with (
        patch(
            "sase.main.utils.ensure_project_file_and_get_workspace_num",
            return_value=(None, None, None),
        ),
        patch("sase.history.prompt.add_or_update_prompt"),
        patch(
            "sase.core.agent_launch_facade.reserve_launch_timestamp_batch",
            return_value=["260501_120000"],
        ),
        patch(
            "sase.agent.launcher.spawn_agent_subprocess",
            return_value=spawn_result,
        ) as spawn,
        patch(
            "sase.running_field.claim_next_axe_workspace",
            return_value=101,
        ),
        patch(
            "sase.running_field.get_workspace_directory_for_num",
            return_value=(str(allocated_workspace), None),
        ),
    ):
        result = launch_agent_from_cwd("#gh:sase-org/sase #!sase/refresh_docs")

    assert result is spawn_result
    kwargs = spawn.call_args.kwargs
    assert kwargs["project_name"] == "sase"
    assert kwargs["project_file"] == project_file
    assert kwargs["workspace_dir"] == str(allocated_workspace)
    assert kwargs["is_home_mode"] is False
    assert kwargs["update_target"] == VCS_DEFAULT_REVISION
    assert kwargs["cl_name"] == "sase"
    assert kwargs["vcs_ref"] == ("gh", "sase")
    assert kwargs["retry_transfer_from_pid"] == os.getpid()


def test_launch_agent_from_cwd_owner_repo_ref_uses_workspace_match_for_duplicate_basename(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_cd_metadata(monkeypatch)
    from sase.agent.launcher import launch_agent_from_cwd
    from sase.vcs_provider import VCS_DEFAULT_REVISION

    monkeypatch.setenv("HOME", str(tmp_path))
    foo_workspace = tmp_path / "projects" / "github" / "foo-org" / "foo"
    bar_workspace = tmp_path / "projects" / "github" / "bar-org" / "foo"
    foo_workspace.mkdir(parents=True)
    bar_workspace.mkdir(parents=True)
    allocated_workspace = tmp_path / "gh_bar_org__foo_101"
    allocated_workspace.mkdir()
    project_file = str(
        tmp_path / ".sase" / "projects" / "gh_bar_org__foo" / "gh_bar_org__foo.sase"
    )
    spawn_result = MagicMock(
        pid=123, workspace_dir=str(allocated_workspace), workspace_num=101
    )
    monkeypatch.setattr(
        "sase.xprompt.loader.get_known_project_workspaces",
        lambda *_args, **_kwargs: {
            "gh_foo_org__foo": foo_workspace,
            "gh_bar_org__foo": bar_workspace,
        },
    )

    with (
        patch(
            "sase.main.utils.ensure_project_file_and_get_workspace_num",
            return_value=(None, None, None),
        ),
        patch("sase.history.prompt.add_or_update_prompt"),
        patch(
            "sase.core.agent_launch_facade.reserve_launch_timestamp_batch",
            return_value=["260501_120000"],
        ),
        patch(
            "sase.agent.launcher.spawn_agent_subprocess",
            return_value=spawn_result,
        ) as spawn,
        patch(
            "sase.running_field.claim_next_axe_workspace",
            return_value=101,
        ) as claim_ws,
        patch(
            "sase.running_field.get_workspace_directory_for_num",
            return_value=(str(allocated_workspace), None),
        ) as ws_dir,
    ):
        result = launch_agent_from_cwd("#gh:bar-org/foo #!gh_bar_org__foo/fix")

    assert result is spawn_result
    kwargs = spawn.call_args.kwargs
    assert kwargs["prompt"] == "#gh:bar-org/foo #!gh_bar_org__foo/fix"
    assert kwargs["project_name"] == "gh_bar_org__foo"
    assert kwargs["project_file"] == project_file
    assert kwargs["workspace_dir"] == str(allocated_workspace)
    assert kwargs["is_home_mode"] is False
    assert kwargs["update_target"] == VCS_DEFAULT_REVISION
    assert kwargs["cl_name"] == "gh_bar_org__foo"
    assert kwargs["history_sort_key"] == "gh_bar_org__foo"
    assert kwargs["vcs_ref"] == ("gh", "gh_bar_org__foo")
    claim_ws.assert_called_once()
    assert claim_ws.call_args.args[0] == project_file
    ws_dir.assert_called_once_with(101, "gh_bar_org__foo")


def test_launch_agent_from_cwd_ignores_fenced_wait_snapshot_for_deferred_workspace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A fenced old prompt snapshot must not force placeholder workspace 0."""
    patch_cd_metadata(monkeypatch)
    from sase.agent.launcher import launch_agent_from_cwd

    monkeypatch.setenv("HOME", str(tmp_path))
    workspace = tmp_path / "sase"
    workspace.mkdir()
    allocated_workspace = tmp_path / "sase_101"
    allocated_workspace.mkdir()
    project_file = str(tmp_path / ".sase" / "projects" / "sase" / "sase.sase")
    spawn_result = MagicMock(
        pid=123, workspace_dir=str(allocated_workspace), workspace_num=101
    )
    monkeypatch.setattr(
        "sase.xprompt.loader.get_known_project_workspaces",
        lambda: {"sase": workspace},
    )

    prompt = "#gh:sase-org/sase\n```text\n%w:old_agent\n```\nDo work"
    with (
        patch(
            "sase.main.utils.ensure_project_file_and_get_workspace_num",
            return_value=(None, None, None),
        ),
        patch("sase.history.prompt.add_or_update_prompt"),
        patch(
            "sase.core.agent_launch_facade.reserve_launch_timestamp_batch",
            return_value=["260501_120000"],
        ),
        patch(
            "sase.agent.launcher.spawn_agent_subprocess",
            return_value=spawn_result,
        ) as spawn,
        patch(
            "sase.running_field.claim_next_axe_workspace",
            return_value=101,
        ),
        patch(
            "sase.running_field.get_workspace_directory_for_num",
            return_value=(str(allocated_workspace), None),
        ),
    ):
        result = launch_agent_from_cwd(prompt)

    assert result is spawn_result
    kwargs = spawn.call_args.kwargs
    assert kwargs["project_name"] == "sase"
    assert kwargs["project_file"] == project_file
    assert kwargs["workspace_dir"] == str(allocated_workspace)
    assert kwargs["workspace_num"] == 101
    assert kwargs["deferred_workspace"] is False
    assert kwargs["retry_transfer_from_pid"] == os.getpid()
