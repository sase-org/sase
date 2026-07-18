"""Tests for core multi-prompt launch behavior."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.agent.multi_prompt_launcher import launch_multi_prompt_agents


@patch("sase.agent.launcher.spawn_agent_subprocess")
@patch("sase.agent.multi_prompt_launcher._wait_for_agent_naming")
@patch("sase.core.time.generate_timestamp")
@patch("sase.artifacts.create_artifacts_directory")
@patch("sase.running_field.claim_next_axe_workspace")
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
        project_file="/test.sase",
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
@patch("sase.running_field.claim_next_axe_workspace")
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
        project_file="/test.sase",
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
@patch("sase.agent.names.get_reserved_agent_names", return_value=set())
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
        project_file="/test.sase",
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
    assert calls[0].kwargs["extra_env"]["SASE_AGENT_PLANNED_NAME"] == "0"
    assert calls[1].kwargs["extra_env"]["SASE_AGENT_PLANNED_NAME"] == "0.w0"
    assert calls[2].kwargs["extra_env"]["SASE_AGENT_PLANNED_NAME"] == "0.w0.w0"
    assert calls[1].kwargs["prompt"].startswith("%wait:0")
    assert calls[2].kwargs["prompt"].startswith("%wait:0.w0")


@pytest.mark.parametrize(
    ("prompt", "planned_name"),
    [
        ("#fork:foo\nReview", "foo.f0"),
        ("#fork:@epic\nReview", "0"),
    ],
)
@patch("sase.agent.launcher.spawn_agent_subprocess")
@patch("sase.agent.multi_prompt_launcher._wait_for_agent_naming")
@patch("sase.core.time.generate_timestamp")
@patch("sase.artifacts.create_artifacts_directory")
@patch("sase.running_field.claim_next_axe_workspace", return_value=100)
@patch("sase.running_field.get_workspace_directory", return_value="/ws/main")
@patch(
    "sase.running_field.get_workspace_directory_for_num",
    return_value=("/ws/100", None),
)
def test_launch_multi_prompt_fork_reference_defers_workspace(
    mock_ws_dir: MagicMock,
    mock_wait_ws_dir: MagicMock,
    mock_claim_ws: MagicMock,
    mock_create_artifacts: MagicMock,
    mock_timestamp: MagicMock,
    mock_wait: MagicMock,
    mock_spawn: MagicMock,
    tmp_path: Path,
    prompt: str,
    planned_name: str,
) -> None:
    """An explicit fork target should not claim a numbered workspace."""
    mock_timestamp.return_value = "260501_120000"
    mock_wait.return_value = "alpha"
    mock_spawn.return_value = MagicMock(pid=1)

    with patch.object(Path, "home", return_value=tmp_path):
        launch_multi_prompt_agents(
            segments=[prompt],
            local_xprompts={},
            cl_name="test",
            project_file="/test.sase",
            project_name="test",
            is_home_mode=False,
            vcs_ref=None,
        )

    kwargs = mock_spawn.call_args.kwargs
    assert kwargs["workspace_num"] == 0
    assert kwargs["workspace_dir"] == "/ws/main"
    assert kwargs["deferred_workspace"] is True
    assert kwargs["extra_env"]["SASE_AGENT_PLANNED_NAME"] == planned_name
    mock_claim_ws.assert_not_called()
    mock_ws_dir.assert_not_called()
    mock_create_artifacts.assert_not_called()
    mock_wait.assert_not_called()


@patch("sase.agent.launcher.spawn_agent_subprocess")
@patch("sase.agent.multi_prompt_launcher._wait_for_agent_naming")
@patch("sase.core.time.generate_timestamp")
@patch("sase.artifacts.create_artifacts_directory")
@patch("sase.running_field.claim_next_axe_workspace")
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
        project_file="/test.sase",
        project_name="test",
        is_home_mode=False,
        vcs_ref=None,
    )

    calls = mock_spawn.call_args_list
    assert calls[0].kwargs["timestamp"] == "260501_120000"
    assert calls[1].kwargs["timestamp"] == "260501_120001"
    assert calls[0].kwargs["workspace_num"] == 100
    assert calls[1].kwargs["workspace_num"] == 101
