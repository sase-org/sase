"""Tests for multi-prompt launch env propagation."""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from tests._multi_prompt_launcher_launch_helpers import spawn_result_with_planned_name
from sase.agent.output_variable_context import SASE_AGENT_VAR_UPSTREAMS_ENV
from sase.agent.multi_prompt_launcher import launch_multi_prompt_agents
from sase.history.multi_agent_prompt import MULTI_AGENT_PROMPT_FILE_ENV


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
def test_launch_multi_prompt_passes_scoped_output_variable_upstreams(
    mock_ws_dir: MagicMock,
    mock_first_ws: MagicMock,
    mock_wait_ws_dir: MagicMock,
    mock_create_artifacts: MagicMock,
    mock_timestamp: MagicMock,
    mock_wait: MagicMock,
    mock_spawn: MagicMock,
    tmp_path: Path,
) -> None:
    """Later segments receive scoped upstream identity for prior named agents."""
    mock_spawn.side_effect = spawn_result_with_planned_name

    with patch.object(Path, "home", return_value=tmp_path):
        launch_multi_prompt_agents(
            segments=[
                "%n:build-@\nBuild",
                '%w:build-@\nUse {{ agents["build"].path }}',
            ],
            local_xprompts={},
            cl_name="test",
            project_file="/test.sase",
            project_name="test",
            is_home_mode=False,
            vcs_ref=None,
        )

    first_env = mock_spawn.call_args_list[0].kwargs["extra_env"]
    second_env = mock_spawn.call_args_list[1].kwargs["extra_env"]
    assert SASE_AGENT_VAR_UPSTREAMS_ENV not in first_env
    upstreams = json.loads(second_env[SASE_AGENT_VAR_UPSTREAMS_ENV])
    assert upstreams == [
        {
            "agent_name_template": "build-@",
            "artifacts_dir": str(
                tmp_path
                / ".sase"
                / "projects"
                / "test"
                / "artifacts"
                / "ace-run"
                / "202605"
                / "01"
                / "20260501120000"
            ),
            "name": "build-0",
            "agent_key": "build",
            "project_name": "test",
            "workflow_timestamp": "260501_120000",
        }
    ]
    assert second_env["SASE_AGENT_PLANNED_NAME"] == "build-0.w0"
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
def test_launch_multi_prompt_passes_digit_leading_fanout_output_variable_upstreams(
    mock_ws_dir: MagicMock,
    mock_first_ws: MagicMock,
    mock_wait_ws_dir: MagicMock,
    mock_create_artifacts: MagicMock,
    mock_timestamp: MagicMock,
    mock_wait: MagicMock,
    mock_spawn: MagicMock,
    tmp_path: Path,
) -> None:
    """Fan-out planned names can produce scoped output-variable namespaces."""
    mock_spawn.side_effect = spawn_result_with_planned_name

    with patch.object(Path, "home", return_value=tmp_path):
        launch_multi_prompt_agents(
            segments=["%name:0n.cld\nClaude work", "%name:0n.cdx\nCodex work"],
            local_xprompts={},
            cl_name="test",
            project_file="/test.sase",
            project_name="test",
            is_home_mode=False,
            vcs_ref=None,
        )

    second_env = mock_spawn.call_args_list[1].kwargs["extra_env"]
    upstreams = json.loads(second_env[SASE_AGENT_VAR_UPSTREAMS_ENV])
    assert upstreams == [
        {
            "agent_name_template": None,
            "artifacts_dir": str(
                tmp_path
                / ".sase"
                / "projects"
                / "test"
                / "artifacts"
                / "ace-run"
                / "202605"
                / "01"
                / "20260501120000"
            ),
            "name": "0n.cld",
            "agent_key": "0n.cld",
            "project_name": "test",
            "workflow_timestamp": "260501_120000",
        }
    ]
    assert second_env["SASE_AGENT_PLANNED_NAME"] == "0n.cdx"
    assert mock_wait.call_count == 0
    assert mock_create_artifacts.call_count == 0


