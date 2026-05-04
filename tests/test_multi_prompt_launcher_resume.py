"""Tests for multi-prompt bare #resume rewriting."""

from unittest.mock import MagicMock, patch

from sase.agent.multi_prompt_launcher import (
    _has_bare_resume_reference,
    _rewrite_bare_resume_references,
    launch_multi_prompt_agents,
)
from sase.xprompt.models import XPrompt


@patch("sase.agent.launcher.spawn_agent_subprocess")
@patch("sase.agent.multi_prompt_launcher._wait_for_agent_naming")
@patch("sase.core.time.generate_timestamp", return_value="260501_120000")
@patch("sase.artifacts.create_artifacts_directory", return_value="/a")
@patch(
    "sase.running_field.get_first_available_axe_workspace",
    side_effect=[100, 101, 102],
)
@patch("sase.running_field.get_workspace_directory", return_value="/ws/main")
@patch(
    "sase.running_field.get_workspace_directory_for_num",
    side_effect=[("/ws1", None), ("/ws2", None), ("/ws3", None)],
)
def test_launch_multi_prompt_rewrites_bare_resume_to_explicit_previous_name(
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
        segments=["%name:builder\nBuild", "#resume\nReview"],
        local_xprompts={},
        cl_name="test",
        project_file="/test.gp",
        project_name="test",
        is_home_mode=False,
        vcs_ref=None,
    )

    assert mock_wait.call_count == 0
    assert mock_create_artifacts.call_count == 0
    assert mock_spawn.call_args_list[1].kwargs["prompt"] == "#resume:builder\nReview"


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
def test_launch_multi_prompt_plans_auto_name_for_bare_resume_predecessor(
    mock_ws_dir: MagicMock,
    mock_wait_ws_dir: MagicMock,
    mock_first_ws: MagicMock,
    mock_active_names: MagicMock,
    mock_create_artifacts: MagicMock,
    mock_timestamp: MagicMock,
    mock_wait: MagicMock,
    mock_spawn: MagicMock,
) -> None:
    """Auto-named predecessors are declared by env and used in bare resumes."""
    mock_spawn.return_value = MagicMock(pid=1)

    launch_multi_prompt_agents(
        segments=["Build", "#resume\nReview"],
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
    assert mock_spawn.call_args_list[1].kwargs["prompt"] == "#resume:a\nReview"


@patch("sase.agent.launcher.spawn_agent_subprocess")
@patch("sase.agent.multi_prompt_launcher._wait_for_agent_naming")
@patch("sase.core.time.generate_timestamp", return_value="260501_120000")
@patch("sase.artifacts.create_artifacts_directory", return_value="/artifacts/alpha")
@patch("sase.running_field.get_first_available_axe_workspace", side_effect=[100, 101])
@patch(
    "sase.running_field.get_workspace_directory_for_num",
    side_effect=[("/ws1", None), ("/ws2", None)],
)
def test_launch_multi_prompt_polls_for_unplanned_resume_predecessor(
    mock_ws_dir: MagicMock,
    mock_first_ws: MagicMock,
    mock_create_artifacts: MagicMock,
    mock_timestamp: MagicMock,
    mock_wait: MagicMock,
    mock_spawn: MagicMock,
) -> None:
    """Xprompt predecessors are polled before a following bare #resume launches."""
    mock_spawn.return_value = MagicMock(pid=1)
    mock_wait.return_value = "polled-builder"

    launch_multi_prompt_agents(
        segments=["#_prep\nBuild", "#resume\nReview"],
        local_xprompts={"_prep": XPrompt(name="_prep", content="Prep")},
        cl_name="test",
        project_file="/test.gp",
        project_name="test",
        is_home_mode=False,
        vcs_ref=None,
    )

    assert mock_create_artifacts.call_args.args == ("ace-run",)
    assert mock_create_artifacts.call_args.kwargs == {
        "project_name": "test",
        "timestamp": "260501_120000",
    }
    assert mock_wait.call_args.args == ("/artifacts/alpha",)
    assert mock_spawn.call_args_list[1].kwargs["prompt"] == (
        "#resume:polled-builder\nReview"
    )


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
def test_launch_multi_prompt_leaves_first_segment_bare_resume_unrewritten(
    mock_ws_dir: MagicMock,
    mock_wait_ws_dir: MagicMock,
    mock_first_ws: MagicMock,
    mock_create_artifacts: MagicMock,
    mock_timestamp: MagicMock,
    mock_wait: MagicMock,
    mock_spawn: MagicMock,
) -> None:
    """The first segment keeps the global bare #resume behavior."""
    mock_spawn.return_value = MagicMock(pid=1)

    with patch(
        "sase.xprompt.processor.process_xprompt_references",
        return_value="#resume\nContinue",
    ):
        launch_multi_prompt_agents(
            segments=["#resume\nContinue", "%name:next\nNext"],
            local_xprompts={},
            cl_name="test",
            project_file="/test.gp",
            project_name="test",
            is_home_mode=False,
            vcs_ref=None,
        )

    assert mock_spawn.call_args_list[0].kwargs["prompt"] == "#resume\nContinue"


def test_bare_resume_rewrite_ignores_explicit_fenced_and_disabled_regions() -> None:
    """Only top-level bare #resume references are rewritten."""
    prompt = (
        "#resume\n"
        "#resume:explicit\n"
        "#resume(explicit)\n"
        "#resume_by_chat:/tmp/chat.md\n"
        "```\n#resume\n```\n"
        "%xprompts_enabled:false\n#resume\n%xprompts_enabled:true\n"
    )

    assert _has_bare_resume_reference(prompt) is True
    assert _rewrite_bare_resume_references(prompt, "builder") == (
        "#resume:builder\n"
        "#resume:explicit\n"
        "#resume(explicit)\n"
        "#resume_by_chat:/tmp/chat.md\n"
        "```\n#resume\n```\n"
        "%xprompts_enabled:false\n#resume\n%xprompts_enabled:true\n"
    )


@patch("sase.agent.launcher.spawn_agent_subprocess")
@patch("sase.agent.multi_prompt_launcher._wait_for_agent_naming")
@patch("sase.core.time.generate_timestamp", return_value="260501_120000")
@patch("sase.artifacts.create_artifacts_directory", return_value="/a")
@patch(
    "sase.running_field.get_first_available_axe_workspace",
    side_effect=[100, 101, 102],
)
@patch("sase.running_field.get_workspace_directory", return_value="/ws/main")
@patch(
    "sase.running_field.get_workspace_directory_for_num",
    side_effect=[("/ws1", None), ("/ws2", None), ("/ws3", None)],
)
def test_launch_multi_prompt_resume_uses_last_alt_generated_name(
    mock_ws_dir: MagicMock,
    mock_wait_ws_dir: MagicMock,
    mock_first_ws: MagicMock,
    mock_create_artifacts: MagicMock,
    mock_timestamp: MagicMock,
    mock_wait: MagicMock,
    mock_spawn: MagicMock,
) -> None:
    """Fanout generated names are available for following bare resumes."""
    mock_spawn.return_value = MagicMock(pid=1)

    launch_multi_prompt_agents(
        segments=["%n:ag\n%alt(sec=Build security,perf=Build perf)", "#resume\nReview"],
        local_xprompts={},
        cl_name="test",
        project_file="/test.gp",
        project_name="test",
        is_home_mode=False,
        vcs_ref=None,
    )

    assert mock_wait.call_count == 0
    assert mock_create_artifacts.call_count == 0
    assert mock_spawn.call_args_list[2].kwargs["prompt"] == "#resume:ag.perf\nReview"
