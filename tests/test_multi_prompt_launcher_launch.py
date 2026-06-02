"""Tests for core multi-prompt launch behavior."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from tests._agent_names_fixtures import make_agent
from sase.agent.multi_prompt_launcher import launch_multi_prompt_agents
from sase.xprompt.models import XPrompt


def _spawn_result_with_planned_name(**kwargs: object):
    from sase.agent.launch_types import AgentLaunchResult

    extra_env = kwargs.get("extra_env") or {}
    planned_name = (
        extra_env.get("SASE_AGENT_PLANNED_NAME")
        if isinstance(extra_env, dict)
        else None
    )
    return AgentLaunchResult(
        pid=1,
        workspace_num=int(kwargs.get("workspace_num", 0)),  # type: ignore[arg-type]
        workspace_dir=str(kwargs.get("workspace_dir", "/ws")),
        output_path="/out.txt",
        timestamp=str(kwargs.get("timestamp", "")),
        project_name=str(kwargs.get("project_name", "")),
        agent_name=planned_name if isinstance(planned_name, str) else None,
    )


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
    assert calls[1].kwargs["extra_env"]["SASE_AGENT_PLANNED_NAME"] == "0.w1"
    assert calls[2].kwargs["extra_env"]["SASE_AGENT_PLANNED_NAME"] == "0.w1.w1"
    assert calls[1].kwargs["prompt"].startswith("%wait:0")
    assert calls[2].kwargs["prompt"].startswith("%wait:0.w1")


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
    mock_spawn.side_effect = _spawn_result_with_planned_name

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
    mock_spawn.side_effect = _spawn_result_with_planned_name

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
    mock_spawn.side_effect = _spawn_result_with_planned_name

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
    mock_spawn.side_effect = _spawn_result_with_planned_name

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

    mock_spawn.side_effect = _spawn_result_with_planned_name
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
    assert mock_spawn.call_args_list[1].kwargs["extra_env"] == {
        "SASE_SHARED": "yes",
        "SASE_BEAD_ID": "sase-x.2",
        "SASE_AGENT_PLANNED_NAME": "first.w1",
    }


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
        segments=["%group:review\nReview this"],
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
