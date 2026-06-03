"""Tests for multi-prompt launch name and reference planning."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from tests._agent_names_fixtures import make_agent
from tests._multi_prompt_launcher_launch_helpers import spawn_result_with_planned_name
from sase.agent.multi_prompt_launcher import launch_multi_prompt_agents
from sase.xprompt.models import XPrompt


@patch("sase.agent.launcher.spawn_agent_subprocess")
@patch("sase.agent.multi_prompt_launcher._wait_for_agent_naming")
@patch("sase.core.time.generate_timestamp", return_value="260501_120000")
@patch("sase.artifacts.create_artifacts_directory", return_value="/a")
@patch("sase.running_field.get_workspace_directory", return_value="/ws/main")
@patch(
    "sase.running_field.claim_next_axe_workspace",
    side_effect=[100, 101],
)
@patch(
    "sase.running_field.get_workspace_directory_for_num",
    side_effect=[("/ws1", None), ("/ws2", None)],
)
def test_launch_multi_prompt_resolves_indexed_wait_to_planned_predecessor(
    mock_ws_dir: MagicMock,
    mock_first_ws: MagicMock,
    mock_wait_ws_dir: MagicMock,
    mock_create_artifacts: MagicMock,
    mock_timestamp: MagicMock,
    mock_wait: MagicMock,
    mock_spawn: MagicMock,
    tmp_path: Path,
) -> None:
    """Later segments can wait on an indexed name planned earlier in the batch."""
    mock_spawn.side_effect = spawn_result_with_planned_name

    with patch.object(Path, "home", return_value=tmp_path):
        results = launch_multi_prompt_agents(
            segments=["%n:build-@\nBuild", "%w:build-@\nReview"],
            local_xprompts={},
            cl_name="test",
            project_file="/test.sase",
            project_name="test",
            is_home_mode=False,
            vcs_ref=None,
        )

    calls = mock_spawn.call_args_list
    assert [result.agent_name for result in results] == ["build-1", "build-1.w1"]
    assert calls[0].kwargs["prompt"] == "%n:build-@\nBuild"
    assert calls[1].kwargs["prompt"] == "%w:build-1\nReview"
    assert calls[0].kwargs["extra_env"]["SASE_AGENT_PLANNED_NAME"] == "build-1"
    assert calls[1].kwargs["extra_env"]["SASE_AGENT_PLANNED_NAME"] == "build-1.w1"
    assert mock_wait.call_count == 0
    assert mock_create_artifacts.call_count == 0


@patch("sase.agent.launcher.spawn_agent_subprocess")
@patch("sase.agent.multi_prompt_launcher._wait_for_agent_naming")
@patch("sase.core.time.generate_timestamp", return_value="260501_120000")
@patch("sase.artifacts.create_artifacts_directory", return_value="/a")
@patch(
    "sase.running_field.claim_next_axe_workspace",
    side_effect=[100, 101],
)
@patch(
    "sase.running_field.get_workspace_directory_for_num",
    side_effect=[("/ws1", None), ("/ws2", None)],
)
def test_launch_multi_prompt_allocates_distinct_indexed_names_per_segment(
    mock_ws_dir: MagicMock,
    mock_first_ws: MagicMock,
    mock_create_artifacts: MagicMock,
    mock_timestamp: MagicMock,
    mock_wait: MagicMock,
    mock_spawn: MagicMock,
    tmp_path: Path,
) -> None:
    """Two indexed name templates in one launch reserve consecutive names."""
    mock_spawn.side_effect = spawn_result_with_planned_name

    with patch.object(Path, "home", return_value=tmp_path):
        results = launch_multi_prompt_agents(
            segments=["%n:build-@\nFirst", "%n:build-@\nSecond"],
            local_xprompts={},
            cl_name="test",
            project_file="/test.sase",
            project_name="test",
            is_home_mode=False,
            vcs_ref=None,
        )

    assert [result.agent_name for result in results] == ["build-1", "build-2"]
    assert [
        call.kwargs["extra_env"]["SASE_AGENT_PLANNED_NAME"]
        for call in mock_spawn.call_args_list
    ] == ["build-1", "build-2"]
    assert mock_wait.call_count == 0
    assert mock_create_artifacts.call_count == 0


@patch("sase.agent.launcher.spawn_agent_subprocess")
@patch("sase.agent.multi_prompt_launcher._wait_for_agent_naming")
@patch("sase.core.time.generate_timestamp", return_value="260501_120000")
@patch("sase.artifacts.create_artifacts_directory", return_value="/a")
@patch("sase.running_field.get_workspace_directory", return_value="/ws/main")
@patch(
    "sase.running_field.claim_next_axe_workspace",
    side_effect=[100, 101],
)
@patch(
    "sase.running_field.get_workspace_directory_for_num",
    side_effect=[("/ws1", None), ("/ws2", None)],
)
def test_launch_multi_prompt_resolves_indexed_resume_to_planned_predecessor(
    mock_ws_dir: MagicMock,
    mock_first_ws: MagicMock,
    mock_wait_ws_dir: MagicMock,
    mock_create_artifacts: MagicMock,
    mock_timestamp: MagicMock,
    mock_wait: MagicMock,
    mock_spawn: MagicMock,
    tmp_path: Path,
) -> None:
    """#fork/#resume indexed refs resolve to the latest planned concrete name."""
    mock_spawn.side_effect = spawn_result_with_planned_name

    with patch.object(Path, "home", return_value=tmp_path):
        launch_multi_prompt_agents(
            segments=[
                "%n:build-@\nBuild",
                "#fork:build-@\n#resume:build-@\nReview",
            ],
            local_xprompts={},
            cl_name="test",
            project_file="/test.sase",
            project_name="test",
            is_home_mode=False,
            vcs_ref=None,
        )

    assert mock_spawn.call_args_list[1].kwargs["prompt"] == (
        "#fork:build-1\n#resume:build-1\nReview"
    )
    assert (
        mock_spawn.call_args_list[1].kwargs["extra_env"]["SASE_AGENT_PLANNED_NAME"]
        == "build-1.f1"
    )
    assert mock_wait.call_count == 0
    assert mock_create_artifacts.call_count == 0


