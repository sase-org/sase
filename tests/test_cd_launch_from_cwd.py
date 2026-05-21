"""``launch_agent_from_cwd`` tests for built-in ``#cd`` launch resolution."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.workspace_provider._hookspec import ResolvedRef
from tests._cd_launch_resolution_helpers import (
    patch_cd_git_metadata,
    patch_cd_metadata,
)


def test_launch_agent_from_cwd_cd_launches_in_target_without_workspace_claim(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_cd_metadata(monkeypatch)
    from sase.agent.launcher import launch_agent_from_cwd

    spawn_result = MagicMock(pid=123, workspace_dir=str(tmp_path), workspace_num=0)
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
        patch("sase.running_field.get_first_available_axe_workspace") as first_ws,
        patch("sase.running_field.get_workspace_directory_for_num") as ws_dir,
    ):
        result = launch_agent_from_cwd(f"#cd:{tmp_path} do work")

    assert result is spawn_result
    kwargs = spawn.call_args.kwargs
    assert kwargs["workspace_dir"] == str(tmp_path.resolve())
    assert kwargs["workspace_num"] == 0
    assert kwargs["is_home_mode"] is True
    assert kwargs["update_target"] == ""
    assert kwargs["vcs_ref"] == ("cd", str(tmp_path))
    first_ws.assert_not_called()
    ws_dir.assert_not_called()


def test_launch_agent_from_cwd_no_ref_defaults_to_git_home(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_cd_git_metadata(monkeypatch)
    from sase.agent.launcher import launch_agent_from_cwd
    from sase.vcs_provider import VCS_DEFAULT_REVISION

    primary_workspace = tmp_path / "home"
    allocated_workspace = tmp_path / "home_101"
    project_file = str(tmp_path / "home.sase")
    spawn_result = MagicMock(
        pid=123, workspace_dir=str(allocated_workspace), workspace_num=101
    )
    with (
        patch(
            "sase.main.utils.ensure_project_file_and_get_workspace_num",
            return_value=("/projects/repo/repo.sase", 3, "repo"),
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
            "sase.workspace_provider.resolve_ref",
            return_value=ResolvedRef(
                project_file=project_file,
                project_name="home",
                primary_workspace_dir=str(primary_workspace),
                checkout_target="main",
            ),
        ) as resolve_ref,
        patch(
            "sase.running_field.get_first_available_axe_workspace",
            return_value=101,
        ) as first_ws,
        patch(
            "sase.workspace_provider.get_workspace_directory",
            return_value=str(allocated_workspace),
        ) as provider_ws_dir,
        patch("sase.running_field.get_workspace_directory_for_num") as ws_dir,
    ):
        result = launch_agent_from_cwd("do work")

    assert result is spawn_result
    kwargs = spawn.call_args.kwargs
    assert kwargs["prompt"] == "#git:home do work"
    assert kwargs["project_name"] == "home"
    assert kwargs["workspace_dir"] == str(allocated_workspace)
    assert kwargs["workspace_num"] == 101
    assert kwargs["is_home_mode"] is False
    assert kwargs["update_target"] == VCS_DEFAULT_REVISION
    assert kwargs["vcs_ref"] == ("git", "home")
    resolve_ref.assert_called_once_with("home", "git")
    first_ws.assert_called_once_with(project_file)
    provider_ws_dir.assert_called_once_with(
        "git",
        101,
        "home",
        str(primary_workspace),
    )
    ws_dir.assert_not_called()


def test_launch_agent_from_cwd_alt_fanout_uses_named_child_prompts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_cd_metadata(monkeypatch)
    from sase.agent.launcher import launch_agent_from_cwd, launch_agents_from_cwd

    spawn_result = MagicMock(pid=123, workspace_dir=str(tmp_path), workspace_num=0)
    with (
        patch(
            "sase.main.utils.ensure_project_file_and_get_workspace_num",
            return_value=(None, None, None),
        ),
        patch("sase.history.prompt.add_or_update_prompt"),
        patch(
            "sase.core.agent_launch_facade.reserve_launch_timestamp_batch",
            return_value=["260501_120000", "260501_120001"],
        ),
        patch(
            "sase.agent.launcher.spawn_agent_subprocess",
            return_value=spawn_result,
        ) as spawn,
        patch("sase.running_field.get_first_available_axe_workspace") as first_ws,
        patch("sase.running_field.get_workspace_directory_for_num") as ws_dir,
    ):
        result = launch_agent_from_cwd(
            f"%n:ag\n%alt(sec=security pass,perf=performance pass)\n"
            f"#cd:{tmp_path} do work"
        )
        all_results = launch_agents_from_cwd(
            f"%n:ag\n%alt(sec=security pass,perf=performance pass)\n"
            f"#cd:{tmp_path} do work"
        )

    assert result is spawn_result
    assert all_results == [spawn_result, spawn_result]
    assert spawn.call_count == 4
    prompts = [c.kwargs["prompt"] for c in spawn.call_args_list]
    assert prompts == [
        f"%name:ag.sec\nsecurity pass\n#cd:{tmp_path} do work",
        f"%name:ag.perf\nperformance pass\n#cd:{tmp_path} do work",
        f"%name:ag.sec\nsecurity pass\n#cd:{tmp_path} do work",
        f"%name:ag.perf\nperformance pass\n#cd:{tmp_path} do work",
    ]
    first_ws.assert_not_called()
    ws_dir.assert_not_called()


def test_launch_agents_from_cwd_xprompt_expanded_multi_model_fans_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_cd_metadata(monkeypatch)
    from sase.agent.launcher import launch_agents_from_cwd

    launched = [MagicMock(name="opus"), MagicMock(name="sonnet")]
    expanded = "%n:ag\n%m(opus,sonnet)\nDo work"
    with (
        patch(
            "sase.main.utils.ensure_project_file_and_get_workspace_num",
            return_value=(None, None, None),
        ),
        patch("sase.history.prompt.add_or_update_prompt"),
        patch(
            "sase.xprompt.processor.process_xprompt_references",
            return_value=expanded,
        ) as expand,
        patch(
            "sase.agent.multi_prompt_launcher.launch_multi_prompt_agents",
            return_value=launched,
        ) as launch_multi,
    ):
        result = launch_agents_from_cwd("#stub_m Do work")

    assert result == launched
    expand.assert_called_once_with("#stub_m Do work")
    launch_multi.assert_called_once()
    assert launch_multi.call_args.kwargs["segments"] == [
        "%name:ag.cld_opus\n%model:opus\nDo work",
        "%name:ag.cld_sonnet\n%model:sonnet\nDo work",
    ]


def test_launch_agents_from_cwd_unexpanded_xprompt_stays_single_agent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_cd_metadata(monkeypatch)
    from sase.agent.launcher import launch_agents_from_cwd

    spawn_result = MagicMock(pid=123, workspace_dir=str(tmp_path), workspace_num=0)
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
            "sase.xprompt.processor.process_xprompt_references",
            return_value="#stub_m Do work",
        ) as expand,
        patch(
            "sase.agent.multi_prompt_launcher.launch_multi_prompt_agents",
        ) as launch_multi,
        patch(
            "sase.agent.launcher.spawn_agent_subprocess",
            return_value=spawn_result,
        ) as spawn,
    ):
        result = launch_agents_from_cwd("#stub_m Do work")

    assert result == [spawn_result]
    expand.assert_called_once_with("#stub_m Do work")
    launch_multi.assert_not_called()
    spawn.assert_called_once()
    assert spawn.call_args.kwargs["prompt"] == "#stub_m Do work"


def test_launch_agents_from_cwd_multi_agent_xprompt_history_uses_submitted_prompt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_cd_metadata(monkeypatch)
    from sase.agent.launcher import launch_agents_from_cwd
    from sase.history import prompt as prompt_history
    from sase.xprompt.models import XPrompt

    history_path = tmp_path / ".sase" / "prompt_history.json"
    monkeypatch.setattr(prompt_history, "_PROMPT_HISTORY_FILE", history_path)
    monkeypatch.setattr(
        prompt_history, "_get_current_branch_or_workspace", lambda: "main"
    )
    monkeypatch.setattr(prompt_history, "generate_timestamp", lambda: "260501_120000")
    launched = [MagicMock(name="plan"), MagicMock(name="build")]
    catalog = {"swarm": XPrompt(name="swarm", content="Plan phase\n---\nBuild phase")}

    with (
        patch(
            "sase.main.utils.ensure_project_file_and_get_workspace_num",
            return_value=(None, None, None),
        ),
        patch(
            "sase.agent.multi_agent_xprompt.get_all_xprompts",
            return_value=catalog,
        ),
        patch(
            "sase.agent.multi_prompt_launcher.launch_multi_prompt_agents",
            return_value=launched,
        ) as launch_multi,
    ):
        result = launch_agents_from_cwd("#!swarm")

    assert result == launched
    assert launch_multi.call_args.kwargs["segments"] == ["Plan phase", "Build phase"]
    entries = json.loads(history_path.read_text(encoding="utf-8"))["prompts"]
    assert [entry["text"] for entry in entries] == ["#!swarm"]
    assert all("Plan phase" not in entry["text"] for entry in entries)


def test_launch_agents_from_cwd_multi_agent_xprompt_cancelled_history_uses_submitted_prompt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_cd_metadata(monkeypatch)
    from sase.agent.launch_validation import AgentNameSyntaxError
    from sase.agent.launcher import launch_agents_from_cwd
    from sase.history import prompt as prompt_history
    from sase.xprompt.models import XPrompt

    history_path = tmp_path / ".sase" / "prompt_history.json"
    monkeypatch.setattr(prompt_history, "_PROMPT_HISTORY_FILE", history_path)
    monkeypatch.setattr(
        prompt_history, "_get_current_branch_or_workspace", lambda: "main"
    )
    monkeypatch.setattr(prompt_history, "generate_timestamp", lambda: "260501_120000")
    catalog = {
        "swarm": XPrompt(
            name="swarm",
            content="%name:bad-name\nPlan phase\n---\nBuild phase",
        )
    }

    with (
        patch(
            "sase.main.utils.ensure_project_file_and_get_workspace_num",
            return_value=(None, None, None),
        ),
        patch(
            "sase.agent.multi_agent_xprompt.get_all_xprompts",
            return_value=catalog,
        ),
        patch("sase.agent.multi_prompt_launcher.launch_multi_prompt_agents") as launch,
    ):
        with pytest.raises(AgentNameSyntaxError):
            launch_agents_from_cwd("#!swarm")

    launch.assert_not_called()
    entries = json.loads(history_path.read_text(encoding="utf-8"))["prompts"]
    assert [entry["text"] for entry in entries] == ["#!swarm"]
    assert entries[0]["cancelled"] is True
    assert "Plan phase" not in entries[0]["text"]


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
    # Pre-claim under parent PID — atomic find+claim under the project lock.
    first_ws.assert_called_once()
    assert first_ws.call_args.args[0] == project_file
    ws_dir.assert_called_once_with(101, "sase")


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


def test_launch_agent_from_cwd_wait_cd_stays_directory_mode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_cd_metadata(monkeypatch)
    from sase.agent.launcher import launch_agent_from_cwd

    spawn_result = MagicMock(pid=123, workspace_dir=str(tmp_path), workspace_num=0)
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
        patch("sase.running_field.get_first_available_axe_workspace") as first_ws,
        patch("sase.running_field.get_workspace_directory_for_num") as ws_dir,
    ):
        result = launch_agent_from_cwd(f"%wait:1s #cd:{tmp_path} do work")

    assert result is spawn_result
    kwargs = spawn.call_args.kwargs
    assert kwargs["workspace_dir"] == str(tmp_path.resolve())
    assert kwargs["workspace_num"] == 0
    assert kwargs["is_home_mode"] is True
    assert kwargs["deferred_workspace"] is True
    assert kwargs["vcs_ref"] == ("cd", str(tmp_path))
    first_ws.assert_not_called()
    ws_dir.assert_not_called()


def test_launch_agent_from_cwd_bad_cd_path_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_cd_metadata(monkeypatch)
    from sase.agent.launcher import launch_agent_from_cwd

    with (
        patch(
            "sase.main.utils.ensure_project_file_and_get_workspace_num",
            return_value=(None, None, None),
        ),
        patch("sase.agent.launcher.spawn_agent_subprocess") as spawn,
    ):
        with pytest.raises(ValueError, match="does not exist"):
            launch_agent_from_cwd(f"#cd:{tmp_path / 'missing'} do work")

    spawn.assert_not_called()
