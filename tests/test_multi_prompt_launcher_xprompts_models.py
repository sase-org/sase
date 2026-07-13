"""Tests for multi-prompt local xprompt and model expansion behavior."""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.agent.multi_prompt_launcher import (
    deserialize_local_xprompts,
    launch_multi_prompt_agents,
)
from sase.xprompt.models import XPrompt
from tests._agent_names_fixtures import make_agent
from tests._multi_prompt_launcher_launch_helpers import spawn_result_with_planned_name


@patch("sase.agent.launcher.spawn_agent_subprocess")
@patch("sase.agent.multi_prompt_launcher._wait_for_agent_naming")
@patch("sase.core.time.generate_timestamp", return_value="260501_120000")
@patch("sase.artifacts.create_artifacts_directory", return_value="/a")
@patch("sase.running_field.claim_next_axe_workspace", side_effect=[100, 101])
@patch(
    "sase.running_field.get_workspace_directory_for_num",
    side_effect=[("/ws1", None), ("/ws2", None)],
)
def test_launch_multi_prompt_passes_segment_local_xprompts_file(
    mock_ws_dir: MagicMock,
    mock_first_ws: MagicMock,
    mock_create_artifacts: MagicMock,
    mock_timestamp: MagicMock,
    mock_wait: MagicMock,
    mock_spawn: MagicMock,
) -> None:
    """Only segments that reference local xprompts get a temp xprompt file."""
    mock_spawn.return_value = MagicMock(pid=1)
    mock_wait.return_value = "alpha"

    xprompts = {
        "_review": XPrompt(name="_review", content="be thorough"),
    }

    launch_multi_prompt_agents(
        segments=["seg1", "seg2 #_review"],
        local_xprompts=xprompts,
        cl_name="test",
        project_file="/test.sase",
        project_name="test",
        is_home_mode=False,
        vcs_ref=None,
    )

    first_path = mock_spawn.call_args_list[0].kwargs["local_xprompts_file"]
    second_path = mock_spawn.call_args_list[1].kwargs["local_xprompts_file"]

    assert first_path is None
    assert second_path is not None
    try:
        loaded = deserialize_local_xprompts(second_path)
        assert set(loaded) == {"_review"}
    finally:
        if os.path.exists(second_path):
            os.unlink(second_path)


@patch("sase.agent.launcher.spawn_agent_subprocess")
@patch("sase.agent.multi_prompt_launcher._wait_for_agent_naming")
@patch("sase.core.time.generate_timestamp", return_value="260501_120000")
@patch("sase.artifacts.create_artifacts_directory", return_value="/a")
@patch("sase.running_field.claim_next_axe_workspace", return_value=100)
@patch(
    "sase.running_field.get_workspace_directory_for_num",
    return_value=("/ws", None),
)
def test_launch_multi_prompt_includes_transitive_local_xprompts(
    mock_ws_dir: MagicMock,
    mock_first_ws: MagicMock,
    mock_create_artifacts: MagicMock,
    mock_timestamp: MagicMock,
    mock_wait: MagicMock,
    mock_spawn: MagicMock,
) -> None:
    """Segment-local xprompts include transitive local-xprompt dependencies."""
    mock_spawn.return_value = MagicMock(pid=1)
    mock_wait.return_value = "alpha"

    xprompts = {
        "_inner": XPrompt(name="_inner", content="inner"),
        "_outer": XPrompt(name="_outer", content="use #_inner"),
    }

    launch_multi_prompt_agents(
        segments=["work #_outer"],
        local_xprompts=xprompts,
        cl_name="test",
        project_file="/test.sase",
        project_name="test",
        is_home_mode=False,
        vcs_ref=None,
    )

    path = mock_spawn.call_args.kwargs["local_xprompts_file"]
    assert path is not None
    try:
        loaded = deserialize_local_xprompts(path)
        assert set(loaded) == {"_inner", "_outer"}
    finally:
        if os.path.exists(path):
            os.unlink(path)


