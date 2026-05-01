"""Tests for multi_prompt_launcher module."""

import json
import os
import re
import tempfile
import time
from unittest.mock import MagicMock, patch

import pytest

from sase.agent.multi_prompt_launcher import (
    deserialize_local_xprompts,
    launch_multi_prompt_agents,
    _serialize_local_xprompts,
    _wait_for_agent_naming,
)
from sase.xprompt.models import InputArg, InputType, XPrompt


# --- serialize / deserialize round-trip ---


def test_serialize_deserialize_roundtrip_simple() -> None:
    """Simple xprompt survives serialization round-trip."""
    xprompts = {
        "_review": XPrompt(
            name="_review",
            content="Focus on correctness",
            source_path="user-prompt",
        ),
    }
    path = _serialize_local_xprompts(xprompts)
    try:
        result = deserialize_local_xprompts(path)
        assert "_review" in result
        xp = result["_review"]
        assert xp.name == "_review"
        assert xp.content == "Focus on correctness"
        assert xp.source_path == "user-prompt"
        assert xp.inputs == []
    finally:
        os.unlink(path)


def test_serialize_deserialize_roundtrip_with_inputs() -> None:
    """Xprompt with typed inputs survives round-trip."""
    xprompts = {
        "_greet": XPrompt(
            name="_greet",
            content="Hello {{ name }}",
            inputs=[
                InputArg(name="name", type=InputType.WORD),
                InputArg(name="count", type=InputType.INT, default=3),
            ],
            source_path="/some/path.yml",
        ),
    }
    path = _serialize_local_xprompts(xprompts)
    try:
        result = deserialize_local_xprompts(path)
        xp = result["_greet"]
        assert xp.name == "_greet"
        assert len(xp.inputs) == 2
        assert xp.inputs[0].name == "name"
        assert xp.inputs[0].type == InputType.WORD
        assert xp.inputs[1].name == "count"
        assert xp.inputs[1].type == InputType.INT
        assert xp.inputs[1].default == 3
    finally:
        os.unlink(path)


def test_serialize_deserialize_multiple_xprompts() -> None:
    """Multiple xprompts in a single file."""
    xprompts = {
        "_a": XPrompt(name="_a", content="A"),
        "_b": XPrompt(name="_b", content="B"),
    }
    path = _serialize_local_xprompts(xprompts)
    try:
        result = deserialize_local_xprompts(path)
        assert set(result.keys()) == {"_a", "_b"}
    finally:
        os.unlink(path)


# --- _wait_for_agent_naming ---


def test__wait_for_agent_naming_returns_name() -> None:
    """Returns name when agent_meta.json appears with a name field."""
    with tempfile.TemporaryDirectory() as tmpdir:
        meta_path = os.path.join(tmpdir, "agent_meta.json")
        with open(meta_path, "w") as f:
            json.dump({"pid": 123, "name": "alpha"}, f)

        result = _wait_for_agent_naming(tmpdir, timeout=2)
        assert result == "alpha"


def test__wait_for_agent_naming_returns_none_on_timeout() -> None:
    """Returns None when agent_meta.json never appears."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = _wait_for_agent_naming(tmpdir, timeout=0.5)
        assert result is None


def test__wait_for_agent_naming_handles_missing_file() -> None:
    """Gracefully handles missing agent_meta.json (polls until timeout)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = _wait_for_agent_naming(tmpdir, timeout=0.5)
        assert result is None


def test__wait_for_agent_naming_handles_corrupt_json() -> None:
    """Gracefully handles corrupt JSON."""
    with tempfile.TemporaryDirectory() as tmpdir:
        meta_path = os.path.join(tmpdir, "agent_meta.json")
        with open(meta_path, "w") as f:
            f.write("not valid json{{{")

        result = _wait_for_agent_naming(tmpdir, timeout=0.5)
        assert result is None


def test__wait_for_agent_naming_waits_for_name_field() -> None:
    """Polls until name field appears (not just the file)."""
    import threading

    with tempfile.TemporaryDirectory() as tmpdir:
        meta_path = os.path.join(tmpdir, "agent_meta.json")
        # Write meta without name first.
        with open(meta_path, "w") as f:
            json.dump({"pid": 123}, f)

        def _write_name_later() -> None:
            time.sleep(0.3)
            with open(meta_path, "w") as f:
                json.dump({"pid": 123, "name": "beta"}, f)

        thread = threading.Thread(target=_write_name_later)
        thread.start()

        result = _wait_for_agent_naming(tmpdir, timeout=5)
        thread.join()
        assert result == "beta"


# --- launch_multi_prompt_agents ---