@patch("sase.agent.launcher.spawn_agent_subprocess")
@patch("sase.agent.multi_prompt_launcher._wait_for_agent_naming")
@patch("sase.core.time.generate_timestamp", return_value="260501_120000")
@patch("sase.artifacts.create_artifacts_directory", return_value="/a")
@patch("sase.agent.names.get_reserved_agent_names", return_value=set())
@patch("sase.running_field.claim_next_axe_workspace", side_effect=[100, 101])
@patch(
    "sase.running_field.get_workspace_directory_for_num",
    side_effect=[("/ws1", None), ("/ws2", None)],
)
def test_launch_multi_prompt_passes_extra_env_to_each_child(
    mock_ws_dir: MagicMock,
    mock_first_ws: MagicMock,
    mock_active_names: MagicMock,
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
        project_file="/test.sase",
        project_name="test",
        is_home_mode=False,
        vcs_ref=None,
        extra_env=extra_env,
    )

    # The parent allocates an auto agent name for each slot and injects it
    # via SASE_AGENT_PLANNED_NAME so AgentLaunchResult.agent_name is set
    # synchronously. Chop metadata env is still forwarded alongside.
    call0_env = mock_spawn.call_args_list[0].kwargs["extra_env"]
    call1_env = mock_spawn.call_args_list[1].kwargs["extra_env"]
    assert call0_env["SASE_CHOP_LUMBERJACK"] == "hooks"
    assert call0_env["SASE_CHOP_NAME"] == "split"
    assert call1_env["SASE_CHOP_LUMBERJACK"] == "hooks"
    assert call1_env["SASE_CHOP_NAME"] == "split"
    assert call0_env["SASE_AGENT_PLANNED_NAME"] == "0"
    assert call1_env["SASE_AGENT_PLANNED_NAME"] == "1"


@patch("sase.agent.launcher.spawn_agent_subprocess")
@patch("sase.agent.multi_prompt_launcher._wait_for_agent_naming")
@patch("sase.core.time.generate_timestamp", return_value="260501_120000")
@patch("sase.artifacts.create_artifacts_directory", return_value="/a")
@patch("sase.agent.names.get_reserved_agent_names", return_value=set())
@patch("sase.running_field.claim_next_axe_workspace", side_effect=[100, 101])
@patch(
    "sase.running_field.get_workspace_directory_for_num",
    side_effect=[("/ws1", None), ("/ws2", None)],
)
def test_launch_multi_prompt_injects_shared_multi_agent_prompt_file(
    mock_ws_dir: MagicMock,
    mock_first_ws: MagicMock,
    mock_active_names: MagicMock,
    mock_create_artifacts: MagicMock,
    mock_timestamp: MagicMock,
    mock_wait: MagicMock,
    mock_spawn: MagicMock,
) -> None:
    """Opt-in multi-agent launches write one prompt file shared by all children."""
    mock_spawn.return_value = MagicMock(pid=1)
    mock_wait.return_value = "alpha"
    submitted = "---\nmodel: test\n---\nseg1\n---\nseg2"

    launch_multi_prompt_agents(
        segments=["seg1", "seg2"],
        local_xprompts={},
        cl_name="test",
        project_file="/test.sase",
        project_name="test",
        is_home_mode=False,
        vcs_ref=None,
        multi_agent_prompt_text=submitted,
    )

    prompt_paths = {
        call.kwargs["extra_env"][MULTI_AGENT_PROMPT_FILE_ENV]
        for call in mock_spawn.call_args_list
    }
    assert prompt_paths == {
        "~/.sase/multi_prompts/202605/test-multiprompt-260501_120000.md"
    }
    prompt_path = Path(os.path.expanduser(next(iter(prompt_paths))))
    assert prompt_path.read_text(encoding="utf-8") == submitted