@patch("sase.agent.launcher.spawn_agent_subprocess")
@patch("sase.agent.multi_prompt_launcher._wait_for_agent_naming")
@patch("sase.core.time.generate_timestamp")
@patch("sase.artifacts.create_artifacts_directory", return_value="/a")
@patch("sase.running_field.claim_next_axe_workspace")
@patch(
    "sase.running_field.get_workspace_directory_for_num",
)
def test_launch_multi_prompt_with_multi_model_segment(
    mock_ws_dir: MagicMock,
    mock_first_ws: MagicMock,
    mock_create_artifacts: MagicMock,
    mock_timestamp: MagicMock,
    mock_wait: MagicMock,
    mock_spawn: MagicMock,
) -> None:
    """A segment with explicit model branches spawns one agent per model."""
    mock_first_ws.side_effect = [100, 101, 102]
    mock_ws_dir.side_effect = [
        ("/ws/100", None),
        ("/ws/101", None),
        ("/ws/102", None),
    ]
    mock_timestamp.return_value = "260501_120000"
    mock_wait.return_value = "alpha"
    mock_spawn.return_value = MagicMock(pid=1)

    results = launch_multi_prompt_agents(
        segments=[
            "%{%model:opus | %model:sonnet} Do the work",
            "Review the output",
        ],
        local_xprompts={},
        cl_name="test",
        project_file="/test.sase",
        project_name="test",
        is_home_mode=False,
        vcs_ref=None,
    )

    # Segment 1 produces 2 agents (one per model), segment 2 produces 1.
    assert len(results) == 3
    assert mock_spawn.call_count == 3

    prompts = [c.kwargs["prompt"] for c in mock_spawn.call_args_list]
    assert "%model:opus" in prompts[0]
    assert "%model:sonnet" in prompts[1]
    assert prompts[2] == "Review the output"
    assert [c.kwargs["timestamp"] for c in mock_spawn.call_args_list] == [
        "260501_120000",
        "260501_120001",
        "260501_120002",
    ]

    assert mock_wait.call_count == 0
    assert mock_create_artifacts.call_count == 0


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
def test_launch_multi_prompt_waits_on_last_multi_model_generated_name(
    mock_ws_dir: MagicMock,
    mock_wait_ws_dir: MagicMock,
    mock_first_ws: MagicMock,
    mock_create_artifacts: MagicMock,
    mock_timestamp: MagicMock,
    mock_wait: MagicMock,
    mock_spawn: MagicMock,
) -> None:
    """Multi-model generated names are available for following bare waits."""
    mock_spawn.return_value = MagicMock(pid=1)

    launch_multi_prompt_agents(
        segments=["%n:ag\n%{%model:opus | %model:sonnet}\nBuild", "%wait\nReview"],
        local_xprompts={},
        cl_name="test",
        project_file="/test.sase",
        project_name="test",
        is_home_mode=False,
        vcs_ref=None,
    )

    assert mock_wait.call_count == 0
    assert mock_create_artifacts.call_count == 0
    assert mock_spawn.call_args_list[2].kwargs["prompt"] == (
        "%wait:ag.cld_sonnet\nReview"
    )


@patch("sase.agent.launcher.spawn_agent_subprocess")
@patch("sase.agent.multi_prompt_launcher._wait_for_agent_naming")
@patch("sase.core.time.generate_timestamp", return_value="260501_120000")
@patch("sase.artifacts.create_artifacts_directory", return_value="/a")
@patch("sase.running_field.claim_next_axe_workspace", side_effect=[100, 101, 102])
@patch("sase.running_field.get_workspace_directory", return_value="/ws/main")
@patch(
    "sase.running_field.get_workspace_directory_for_num",
    side_effect=[("/ws1", None), ("/ws2", None), ("/ws3", None)],
)
def test_launch_multi_prompt_generated_model_fanout_allocates_grouped_names(
    mock_ws_dir: MagicMock,
    mock_wait_ws_dir: MagicMock,
    mock_first_ws: MagicMock,
    mock_create_artifacts: MagicMock,
    mock_timestamp: MagicMock,
    mock_wait: MagicMock,
    mock_spawn: MagicMock,
    tmp_path: Path,
) -> None:
    """Generated model fan-out templates share one allocated token."""
    mock_spawn.side_effect = spawn_result_with_planned_name

    with patch.object(Path, "home", return_value=tmp_path):
        results = launch_multi_prompt_agents(
            segments=["%{%model:opus | %model:gpt-5.6-sol}\nBuild", "%wait\nReview"],
            local_xprompts={},
            cl_name="test",
            project_file="/test.sase",
            project_name="test",
            is_home_mode=False,
            vcs_ref=None,
        )

    assert [result.agent_name for result in results] == [
        "0.cld",
        "0.cdx",
        "0.cdx.w0",
    ]
    prompts = [c.kwargs["prompt"] for c in mock_spawn.call_args_list]
    assert prompts == [
        "%name:@.cld\n%model:opus\nBuild",
        "%name:@.cdx\n%model:gpt-5.6-sol\nBuild",
        "%wait:0.cdx\nReview",
    ]
    envs = [c.kwargs["extra_env"] for c in mock_spawn.call_args_list]
    assert [env["SASE_AGENT_PLANNED_NAME"] for env in envs] == [
        "0.cld",
        "0.cdx",
        "0.cdx.w0",
    ]
    assert [env.get("SASE_AGENT_GENERATED_NAME") for env in envs] == [
        "1",
        "1",
        None,
    ]
    assert mock_wait.call_count == 0
    assert mock_create_artifacts.call_count == 0


