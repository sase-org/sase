"""Tests for core multi-prompt launch behavior."""

from unittest.mock import MagicMock, patch

from sase.agent.multi_prompt_launcher import launch_multi_prompt_agents


@patch("sase.agent.launcher.spawn_agent_subprocess")
@patch("sase.agent.multi_prompt_launcher._wait_for_agent_naming")
@patch("sase.core.time.generate_timestamp")
@patch("sase.artifacts.create_artifacts_directory")
@patch("sase.running_field.get_first_available_axe_workspace")
@patch("sase.running_field.get_workspace_directory_for_num")
def test_launch_multi_prompt_sequential_calls(
    mock_ws_dir: MagicMock,
    mock_first_ws: MagicMock,
    mock_create_artifacts: MagicMock,
    mock_timestamp: MagicMock,
    mock_wait: MagicMock,
    mock_spawn: MagicMock,
) -> None:
    """Verifies sequential spawn calls without unneeded naming waits."""
    mock_first_ws.return_value = 100
    mock_ws_dir.return_value = ("/workspace/100", None)
    mock_timestamp.return_value = "260501_120000"
    mock_wait.return_value = "alpha"
    mock_create_artifacts.return_value = "/artifacts/dir"
    mock_spawn.return_value = MagicMock(pid=1)

    results = launch_multi_prompt_agents(
        segments=["seg1", "seg2", "seg3"],
        local_xprompts={},
        cl_name="test",
        project_file="/test.gp",
        project_name="test",
        is_home_mode=False,
        vcs_ref=None,
    )

    assert len(results) == 3
    assert mock_spawn.call_count == 3
    assert mock_wait.call_count == 0
    assert mock_create_artifacts.call_count == 0


@patch("sase.agent.launcher.spawn_agent_subprocess")
@patch("sase.agent.multi_prompt_launcher._wait_for_agent_naming")
@patch("sase.core.time.generate_timestamp")
@patch("sase.artifacts.create_artifacts_directory")
@patch("sase.running_field.get_first_available_axe_workspace")
@patch("sase.running_field.get_workspace_directory_for_num")
def test_launch_multi_prompt_allocates_unique_timestamps_without_sleep(
    mock_ws_dir: MagicMock,
    mock_first_ws: MagicMock,
    mock_create_artifacts: MagicMock,
    mock_timestamp: MagicMock,
    mock_wait: MagicMock,
    mock_spawn: MagicMock,
) -> None:
    """Duplicate wall-clock timestamps are batch-adjusted without sleeping."""
    mock_first_ws.side_effect = [100, 101, 102]
    mock_ws_dir.side_effect = [
        ("/ws/100", None),
        ("/ws/101", None),
        ("/ws/102", None),
    ]
    mock_timestamp.return_value = "260501_120000"
    mock_wait.return_value = "alpha"
    mock_create_artifacts.return_value = "/artifacts/dir"
    mock_spawn.return_value = MagicMock(pid=1)

    launch_multi_prompt_agents(
        segments=["seg1", "seg2", "seg3"],
        local_xprompts={},
        cl_name="test",
        project_file="/test.gp",
        project_name="test",
        is_home_mode=False,
        vcs_ref=None,
    )

    calls = mock_spawn.call_args_list
    assert [c.kwargs["timestamp"] for c in calls] == [
        "260501_120000",
        "260501_120001",
        "260501_120002",
    ]
    assert [c.kwargs["workflow_name"] for c in calls] == [
        "ace(run)-260501_120000",
        "ace(run)-260501_120001",
        "ace(run)-260501_120002",
    ]


