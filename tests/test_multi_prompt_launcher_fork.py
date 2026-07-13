"""Tests for multi-prompt bare #fork rewriting."""

from pathlib import Path
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
    "sase.running_field.claim_next_axe_workspace",
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
        segments=["%name:builder\nBuild", "#fork\nReview"],
        local_xprompts={},
        cl_name="test",
        project_file="/test.sase",
        project_name="test",
        is_home_mode=False,
        vcs_ref=None,
    )

    assert mock_wait.call_count == 0
    assert mock_create_artifacts.call_count == 0
    assert mock_spawn.call_args_list[1].kwargs["prompt"] == "#fork:builder\nReview"


@patch("sase.agent.launcher.spawn_agent_subprocess")
@patch("sase.agent.multi_prompt_launcher._wait_for_agent_naming")
@patch("sase.core.time.generate_timestamp", return_value="260501_120000")
@patch("sase.artifacts.create_artifacts_directory", return_value="/a")
@patch("sase.agent.names.get_reserved_agent_names", return_value=set())
@patch("sase.running_field.claim_next_axe_workspace", side_effect=[100, 101])
@patch("sase.running_field.get_workspace_directory", return_value="/ws/main")
@patch(
    "sase.running_field.get_workspace_directory_for_num",
    side_effect=[("/ws1", None), ("/ws2", None)],
)
def test_launch_multi_prompt_plans_auto_name_for_bare_resume_predecessor(
    mock_ws_dir: MagicMock,
    mock_wait_ws_dir: MagicMock,
    mock_first_ws: MagicMock,
    mock_reserved_names: MagicMock,
    mock_create_artifacts: MagicMock,
    mock_timestamp: MagicMock,
    mock_wait: MagicMock,
    mock_spawn: MagicMock,
) -> None:
    """Auto-named predecessors are declared by env and used in bare resumes."""
    mock_spawn.return_value = MagicMock(pid=1)

    launch_multi_prompt_agents(
        segments=["Build", "#fork\nReview"],
        local_xprompts={},
        cl_name="test",
        project_file="/test.sase",
        project_name="test",
        is_home_mode=False,
        vcs_ref=None,
    )

    assert mock_wait.call_count == 0
    assert mock_create_artifacts.call_count == 0
    assert (
        mock_spawn.call_args_list[0].kwargs["extra_env"]["SASE_AGENT_PLANNED_NAME"]
        == "0"
    )
    assert mock_spawn.call_args_list[1].kwargs["prompt"] == "#fork:0\nReview"


@patch("sase.agent.launcher.spawn_agent_subprocess")
@patch("sase.agent.multi_prompt_launcher._wait_for_agent_naming")
@patch("sase.core.time.generate_timestamp", return_value="260501_120000")
@patch("sase.artifacts.create_artifacts_directory", return_value="/artifacts/alpha")
@patch("sase.running_field.claim_next_axe_workspace", side_effect=[100, 101])
@patch("sase.running_field.get_workspace_directory", return_value="/ws/main")
@patch(
    "sase.running_field.get_workspace_directory_for_num",
    side_effect=[("/ws1", None), ("/ws2", None)],
)
def test_launch_multi_prompt_polls_for_unplanned_resume_predecessor(
    mock_ws_dir: MagicMock,
    mock_wait_ws_dir: MagicMock,
    mock_first_ws: MagicMock,
    mock_create_artifacts: MagicMock,
    mock_timestamp: MagicMock,
    mock_wait: MagicMock,
    mock_spawn: MagicMock,
) -> None:
    """Xprompt predecessors are polled before a following bare #fork launches."""
    mock_spawn.return_value = MagicMock(pid=1)
    mock_wait.return_value = "polled-builder"

    launch_multi_prompt_agents(
        segments=["#_prep\nBuild", "#fork\nReview"],
        local_xprompts={"_prep": XPrompt(name="_prep", content="Prep")},
        cl_name="test",
        project_file="/test.sase",
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
        "#fork:polled-builder\nReview"
    )
    assert mock_spawn.call_args_list[1].kwargs["workspace_num"] == 0
    assert mock_spawn.call_args_list[1].kwargs["workspace_dir"] == "/ws/main"
    assert mock_spawn.call_args_list[1].kwargs["deferred_workspace"] is True
    mock_wait_ws_dir.assert_called_once_with("test", 1)


