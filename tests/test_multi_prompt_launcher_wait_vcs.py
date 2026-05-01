"""Tests for multi-prompt wait rewriting and VCS metadata."""

import re
from unittest.mock import MagicMock, patch

from sase.agent.multi_prompt_launcher import launch_multi_prompt_agents


@patch("sase.agent.launcher.spawn_agent_subprocess")
@patch("sase.agent.multi_prompt_launcher._wait_for_agent_naming")
@patch("sase.core.time.generate_timestamp", return_value="260501_120000")
@patch("sase.artifacts.create_artifacts_directory", return_value="/a")
@patch("sase.running_field.get_first_available_axe_workspace", side_effect=[100, 101])
@patch("sase.running_field.get_workspace_directory", return_value="/ws/main")
@patch(
    "sase.running_field.get_workspace_directory_for_num",
    side_effect=[("/ws1", None), ("/ws2", None)],
)
def test_launch_multi_prompt_rewrites_bare_wait_to_explicit_previous_name(
    mock_ws_dir: MagicMock,
    mock_wait_ws_dir: MagicMock,
    mock_first_ws: MagicMock,
    mock_create_artifacts: MagicMock,
    mock_timestamp: MagicMock,
    mock_wait: MagicMock,
    mock_spawn: MagicMock,
) -> None:
    """Known explicit predecessor names avoid parent-side naming polling."""
    mock_spawn.return_value = MagicMock(pid=1)

    launch_multi_prompt_agents(
        segments=["%name:builder\nBuild", "%wait\nReview"],
        local_xprompts={},
        cl_name="test",
        project_file="/test.gp",
        project_name="test",
        is_home_mode=False,
        vcs_ref=None,
    )

    assert mock_wait.call_count == 0
    assert mock_create_artifacts.call_count == 0
    assert mock_spawn.call_args_list[1].kwargs["prompt"] == "%wait:builder\nReview"


@patch("sase.agent.launcher.spawn_agent_subprocess")
@patch("sase.agent.multi_prompt_launcher._wait_for_agent_naming")
@patch("sase.core.time.generate_timestamp", return_value="260501_120000")
@patch("sase.artifacts.create_artifacts_directory", return_value="/a")
@patch("sase.agent.names.get_active_agent_names", return_value=set())
@patch("sase.running_field.get_first_available_axe_workspace", side_effect=[100, 101])
@patch("sase.running_field.get_workspace_directory", return_value="/ws/main")
@patch(
    "sase.running_field.get_workspace_directory_for_num",
    side_effect=[("/ws1", None), ("/ws2", None)],
)
def test_launch_multi_prompt_plans_auto_name_for_bare_wait_predecessor(
    mock_ws_dir: MagicMock,
    mock_wait_ws_dir: MagicMock,
    mock_first_ws: MagicMock,
    mock_active_names: MagicMock,
    mock_create_artifacts: MagicMock,
    mock_timestamp: MagicMock,
    mock_wait: MagicMock,
    mock_spawn: MagicMock,
) -> None:
    """Auto-named predecessors are declared by env and used in bare waits."""
    mock_spawn.return_value = MagicMock(pid=1)

    launch_multi_prompt_agents(
        segments=["Build", "%wait\nReview"],
        local_xprompts={},
        cl_name="test",
        project_file="/test.gp",
        project_name="test",
        is_home_mode=False,
        vcs_ref=None,
    )

    assert mock_wait.call_count == 0
    assert mock_create_artifacts.call_count == 0
    assert (
        mock_spawn.call_args_list[0].kwargs["extra_env"]["SASE_AGENT_PLANNED_NAME"]
        == "a"
    )
    assert mock_spawn.call_args_list[1].kwargs["prompt"] == "%wait:a\nReview"