@patch("sase.agent.launcher.spawn_agent_subprocess")
@patch("sase.agent.multi_prompt_launcher._wait_for_agent_naming")
@patch("sase.core.time.generate_timestamp", return_value="260501_120000")
@patch("sase.artifacts.create_artifacts_directory", return_value="/a")
@patch("sase.running_field.claim_next_axe_workspace", side_effect=[100, 101])
@patch(
    "sase.running_field.get_workspace_directory_for_num",
    side_effect=[("/ws1", None), ("/ws2", None)],
)
@pytest.mark.parametrize("existing_name", ["0", "0.cld", "0.cdx", "0.any"])
def test_launch_multi_prompt_generated_model_fanout_skips_colliding_token(
    mock_ws_dir: MagicMock,
    mock_first_ws: MagicMock,
    mock_create_artifacts: MagicMock,
    mock_timestamp: MagicMock,
    mock_wait: MagicMock,
    mock_spawn: MagicMock,
    tmp_path: Path,
    existing_name: str,
) -> None:
    """A collision in one fan-out sibling advances the whole generated group."""
    make_agent(tmp_path, "proj", "existing", existing_name, done=True)
    mock_spawn.side_effect = spawn_result_with_planned_name

    with patch.object(Path, "home", return_value=tmp_path):
        results = launch_multi_prompt_agents(
            segments=["%{%model:opus | %model:gpt-5.6-sol}\nBuild"],
            local_xprompts={},
            cl_name="test",
            project_file="/test.sase",
            project_name="test",
            is_home_mode=False,
            vcs_ref=None,
        )

    assert [result.agent_name for result in results] == ["1.cld", "1.cdx"]