@patch("sase.agent.launcher.spawn_agent_subprocess")
@patch("sase.agent.multi_prompt_launcher._wait_for_agent_naming")
@patch("sase.core.time.generate_timestamp", return_value="260501_120000")
@patch("sase.artifacts.create_artifacts_directory", return_value="/a")
@patch("sase.agent.names.get_reserved_agent_names", return_value=set())
@patch("sase.running_field.claim_next_axe_workspace", return_value=100)
@patch("sase.running_field.get_workspace_directory", return_value="/ws/1")
@patch(
    "sase.running_field.get_workspace_directory_for_num",
    return_value=("/ws1", None),
)
def test_launch_multi_prompt_merges_segment_extra_env(
    mock_ws_dir: MagicMock,
    mock_wait_ws_dir: MagicMock,
    mock_first_ws: MagicMock,
    mock_active_names: MagicMock,
    mock_create_artifacts: MagicMock,
    mock_timestamp: MagicMock,
    mock_wait: MagicMock,
    mock_spawn: MagicMock,
) -> None:
    """Per-segment env is forwarded and can vary between child agents."""
    mock_spawn.return_value = MagicMock(pid=1)
    mock_wait.return_value = "alpha"

    launch_multi_prompt_agents(
        segments=["%name:first\nseg1", "%wait\nseg2"],
        local_xprompts={},
        cl_name="test",
        project_file="/test.sase",
        project_name="test",
        is_home_mode=False,
        vcs_ref=None,
        extra_env={"SASE_SHARED": "yes"},
        segment_extra_env=[
            {"SASE_BEAD_ID": "sase-x.1"},
            {"SASE_BEAD_ID": "sase-x.2"},
        ],
    )

    # Parent-side name planning adds SASE_AGENT_PLANNED_NAME per slot:
    # explicit %name:first for segment 1, then a wait-derived child name.
    assert mock_spawn.call_args_list[0].kwargs["extra_env"] == {
        "SASE_SHARED": "yes",
        "SASE_BEAD_ID": "sase-x.1",
        "SASE_AGENT_PLANNED_NAME": "first",
    }
    call1_env = mock_spawn.call_args_list[1].kwargs["extra_env"]
    assert call1_env["SASE_SHARED"] == "yes"
    assert call1_env["SASE_BEAD_ID"] == "sase-x.2"
    assert call1_env["SASE_AGENT_PLANNED_NAME"] == "first.w0"
    upstreams = json.loads(call1_env[SASE_AGENT_VAR_UPSTREAMS_ENV])
    assert upstreams[0]["name"] == "first"
    assert upstreams[0]["agent_key"] == "first"


@patch("sase.agent.launcher.spawn_agent_subprocess")
@patch("sase.agent.multi_prompt_launcher._wait_for_agent_naming")
@patch("sase.core.time.generate_timestamp", return_value="260501_120000")
@patch("sase.artifacts.create_artifacts_directory", return_value="/a")
@patch("sase.agent.names.get_reserved_agent_names", return_value=set())
@patch("sase.running_field.claim_next_axe_workspace", return_value=100)
@patch(
    "sase.running_field.get_workspace_directory_for_num",
    return_value=("/ws1", None),
)
def test_launch_multi_prompt_does_not_infer_bead_env_from_tag(
    mock_ws_dir: MagicMock,
    mock_first_ws: MagicMock,
    mock_active_names: MagicMock,
    mock_create_artifacts: MagicMock,
    mock_timestamp: MagicMock,
    mock_wait: MagicMock,
    mock_spawn: MagicMock,
) -> None:
    """A display tag alone is not treated as a bead association env."""
    mock_spawn.return_value = MagicMock(pid=1)
    mock_wait.return_value = "alpha"

    launch_multi_prompt_agents(
        segments=["%tribe:review\nReview this"],
        local_xprompts={},
        cl_name="test",
        project_file="/test.sase",
        project_name="test",
        is_home_mode=False,
        vcs_ref=None,
    )

    # SASE_AGENT_PLANNED_NAME is now always set when the name is knowable;
    # nothing else (no bead env) should be inferred from a display tag.
    assert mock_spawn.call_args_list[0].kwargs["extra_env"] == {
        "SASE_AGENT_PLANNED_NAME": "0",
    }