@patch("sase.agent.launcher.spawn_agent_subprocess")
@patch("sase.agent.multi_prompt_launcher._wait_for_agent_naming")
@patch("sase.core.time.generate_timestamp", return_value="260501_120000")
@patch("sase.artifacts.create_artifacts_directory", return_value="/a")
@patch("sase.running_field.get_first_available_axe_workspace", side_effect=[100, 101])
def test_launch_multi_prompt_derives_vcs_metadata_per_segment(
    mock_first_ws: MagicMock,
    mock_create_artifacts: MagicMock,
    mock_timestamp: MagicMock,
    mock_wait: MagicMock,
    mock_spawn: MagicMock,
) -> None:
    """Mixed VCS refs get per-segment CL, workspace, and history metadata."""
    from sase.workspace_provider import ResolvedRef

    def _resolve_ref(ref: str, workflow_type: str) -> ResolvedRef:
        assert workflow_type == "git"
        return ResolvedRef(
            project_file="/projects/sase/sase.gp",
            project_name="sase",
            primary_workspace_dir="/work/sase",
            checkout_target=ref,
        )

    def _workspace_dir(
        workflow_type: str,
        workspace_num: int,
        project_name: str,
        primary_workspace_dir: str,
    ) -> str:
        assert workflow_type == "git"
        assert project_name == "sase"
        return f"{primary_workspace_dir}_{workspace_num}"

    mock_spawn.return_value = MagicMock(pid=1)
    mock_wait.return_value = "alpha"

    with (
        patch(
            "sase.workspace_provider.get_ref_patterns",
            return_value={
                "git": re.compile(r"#git(?::([^\s]+)|\(([^)]*)\))"),
            },
        ),
        patch("sase.workspace_provider.resolve_ref", side_effect=_resolve_ref),
        patch(
            "sase.workspace_provider.get_workspace_directory",
            side_effect=_workspace_dir,
        ),
    ):
        launch_multi_prompt_agents(
            segments=[
                "#git:sase #pr:sase_feature\nstart the ChangeSpec",
                "#git:sase_feature\ncontinue the work",
                "%wait\n#git:sase_feature\nland the epic",
            ],
            local_xprompts={},
            cl_name="sase",
            project_file="/projects/sase/sase.gp",
            project_name="sase",
            is_home_mode=False,
            vcs_ref=("git", "sase"),
        )

    calls = mock_spawn.call_args_list
    assert [c.kwargs["cl_name"] for c in calls] == [
        "sase",
        "sase_feature",
        "sase_feature",
    ]
    assert [c.kwargs["history_sort_key"] for c in calls] == [
        "sase",
        "sase_feature",
        "sase_feature",
    ]
    assert [c.kwargs["vcs_ref"] for c in calls] == [
        ("git", "sase"),
        ("git", "sase_feature"),
        ("git", "sase_feature"),
    ]
    assert [c.kwargs["workspace_num"] for c in calls] == [100, 101, 0]
    assert [c.kwargs["workspace_dir"] for c in calls] == [
        "/work/sase_100",
        "/work/sase_101",
        "/work/sase",
    ]
    assert [c.kwargs["deferred_workspace"] for c in calls] == [False, False, True]

    assert mock_first_ws.call_args_list[0].args == ("/projects/sase/sase.gp",)
    assert mock_first_ws.call_args_list[1].args == ("/projects/sase/sase.gp",)


@patch("sase.agent.launcher.spawn_agent_subprocess")
@patch("sase.agent.multi_prompt_launcher._wait_for_agent_naming")
@patch("sase.core.time.generate_timestamp", return_value="260501_120000")
@patch(
    "sase.artifacts.create_artifacts_directory",
    side_effect=["/artifacts/alpha", "/artifacts/beta"],
)
@patch("sase.running_field.get_first_available_axe_workspace", side_effect=[10, 20, 30])
def test_launch_multi_prompt_naming_wait_uses_previous_segment_project(
    mock_first_ws: MagicMock,
    mock_create_artifacts: MagicMock,
    mock_timestamp: MagicMock,
    mock_wait: MagicMock,
    mock_spawn: MagicMock,
) -> None:
    """Inter-segment naming waits follow each spawned segment's project."""
    from sase.workspace_provider import ResolvedRef

    def _resolve_ref(ref: str, workflow_type: str) -> ResolvedRef:
        assert workflow_type == "git"
        return ResolvedRef(
            project_file=f"/projects/{ref}/{ref}.gp",
            project_name=ref,
            primary_workspace_dir=f"/work/{ref}",
            checkout_target=ref,
        )

    def _workspace_dir(
        workflow_type: str,
        workspace_num: int,
        project_name: str,
        primary_workspace_dir: str,
    ) -> str:
        assert workflow_type == "git"
        return f"{primary_workspace_dir}_{workspace_num}"

    mock_spawn.return_value = MagicMock(pid=1)
    mock_wait.side_effect = ["alpha-agent", "beta-agent"]

    with (
        patch(
            "sase.workspace_provider.get_ref_patterns",
            return_value={
                "git": re.compile(r"#git(?::([^\s]+)|\(([^)]*)\))"),
            },
        ),
        patch("sase.workspace_provider.resolve_ref", side_effect=_resolve_ref),
        patch(
            "sase.workspace_provider.get_workspace_directory",
            side_effect=_workspace_dir,
        ),
    ):
        launch_multi_prompt_agents(
            segments=[
                "#git:alpha first",
                "%wait\n#git:beta second",
                "%wait\n#git:gamma third",
            ],
            local_xprompts={},
            cl_name="base",
            project_file="/projects/base/base.gp",
            project_name="base",
            is_home_mode=False,
            vcs_ref=None,
        )

    assert [c.kwargs["project_name"] for c in mock_spawn.call_args_list] == [
        "alpha",
        "beta",
        "gamma",
    ]
    assert [c.kwargs["workspace_dir"] for c in mock_spawn.call_args_list] == [
        "/work/alpha_10",
        "/work/beta",
        "/work/gamma",
    ]
    assert [c.kwargs["workspace_num"] for c in mock_spawn.call_args_list] == [
        10,
        0,
        0,
    ]
    assert [c.kwargs for c in mock_create_artifacts.call_args_list] == [
        {"project_name": "alpha", "timestamp": "260501_120000"},
        {"project_name": "beta", "timestamp": "260501_120001"},
    ]
    assert [c.args for c in mock_create_artifacts.call_args_list] == [
        ("ace-run",),
        ("ace-run",),
    ]
    assert [c.args for c in mock_wait.call_args_list] == [
        ("/artifacts/alpha",),
        ("/artifacts/beta",),
    ]
    assert mock_spawn.call_args_list[1].kwargs["prompt"].startswith("%wait:alpha-agent")
    assert mock_spawn.call_args_list[2].kwargs["prompt"].startswith("%wait:beta-agent")