@patch("sase.agent.launcher.spawn_agent_subprocess")
@patch("sase.agent.multi_prompt_launcher._wait_for_agent_naming")
@patch("sase.core.time.generate_timestamp", return_value="260501_120000")
@patch("sase.artifacts.create_artifacts_directory", return_value="/a")
@patch("sase.running_field.claim_next_axe_workspace", side_effect=[100, 101])
@patch(
    "sase.running_field.get_workspace_directory_for_num",
    side_effect=[("/ws1", None), ("/ws2", None)],
)
def test_launch_multi_prompt_explicit_template_model_fanout_groups_token(
    mock_ws_dir: MagicMock,
    mock_first_ws: MagicMock,
    mock_create_artifacts: MagicMock,
    mock_timestamp: MagicMock,
    mock_wait: MagicMock,
    mock_spawn: MagicMock,
    tmp_path: Path,
) -> None:
    """An explicit template base fans out with one shared template token."""
    mock_spawn.side_effect = spawn_result_with_planned_name

    with patch.object(Path, "home", return_value=tmp_path):
        results = launch_multi_prompt_agents(
            segments=["%name:review-@\n%{%model:opus | %model:gpt-5.6-sol}\nBuild"],
            local_xprompts={},
            cl_name="test",
            project_file="/test.sase",
            project_name="test",
            is_home_mode=False,
            vcs_ref=None,
        )

    assert [result.agent_name for result in results] == [
        "review-0.cld",
        "review-0.cdx",
    ]
    prompts = [c.kwargs["prompt"] for c in mock_spawn.call_args_list]
    assert prompts == [
        "%name:review-@.cld\n%model:opus\nBuild",
        "%name:review-@.cdx\n%model:gpt-5.6-sol\nBuild",
    ]
    assert [
        c.kwargs["extra_env"]["SASE_AGENT_PLANNED_NAME"]
        for c in mock_spawn.call_args_list
    ] == ["review-0.cld", "review-0.cdx"]
    assert all(
        "SASE_AGENT_GENERATED_NAME" not in c.kwargs["extra_env"]
        for c in mock_spawn.call_args_list
    )


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
def test_launch_multi_prompt_waits_on_last_alt_generated_name(
    mock_ws_dir: MagicMock,
    mock_wait_ws_dir: MagicMock,
    mock_first_ws: MagicMock,
    mock_create_artifacts: MagicMock,
    mock_timestamp: MagicMock,
    mock_wait: MagicMock,
    mock_spawn: MagicMock,
) -> None:
    """Pure %alt generated names are available for following bare waits."""
    mock_spawn.return_value = MagicMock(pid=1)

    launch_multi_prompt_agents(
        segments=["%n:ag\n%alt(sec=Build security,perf=Build perf)", "%wait\nReview"],
        local_xprompts={},
        cl_name="test",
        project_file="/test.sase",
        project_name="test",
        is_home_mode=False,
        vcs_ref=None,
    )

    assert mock_wait.call_count == 0
    assert mock_create_artifacts.call_count == 0
    prompts = [c.kwargs["prompt"] for c in mock_spawn.call_args_list]
    assert prompts == [
        "%name:ag.sec\nBuild security",
        "%name:ag.perf\nBuild perf",
        "%wait:ag.perf\nReview",
    ]


@patch("sase.agent.launcher.spawn_agent_subprocess")
@patch("sase.agent.multi_prompt_launcher._wait_for_agent_naming")
@patch("sase.core.time.generate_timestamp", return_value="260501_120000")
@patch("sase.artifacts.create_artifacts_directory", return_value="/a")
@patch("sase.running_field.claim_next_axe_workspace", side_effect=[100, 101])
@patch(
    "sase.running_field.get_workspace_directory_for_num",
    side_effect=[("/ws1", None), ("/ws2", None)],
)
def test_launch_multi_prompt_model_shorthand_uses_local_xprompt_for_naming(
    mock_ws_dir: MagicMock,
    mock_first_ws: MagicMock,
    mock_create_artifacts: MagicMock,
    mock_timestamp: MagicMock,
    mock_wait: MagicMock,
    mock_spawn: MagicMock,
) -> None:
    """Local model shorthand is resolved for names but kept in %model."""
    mock_spawn.return_value = MagicMock(pid=1)
    mock_wait.return_value = "alpha"

    xprompts = {
        "_flash": XPrompt(name="_flash", content="gpt-5.6-sol"),
    }

    results = launch_multi_prompt_agents(
        segments=["%n:ag\n%{%model:#_flash | %model:gpt-5.3-codex}\nReview"],
        local_xprompts=xprompts,
        cl_name="test",
        project_file="/test.sase",
        project_name="test",
        is_home_mode=False,
        vcs_ref=None,
    )

    assert len(results) == 2
    prompts = [c.kwargs["prompt"] for c in mock_spawn.call_args_list]
    assert prompts[0] == "%name:ag.cdx_gpt56sol\n%model:#_flash\nReview"
    assert prompts[1] == "%name:ag.cdx_gpt53\n%model:gpt-5.3-codex\nReview"

    local_xprompt_files = [
        c.kwargs["local_xprompts_file"] for c in mock_spawn.call_args_list
    ]
    assert all(path is not None for path in local_xprompt_files)
    for path in local_xprompt_files:
        try:
            loaded = deserialize_local_xprompts(path)
            assert set(loaded) == {"_flash"}
        finally:
            if path and os.path.exists(path):
                os.unlink(path)