@patch("sase.agent.launcher.spawn_agent_subprocess")
@patch("sase.agent.multi_prompt_launcher._wait_for_agent_naming")
@patch("sase.core.time.generate_timestamp", return_value="260501_120000")
@patch("sase.artifacts.create_artifacts_directory", return_value="/a")
@patch("sase.running_field.get_workspace_directory", return_value="/ws/main")
def test_launch_multi_prompt_same_segment_indexed_wait_uses_existing_latest(
    mock_wait_ws_dir: MagicMock,
    mock_create_artifacts: MagicMock,
    mock_timestamp: MagicMock,
    mock_wait: MagicMock,
    mock_spawn: MagicMock,
    tmp_path: Path,
) -> None:
    """Indexed waits resolve before a same-segment indexed name is allocated."""
    make_agent(tmp_path, "proj", "run1", "build-1")
    mock_spawn.side_effect = spawn_result_with_planned_name

    with patch.object(Path, "home", return_value=tmp_path):
        results = launch_multi_prompt_agents(
            segments=["%w:build-@\n%n:build-@\nDo work"],
            local_xprompts={},
            cl_name="test",
            project_file="/test.sase",
            project_name="test",
            is_home_mode=False,
            vcs_ref=None,
        )

    assert [result.agent_name for result in results] == ["build-2"]
    assert mock_spawn.call_args.kwargs["prompt"] == "%w:build-1\n%n:build-@\nDo work"
    assert (
        mock_spawn.call_args.kwargs["extra_env"]["SASE_AGENT_PLANNED_NAME"] == "build-2"
    )
    assert mock_wait.call_count == 0
    assert mock_create_artifacts.call_count == 0


@patch("sase.agent.launcher.spawn_agent_subprocess")
@patch("sase.agent.multi_prompt_launcher._wait_for_agent_naming")
@patch("sase.core.time.generate_timestamp", return_value="260501_120000")
@patch("sase.artifacts.create_artifacts_directory", return_value="/a")
@patch("sase.history.prompt.add_or_update_prompt")
@patch(
    "sase.main.utils.ensure_project_file_and_get_workspace_num",
    return_value=(None, None, None),
)
def test_launch_agents_from_cwd_resolves_indexed_refs_after_multi_xprompt_expansion(
    mock_project: MagicMock,
    mock_history: MagicMock,
    mock_create_artifacts: MagicMock,
    mock_timestamp: MagicMock,
    mock_wait: MagicMock,
    mock_spawn: MagicMock,
    tmp_path: Path,
) -> None:
    """The cwd launch path resolves indexed refs after multi-agent xprompt expansion."""
    from sase.agent.launcher import launch_agents_from_cwd

    mock_spawn.side_effect = spawn_result_with_planned_name
    catalog = {
        "ix": XPrompt(
            name="ix",
            content="%n:flow-@\nBuild\n---\n%w:flow-@\nReview",
        )
    }

    with (
        patch.object(Path, "home", return_value=tmp_path),
        patch("sase.agent.multi_agent_xprompt.get_all_xprompts", return_value=catalog),
    ):
        results = launch_agents_from_cwd("#!ix")

    assert [result.agent_name for result in results] == ["flow-1", None]
    assert [call.kwargs["prompt"] for call in mock_spawn.call_args_list] == [
        "%n:flow-@\n#git:home Build",
        "%w:flow-1\n#git:home Review",
    ]
    assert mock_wait.call_count == 0
    assert mock_create_artifacts.call_count == 0


@patch("sase.agent.launcher.spawn_agent_subprocess")
@patch("sase.agent.multi_prompt_launcher._wait_for_agent_naming")
@patch("sase.core.time.generate_timestamp")
@patch("sase.artifacts.create_artifacts_directory")
@patch("sase.running_field.get_workspace_directory")
def test_launch_multi_prompt_plans_wait_derived_sibling_names(
    mock_wait_ws_dir: MagicMock,
    mock_create_artifacts: MagicMock,
    mock_timestamp: MagicMock,
    mock_wait: MagicMock,
    mock_spawn: MagicMock,
    tmp_path: Path,
) -> None:
    """Sibling explicit waits on the same agent reserve distinct .w slots."""
    mock_wait_ws_dir.return_value = "/ws/1"
    mock_timestamp.return_value = "260501_120000"
    mock_wait.return_value = "alpha"
    mock_create_artifacts.return_value = "/artifacts/dir"
    mock_spawn.return_value = MagicMock(pid=1)

    with patch.object(Path, "home", return_value=tmp_path):
        launch_multi_prompt_agents(
            segments=["%wait:foo first", "%wait:foo second"],
            local_xprompts={},
            cl_name="test",
            project_file="/test.sase",
            project_name="test",
            is_home_mode=False,
            vcs_ref=None,
        )

    calls = mock_spawn.call_args_list
    assert [c.kwargs["extra_env"]["SASE_AGENT_PLANNED_NAME"] for c in calls] == [
        "foo.w1",
        "foo.w2",
    ]
    assert [c.kwargs["prompt"] for c in calls] == [
        "%wait:foo first",
        "%wait:foo second",
    ]
    assert mock_wait.call_count == 0