@patch("sase.agent.launcher.spawn_agent_subprocess")
@patch("sase.agent.multi_prompt_launcher._wait_for_agent_naming")
@patch("sase.core.time.generate_timestamp", return_value="260501_120000")
@patch("sase.artifacts.create_artifacts_directory", return_value="/a")
@patch("sase.running_field.claim_next_axe_workspace", side_effect=[100, 101])
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
    """The first segment keeps the global bare #fork behavior."""
    mock_spawn.return_value = MagicMock(pid=1)

    with patch(
        "sase.xprompt.processor.process_xprompt_references",
        return_value="#fork\nContinue",
    ):
        launch_multi_prompt_agents(
            segments=["#fork\nContinue", "%name:next\nNext"],
            local_xprompts={},
            cl_name="test",
            project_file="/test.sase",
            project_name="test",
            is_home_mode=False,
            vcs_ref=None,
        )

    assert mock_spawn.call_args_list[0].kwargs["prompt"] == "#fork\nContinue"


def test_bare_resume_rewrite_ignores_explicit_fenced_and_disabled_regions() -> None:
    """Only top-level bare #fork references are rewritten."""
    prompt = (
        "#fork\n"
        "#fork:explicit\n"
        "#fork(explicit)\n"
        "#fork_by_chat:/tmp/chat.md\n"
        "```\n#fork\n```\n"
        "%xprompts_enabled:false\n#fork\n%xprompts_enabled:true\n"
    )

    assert _has_bare_resume_reference(prompt) is True
    assert _rewrite_bare_resume_references(prompt, "builder") == (
        "#fork:builder\n"
        "#fork:explicit\n"
        "#fork(explicit)\n"
        "#fork_by_chat:/tmp/chat.md\n"
        "```\n#fork\n```\n"
        "%xprompts_enabled:false\n#fork\n%xprompts_enabled:true\n"
    )


@patch("sase.agent.launcher.spawn_agent_subprocess")
@patch("sase.agent.multi_prompt_launcher._wait_for_agent_naming")
@patch("sase.core.time.generate_timestamp", return_value="260501_120000")
@patch("sase.artifacts.create_artifacts_directory", return_value="/a")
@patch(
    "sase.running_field.claim_next_axe_workspace",
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
        segments=["%n:ag\n%alt(sec=Build security,perf=Build perf)", "#fork\nReview"],
        local_xprompts={},
        cl_name="test",
        project_file="/test.sase",
        project_name="test",
        is_home_mode=False,
        vcs_ref=None,
    )

    assert mock_wait.call_count == 0
    assert mock_create_artifacts.call_count == 0
    assert mock_spawn.call_args_list[2].kwargs["prompt"] == "#fork:ag.perf\nReview"


@patch("sase.agent.launcher.spawn_agent_subprocess")
@patch("sase.agent.multi_prompt_launcher._wait_for_agent_naming")
@patch("sase.core.time.generate_timestamp", return_value="260501_120000")
@patch("sase.artifacts.create_artifacts_directory", return_value="/a")
@patch("sase.running_field.claim_next_axe_workspace", side_effect=[100, 101])
@patch("sase.running_field.get_workspace_directory", return_value="/ws/main")
@patch(
    "sase.running_field.get_workspace_directory_for_num",
    side_effect=[("/ws1", None), ("/ws3", None)],
)
def test_launch_multi_prompt_bare_wait_and_resume_plan_fork_name(
    mock_ws_dir: MagicMock,
    mock_wait_ws_dir: MagicMock,
    mock_first_ws: MagicMock,
    mock_create_artifacts: MagicMock,
    mock_timestamp: MagicMock,
    mock_wait: MagicMock,
    mock_spawn: MagicMock,
    tmp_path: Path,
) -> None:
    """A segment with bare %w and #fork follows the predecessor with an .f- name."""
    mock_spawn.return_value = MagicMock(pid=1)

    with patch.object(Path, "home", return_value=tmp_path):
        launch_multi_prompt_agents(
            segments=[
                "%name:builder\nBuild",
                "%w\n#fork\nReview",
                "#fork\nFollow up",
            ],
            local_xprompts={},
            cl_name="test",
            project_file="/test.sase",
            project_name="test",
            is_home_mode=False,
            vcs_ref=None,
        )

    assert mock_wait.call_count == 0
    assert mock_create_artifacts.call_count == 0
    assert mock_spawn.call_args_list[1].kwargs["prompt"] == (
        "%w:builder\n#fork:builder\nReview"
    )
    assert (
        mock_spawn.call_args_list[1].kwargs["extra_env"]["SASE_AGENT_PLANNED_NAME"]
        == "builder.f0"
    )
    assert mock_spawn.call_args_list[2].kwargs["prompt"] == (
        "#fork:builder.f0\nFollow up"
    )
