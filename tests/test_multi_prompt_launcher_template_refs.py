"""Tests for multi-prompt template reference planning."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from tests._agent_names_fixtures import make_agent
from tests._multi_prompt_launcher_launch_helpers import spawn_result_with_planned_name
from sase.agent.multi_prompt_launcher import launch_multi_prompt_agents


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
def test_launch_multi_prompt_resolves_template_wait_to_planned_predecessor(
    mock_ws_dir: MagicMock,
    mock_first_ws: MagicMock,
    mock_wait_ws_dir: MagicMock,
    mock_create_artifacts: MagicMock,
    mock_timestamp: MagicMock,
    mock_wait: MagicMock,
    mock_spawn: MagicMock,
    tmp_path: Path,
) -> None:
    """Later segments can wait on a template name planned earlier in the batch."""
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
    assert [result.agent_name for result in results] == ["build-0", "build-0.w0"]
    assert calls[0].kwargs["prompt"] == "%n:build-@\nBuild"
    assert calls[1].kwargs["prompt"] == "%w:build-0\nReview"
    assert calls[0].kwargs["extra_env"]["SASE_AGENT_PLANNED_NAME"] == "build-0"
    assert calls[1].kwargs["extra_env"]["SASE_AGENT_PLANNED_NAME"] == "build-0.w0"
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
def test_launch_multi_prompt_allocates_distinct_template_names_per_segment(
    mock_ws_dir: MagicMock,
    mock_first_ws: MagicMock,
    mock_create_artifacts: MagicMock,
    mock_timestamp: MagicMock,
    mock_wait: MagicMock,
    mock_spawn: MagicMock,
    tmp_path: Path,
) -> None:
    """Two identical name templates in one launch reserve consecutive names."""
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

    assert [result.agent_name for result in results] == ["build-0", "build-1"]
    assert [
        call.kwargs["extra_env"]["SASE_AGENT_PLANNED_NAME"]
        for call in mock_spawn.call_args_list
    ] == ["build-0", "build-1"]
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
def test_launch_multi_prompt_allocates_distinct_suffix_shape_template_names(
    mock_ws_dir: MagicMock,
    mock_first_ws: MagicMock,
    mock_create_artifacts: MagicMock,
    mock_timestamp: MagicMock,
    mock_wait: MagicMock,
    mock_spawn: MagicMock,
    tmp_path: Path,
) -> None:
    """Generic suffix-shape templates allocate by rendering template tokens."""
    mock_spawn.side_effect = spawn_result_with_planned_name

    with patch.object(Path, "home", return_value=tmp_path):
        results = launch_multi_prompt_agents(
            segments=["%n:@.cld\nFirst", "%n:@.cld\nSecond"],
            local_xprompts={},
            cl_name="test",
            project_file="/test.sase",
            project_name="test",
            is_home_mode=False,
            vcs_ref=None,
        )

    assert [result.agent_name for result in results] == ["0.cld", "1.cld"]
    assert [
        call.kwargs["extra_env"]["SASE_AGENT_PLANNED_NAME"]
        for call in mock_spawn.call_args_list
    ] == ["0.cld", "1.cld"]
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
def test_launch_multi_prompt_resolves_template_resume_to_planned_predecessor(
    mock_ws_dir: MagicMock,
    mock_first_ws: MagicMock,
    mock_wait_ws_dir: MagicMock,
    mock_create_artifacts: MagicMock,
    mock_timestamp: MagicMock,
    mock_wait: MagicMock,
    mock_spawn: MagicMock,
    tmp_path: Path,
) -> None:
    """#fork/#resume template refs resolve to the latest planned concrete name."""
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
        "#fork:build-0\n#resume:build-0\nReview"
    )
    assert (
        mock_spawn.call_args_list[1].kwargs["extra_env"]["SASE_AGENT_PLANNED_NAME"]
        == "build-0.f0"
    )
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
def test_launch_multi_prompt_resolves_middle_template_wait_to_planned_name(
    mock_ws_dir: MagicMock,
    mock_first_ws: MagicMock,
    mock_wait_ws_dir: MagicMock,
    mock_create_artifacts: MagicMock,
    mock_timestamp: MagicMock,
    mock_wait: MagicMock,
    mock_spawn: MagicMock,
    tmp_path: Path,
) -> None:
    """Middle-marker wait refs resolve to earlier planned concrete names."""
    mock_spawn.side_effect = spawn_result_with_planned_name

    with patch.object(Path, "home", return_value=tmp_path):
        results = launch_multi_prompt_agents(
            segments=[
                "%n:research.@.final\nFinal",
                "%w:research.@.final\nReview",
            ],
            local_xprompts={},
            cl_name="test",
            project_file="/test.sase",
            project_name="test",
            is_home_mode=False,
            vcs_ref=None,
        )

    assert [result.agent_name for result in results] == [
        "research.0.final",
        "research.0.final.w0",
    ]
    assert mock_spawn.call_args_list[1].kwargs["prompt"] == (
        "%w:research.0.final\nReview"
    )
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
def test_launch_multi_prompt_template_refs_prefer_planned_over_existing_latest(
    mock_ws_dir: MagicMock,
    mock_first_ws: MagicMock,
    mock_wait_ws_dir: MagicMock,
    mock_create_artifacts: MagicMock,
    mock_timestamp: MagicMock,
    mock_wait: MagicMock,
    mock_spawn: MagicMock,
    tmp_path: Path,
) -> None:
    """Current-batch planned names win over a higher existing template token."""
    make_agent(tmp_path, "proj", "run1", "build-z")
    mock_spawn.side_effect = spawn_result_with_planned_name

    with patch.object(Path, "home", return_value=tmp_path):
        launch_multi_prompt_agents(
            segments=["%n:build-@\nBuild", "%w:build-@\nReview"],
            local_xprompts={},
            cl_name="test",
            project_file="/test.sase",
            project_name="test",
            is_home_mode=False,
            vcs_ref=None,
        )

    assert mock_spawn.call_args_list[1].kwargs["prompt"] == "%w:build-0\nReview"
    assert mock_wait.call_count == 0
    assert mock_create_artifacts.call_count == 0


@patch("sase.agent.launcher.spawn_agent_subprocess")
@patch("sase.agent.multi_prompt_launcher._wait_for_agent_naming")
@patch("sase.core.time.generate_timestamp", return_value="260501_120000")
@patch("sase.artifacts.create_artifacts_directory", return_value="/a")
@patch("sase.running_field.get_workspace_directory", return_value="/ws/main")
@patch("sase.agent.launch_projects.extract_known_project_vcs_launch_ref")
def test_launch_multi_prompt_same_segment_template_wait_uses_existing_latest(
    mock_known_project_ref: MagicMock,
    mock_wait_ws_dir: MagicMock,
    mock_create_artifacts: MagicMock,
    mock_timestamp: MagicMock,
    mock_wait: MagicMock,
    mock_spawn: MagicMock,
    tmp_path: Path,
) -> None:
    """Template waits resolve before a same-segment template name is allocated."""
    mock_known_project_ref.return_value = None
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

    assert [result.agent_name for result in results] == ["build-0"]
    assert mock_spawn.call_args.kwargs["prompt"] == "%w:build-1\n%n:build-@\nDo work"
    assert (
        mock_spawn.call_args.kwargs["extra_env"]["SASE_AGENT_PLANNED_NAME"] == "build-0"
    )
    assert mock_wait.call_count == 0
    assert mock_create_artifacts.call_count == 0