@patch("sase.agent.launcher.spawn_agent_subprocess")
@patch("sase.agent.multi_prompt_launcher._wait_for_agent_naming")
@patch("sase.core.time.generate_timestamp")
@patch("sase.artifacts.create_artifacts_directory")
@patch("sase.agent.names.get_active_agent_names", return_value=set())
@patch("sase.running_field.get_workspace_directory")
def test_launch_multi_prompt_wait_segments_get_unique_artifacts(
    mock_wait_ws_dir: MagicMock,
    mock_active_names: MagicMock,
    mock_create_artifacts: MagicMock,
    mock_timestamp: MagicMock,
    mock_wait: MagicMock,
    mock_spawn: MagicMock,
) -> None:
    """Multiple %wait segments in one batch do not reuse launch identity."""
    mock_wait_ws_dir.return_value = "/ws/1"
    mock_timestamp.return_value = "260501_120000"
    mock_wait.return_value = "alpha"
    mock_create_artifacts.return_value = "/artifacts/dir"
    mock_spawn.return_value = MagicMock(pid=1)

    launch_multi_prompt_agents(
        segments=["%wait first", "%wait second", "%wait land"],
        local_xprompts={},
        cl_name="test",
        project_file="/test.gp",
        project_name="test",
        is_home_mode=False,
        vcs_ref=None,
    )

    calls = mock_spawn.call_args_list
    assert [c.kwargs["timestamp"] for c in calls] == [
        "260501_120000",
        "260501_120001",
        "260501_120002",
    ]
    assert [c.kwargs["workflow_name"] for c in calls] == [
        "ace(run)-260501_120000",
        "ace(run)-260501_120001",
        "ace(run)-260501_120002",
    ]
    assert [c.kwargs["workspace_num"] for c in calls] == [0, 0, 0]
    assert [c.kwargs["deferred_workspace"] for c in calls] == [True, True, True]
    assert mock_create_artifacts.call_count == 0
    assert mock_wait.call_count == 0
    assert calls[0].kwargs["extra_env"]["SASE_AGENT_PLANNED_NAME"] == "a"
    assert calls[1].kwargs["extra_env"]["SASE_AGENT_PLANNED_NAME"] == "b"
    assert calls[1].kwargs["prompt"].startswith("%wait:a")
    assert calls[2].kwargs["prompt"].startswith("%wait:b")


@patch("sase.agent.launcher.spawn_agent_subprocess")
@patch("sase.agent.multi_prompt_launcher._wait_for_agent_naming")
@patch("sase.core.time.generate_timestamp")
@patch("sase.artifacts.create_artifacts_directory")
@patch("sase.running_field.get_first_available_axe_workspace")
@patch("sase.running_field.get_workspace_directory_for_num")
def test_launch_multi_prompt_each_gets_own_timestamp(
    mock_ws_dir: MagicMock,
    mock_first_ws: MagicMock,
    mock_create_artifacts: MagicMock,
    mock_timestamp: MagicMock,
    mock_wait: MagicMock,
    mock_spawn: MagicMock,
) -> None:
    """Each segment gets its own timestamp and workspace."""
    mock_first_ws.side_effect = [100, 101]
    mock_ws_dir.side_effect = [("/ws/100", None), ("/ws/101", None)]
    mock_timestamp.return_value = "260501_120000"
    mock_wait.return_value = "alpha"
    mock_create_artifacts.return_value = "/artifacts/dir"
    mock_spawn.return_value = MagicMock(pid=1)

    launch_multi_prompt_agents(
        segments=["seg1", "seg2"],
        local_xprompts={},
        cl_name="test",
        project_file="/test.gp",
        project_name="test",
        is_home_mode=False,
        vcs_ref=None,
    )

    calls = mock_spawn.call_args_list
    assert calls[0].kwargs["timestamp"] == "260501_120000"
    assert calls[1].kwargs["timestamp"] == "260501_120001"
    assert calls[0].kwargs["workspace_num"] == 100
    assert calls[1].kwargs["workspace_num"] == 101


@patch("sase.agent.launcher.spawn_agent_subprocess")
@patch("sase.agent.multi_prompt_launcher._wait_for_agent_naming")
@patch("sase.core.time.generate_timestamp", return_value="260501_120000")
@patch("sase.artifacts.create_artifacts_directory", return_value="/a")
@patch("sase.running_field.get_first_available_axe_workspace", side_effect=[100, 101])
@patch(
    "sase.running_field.get_workspace_directory_for_num",
    side_effect=[("/ws1", None), ("/ws2", None)],
)
def test_launch_multi_prompt_passes_extra_env_to_each_child(
    mock_ws_dir: MagicMock,
    mock_first_ws: MagicMock,
    mock_create_artifacts: MagicMock,
    mock_timestamp: MagicMock,
    mock_wait: MagicMock,
    mock_spawn: MagicMock,
) -> None:
    """Chop metadata env is forwarded to every child agent."""
    mock_spawn.return_value = MagicMock(pid=1)
    mock_wait.return_value = "alpha"
    extra_env = {"SASE_CHOP_LUMBERJACK": "hooks", "SASE_CHOP_NAME": "split"}

    launch_multi_prompt_agents(
        segments=["seg1", "seg2"],
        local_xprompts={},
        cl_name="test",
        project_file="/test.gp",
        project_name="test",
        is_home_mode=False,
        vcs_ref=None,
        extra_env=extra_env,
    )

    assert mock_spawn.call_args_list[0].kwargs["extra_env"] == extra_env
    assert mock_spawn.call_args_list[1].kwargs["extra_env"] == extra_env
