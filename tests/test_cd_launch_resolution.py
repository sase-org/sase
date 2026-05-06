"""Launch-context tests for the built-in ``#cd`` workflow."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.workspace_provider._hookspec import WorkflowMetadata


def _cd_metadata() -> tuple[WorkflowMetadata, ...]:
    return (
        WorkflowMetadata(
            workflow_type="cd",
            ref_pattern=r"(?:^|(?<=\s))#cd(?:[_:]([^\s()]+)|\(([^)]*)\))",
            display_name="Directory",
            pre_allocated_env_prefix="SASE_CD",
        ),
    )


def _patch_cd_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    import sase.workspace_provider._registry as registry

    monkeypatch.setattr(registry, "get_all_workflow_metadata", _cd_metadata)


def test_resolve_ref_from_prompt_cd_skips_numbered_workspace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_cd_metadata(monkeypatch)
    from sase.ace.tui.actions.agent_workflow._ref_resolution import (
        resolve_ref_from_prompt,
    )

    with (
        patch("sase.running_field.get_first_available_axe_workspace") as first_ws,
        patch("sase.workspace_provider.get_workspace_directory") as workspace_dir,
    ):
        result = resolve_ref_from_prompt(f"#cd:{tmp_path} do work", "cd")

    assert result is not None
    project_file, project_name, resolved_dir, workspace_num, ref_value = result
    assert project_file.endswith("/projects/home/home.gp")
    assert project_name == tmp_path.name
    assert resolved_dir == str(tmp_path.resolve())
    assert workspace_num == 0
    assert ref_value == str(tmp_path)
    first_ws.assert_not_called()
    workspace_dir.assert_not_called()


def test_resolve_ref_from_prompt_bad_cd_path_raises(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_cd_metadata(monkeypatch)
    from sase.ace.tui.actions.agent_workflow._ref_resolution import (
        resolve_ref_from_prompt,
    )

    missing = tmp_path / "missing"
    with pytest.raises(ValueError, match="does not exist"):
        resolve_ref_from_prompt(f"#cd:{missing} do work", "cd")


def test_launch_agent_from_cwd_cd_launches_in_target_without_workspace_claim(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_cd_metadata(monkeypatch)
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


def test_launch_agent_from_cwd_no_ref_defaults_to_cd_home(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_cd_metadata(monkeypatch)
    from sase.agent.launcher import launch_agent_from_cwd

    home = str(Path.home().resolve())
    spawn_result = MagicMock(pid=123, workspace_dir=home, workspace_num=0)
    with (
        patch(
            "sase.main.utils.ensure_project_file_and_get_workspace_num",
            return_value=("/projects/repo/repo.gp", 3, "repo"),
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
        result = launch_agent_from_cwd("do work")

    assert result is spawn_result
    kwargs = spawn.call_args.kwargs
    assert kwargs["prompt"] == "#cd:~ do work"
    assert kwargs["workspace_dir"] == home
    assert kwargs["workspace_num"] == 0
    assert kwargs["is_home_mode"] is True
    assert kwargs["update_target"] == ""
    assert kwargs["vcs_ref"] == ("cd", "~")
    first_ws.assert_not_called()
    ws_dir.assert_not_called()


def test_launch_agent_from_cwd_alt_fanout_uses_named_child_prompts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_cd_metadata(monkeypatch)
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


def test_launch_agent_from_cwd_known_project_ref_without_provider_is_not_home_wrapped(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_cd_metadata(monkeypatch)
    from sase.agent.launcher import launch_agent_from_cwd
    from sase.vcs_provider import VCS_DEFAULT_REVISION

    workspace = tmp_path / "sase"
    workspace.mkdir()
    allocated_workspace = tmp_path / "sase_101"
    allocated_workspace.mkdir()
    project_file = str(Path.home() / ".sase" / "projects" / "sase" / "sase.gp")
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
            "sase.running_field.get_first_available_axe_workspace",
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
    first_ws.assert_called_once_with(project_file)
    ws_dir.assert_called_once_with(101, "sase")


def test_resolve_vcs_cwd_uses_known_project_workspace_without_provider(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_cd_metadata(monkeypatch)
    from sase.main.query_handler._query import _resolve_vcs_cwd

    workspace = tmp_path / "sase"
    workspace.mkdir()
    monkeypatch.setattr(
        "sase.xprompt.loader.get_known_project_workspaces",
        lambda: {"sase": workspace},
    )

    with patch("sase.xprompt.loader.detect_project") as detect_project:
        result = _resolve_vcs_cwd("#gh:sase #!sase/fix_just")

    assert result == ("sase", "sase")
    assert Path.cwd() == workspace
    detect_project.cache_clear.assert_called_once_with()


def test_launch_agent_from_cwd_wait_cd_stays_directory_mode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_cd_metadata(monkeypatch)
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
    _patch_cd_metadata(monkeypatch)
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


def test_resolve_agent_workspace_dir_prefers_explicit_directory(
    tmp_path: Path,
) -> None:
    from sase.ace.tui.widgets.prompt_panel._file_path_hints import (
        resolve_agent_workspace_dir,
    )

    target = tmp_path / "target"
    target.mkdir()

    assert resolve_agent_workspace_dir(
        0,
        str(tmp_path / "home.gp"),
        str(target),
    ) == str(target)


def test_launch_multi_prompt_agents_resolves_cd_per_segment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_cd_metadata(monkeypatch)
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
            project_file="/projects/base/base.gp",
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


def test_launch_multi_prompt_agents_defaults_bare_segment_to_cd_home(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_cd_metadata(monkeypatch)
    from sase.agent.multi_prompt_launcher import launch_multi_prompt_agents

    dir_a = tmp_path / "a"
    dir_a.mkdir()
    home = str(Path.home().resolve())

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
            segments=[f"#cd:{dir_a} first", "second"],
            local_xprompts={},
            cl_name="base",
            project_file="/projects/base/base.gp",
            project_name="base",
            is_home_mode=False,
            vcs_ref=None,
            default_bare_segments_to_home=True,
        )

    calls = spawn.call_args_list
    assert [c.kwargs["prompt"] for c in calls] == [
        f"#cd:{dir_a} first",
        "#cd:~ second",
    ]
    assert [c.kwargs["workspace_dir"] for c in calls] == [
        str(dir_a.resolve()),
        home,
    ]
    assert [c.kwargs["workspace_num"] for c in calls] == [0, 0]
    assert [c.kwargs["is_home_mode"] for c in calls] == [True, True]
    assert [c.kwargs["vcs_ref"] for c in calls] == [
        ("cd", str(dir_a)),
        ("cd", "~"),
    ]
    create_artifacts.assert_not_called()
    first_ws.assert_not_called()


def test_launch_multi_prompt_bare_home_wait_uses_home_artifacts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_cd_metadata(monkeypatch)
    from sase.agent.multi_prompt_launcher import launch_multi_prompt_agents

    home = str(Path.home().resolve())

    with (
        patch("sase.agent.launcher.spawn_agent_subprocess") as spawn,
        patch("sase.agent.multi_prompt_launcher._wait_for_agent_naming") as wait,
        patch("sase.core.time.generate_timestamp", return_value="260501_120000"),
        patch(
            "sase.artifacts.create_artifacts_directory",
            return_value="/artifacts/home",
        ) as create_artifacts,
        patch("sase.running_field.get_first_available_axe_workspace") as first_ws,
    ):
        spawn.return_value = MagicMock(pid=1)
        wait.return_value = "home-agent"
        launch_multi_prompt_agents(
            segments=["first", "%wait\nsecond"],
            local_xprompts={},
            cl_name="base",
            project_file="/projects/base/base.gp",
            project_name="base",
            is_home_mode=False,
            vcs_ref=None,
            default_bare_segments_to_home=True,
        )

    assert [c.kwargs["prompt"] for c in spawn.call_args_list] == [
        "#cd:~ first",
        "%wait:home-agent\n#cd:~ second",
    ]
    assert [c.kwargs["workspace_dir"] for c in spawn.call_args_list] == [home, home]
    create_artifacts.assert_called_once_with(
        "ace-run",
        project_name="home",
        timestamp="260501_120000",
    )
    wait.assert_called_once_with("/artifacts/home")
    first_ws.assert_not_called()


def test_resolve_vcs_cwd_cd_changes_to_target(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_cd_metadata(monkeypatch)
    from sase.main.query_handler._query import _resolve_vcs_cwd

    with (
        patch("os.chdir") as chdir,
        patch("sase.xprompt.loader.detect_project") as detect_project,
    ):
        result = _resolve_vcs_cwd(f"#cd:{tmp_path} do work")

    assert result == (tmp_path.name, str(tmp_path))
    chdir.assert_called_once_with(str(tmp_path.resolve()))
    detect_project.cache_clear.assert_called_once_with()


def test_resolve_vcs_cwd_cd_bad_path_raises(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_cd_metadata(monkeypatch)
    from sase.main.query_handler._query import _resolve_vcs_cwd

    with pytest.raises(ValueError, match="does not exist"):
        _resolve_vcs_cwd(f"#cd:{tmp_path / 'missing'} do work")