@patch("sase.agent.launcher.spawn_agent_subprocess")
@patch("sase.agent.multi_prompt_launcher._wait_for_agent_naming")
@patch("sase.agent.multi_prompt_launcher.time.sleep")
@patch("sase.core.time.generate_timestamp")
@patch("sase.artifacts.create_artifacts_directory")
@patch("sase.running_field.get_first_available_axe_workspace")
@patch("sase.running_field.get_workspace_directory_for_num")
def test_launch_multi_prompt_sequential_calls(
    mock_ws_dir: MagicMock,
    mock_first_ws: MagicMock,
    mock_create_artifacts: MagicMock,
    mock_timestamp: MagicMock,
    mock_sleep: MagicMock,
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
    mock_sleep.assert_not_called()


@patch("sase.agent.launcher.spawn_agent_subprocess")
@patch("sase.agent.multi_prompt_launcher._wait_for_agent_naming")
@patch("sase.agent.multi_prompt_launcher.time.sleep")
@patch("sase.core.time.generate_timestamp")
@patch("sase.artifacts.create_artifacts_directory")
@patch("sase.running_field.get_first_available_axe_workspace")
@patch("sase.running_field.get_workspace_directory_for_num")
def test_launch_multi_prompt_allocates_unique_timestamps_without_sleep(
    mock_ws_dir: MagicMock,
    mock_first_ws: MagicMock,
    mock_create_artifacts: MagicMock,
    mock_timestamp: MagicMock,
    mock_sleep: MagicMock,
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
    mock_sleep.assert_not_called()


@patch("sase.agent.launcher.spawn_agent_subprocess")
@patch("sase.agent.multi_prompt_launcher._wait_for_agent_naming")
@patch("sase.agent.multi_prompt_launcher.time.sleep")
@patch("sase.core.time.generate_timestamp")
@patch("sase.artifacts.create_artifacts_directory")
@patch("sase.agent.names.get_active_agent_names", return_value=set())
@patch("sase.running_field.get_workspace_directory")
def test_launch_multi_prompt_wait_segments_get_unique_artifacts(
    mock_wait_ws_dir: MagicMock,
    mock_active_names: MagicMock,
    mock_create_artifacts: MagicMock,
    mock_timestamp: MagicMock,
    mock_sleep: MagicMock,
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
    mock_sleep.assert_not_called()


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
        project_file="/test.gp",
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
@patch("sase.running_field.get_first_available_axe_workspace", return_value=100)
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
        project_file="/test.gp",
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
@patch("sase.agent.multi_prompt_launcher.time.sleep")
@patch("sase.core.time.generate_timestamp")
@patch("sase.artifacts.create_artifacts_directory", return_value="/a")
@patch("sase.running_field.get_first_available_axe_workspace")
@patch(
    "sase.running_field.get_workspace_directory_for_num",
)
def test_launch_multi_prompt_with_multi_model_segment(
    mock_ws_dir: MagicMock,
    mock_first_ws: MagicMock,
    mock_create_artifacts: MagicMock,
    mock_timestamp: MagicMock,
    mock_sleep: MagicMock,
    mock_wait: MagicMock,
    mock_spawn: MagicMock,
) -> None:
    """A segment with %model(a,b) spawns one agent per model."""
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
        segments=["%model(opus,sonnet) Do the work", "Review the output"],
        local_xprompts={},
        cl_name="test",
        project_file="/test.gp",
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
    mock_sleep.assert_not_called()


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
        segments=["%n:ag\n%m(opus,sonnet)\nBuild", "%wait\nReview"],
        local_xprompts={},
        cl_name="test",
        project_file="/test.gp",
        project_name="test",
        is_home_mode=False,
        vcs_ref=None,
    )

    assert mock_wait.call_count == 0
    assert mock_create_artifacts.call_count == 0
    assert mock_spawn.call_args_list[2].kwargs["prompt"] == (
        "%wait:ag.cld-sonnet\nReview"
    )


@patch("sase.agent.launcher.spawn_agent_subprocess")
@patch("sase.agent.multi_prompt_launcher._wait_for_agent_naming")
@patch("sase.agent.multi_prompt_launcher.time.sleep")
@patch("sase.core.time.generate_timestamp", return_value="260501_120000")
@patch("sase.artifacts.create_artifacts_directory", return_value="/a")
@patch("sase.running_field.get_first_available_axe_workspace", side_effect=[100, 101])
@patch(
    "sase.running_field.get_workspace_directory_for_num",
    side_effect=[("/ws1", None), ("/ws2", None)],
)
def test_launch_multi_prompt_model_shorthand_uses_local_xprompt_for_naming(
    mock_ws_dir: MagicMock,
    mock_first_ws: MagicMock,
    mock_create_artifacts: MagicMock,
    mock_timestamp: MagicMock,
    mock_sleep: MagicMock,
    mock_wait: MagicMock,
    mock_spawn: MagicMock,
) -> None:
    """Local model shorthand is resolved for names but kept in %model."""
    mock_spawn.return_value = MagicMock(pid=1)
    mock_wait.return_value = "alpha"

    xprompts = {
        "_flash": XPrompt(name="_flash", content="gemini-3-flash-preview"),
    }

    results = launch_multi_prompt_agents(
        segments=["%n:ag\n%m(#_flash,gemini-2.5-flash)\nReview"],
        local_xprompts=xprompts,
        cl_name="test",
        project_file="/test.gp",
        project_name="test",
        is_home_mode=False,
        vcs_ref=None,
    )

    assert len(results) == 2
    prompts = [c.kwargs["prompt"] for c in mock_spawn.call_args_list]
    assert prompts[0] == "%name:ag.gem-flash3\n%model:#_flash\nReview"
    assert prompts[1] == "%name:ag.gem-flash25\n%model:gemini-2.5-flash\nReview"

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
    mock_sleep.assert_not_called()


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
