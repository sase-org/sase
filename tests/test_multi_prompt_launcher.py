"""Tests for multi_prompt_launcher module."""

import json
import os
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
    """Verifies sequential spawn calls with naming-wait between them."""
    mock_first_ws.return_value = 100
    mock_ws_dir.return_value = ("/workspace/100", None)
    mock_timestamp.side_effect = ["ts1", "ts2", "ts3"]
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
    # naming-wait called between launches (not after last one)
    assert mock_wait.call_count == 2


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
    mock_timestamp.side_effect = ["ts_a", "ts_b"]
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
    assert calls[0].kwargs["timestamp"] == "ts_a"
    assert calls[1].kwargs["timestamp"] == "ts_b"
    assert calls[0].kwargs["workspace_num"] == 100
    assert calls[1].kwargs["workspace_num"] == 101


@patch("sase.agent.launcher.spawn_agent_subprocess")
@patch("sase.agent.multi_prompt_launcher._wait_for_agent_naming")
@patch("sase.core.time.generate_timestamp", side_effect=["ts1", "ts2"])
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
@patch("sase.core.time.generate_timestamp", return_value="ts1")
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
@patch("sase.artifacts.create_artifacts_directory", return_value="/a")
@patch("sase.running_field.get_first_available_axe_workspace")
@patch(
    "sase.running_field.get_workspace_directory_for_num",
)
def test_launch_multi_prompt_with_multi_model_segment(
    mock_ws_dir: MagicMock,
    mock_first_ws: MagicMock,
    mock_create_artifacts: MagicMock,
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

    # Naming-wait should fire between segments (not between model variants).
    assert mock_wait.call_count == 1
