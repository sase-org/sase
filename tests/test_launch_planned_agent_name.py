"""Tests for parent-side agent name planning on AgentLaunchResult.

These tests cover the contract that ``launch_agents_from_cwd()`` returns
results whose ``agent_name`` is populated synchronously when the name is
knowable in the parent (explicit ``%name:`` or unambiguous auto-name),
without polling ``agent_meta.json``.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tests._cd_launch_resolution_helpers import patch_cd_metadata


def _make_spawn_capture() -> MagicMock:
    """Make a spawn mock that echoes the planned name onto the result."""
    from sase.agent.launch_types import AgentLaunchResult

    def fake_spawn(**kwargs: object) -> AgentLaunchResult:
        extra_env = kwargs.get("extra_env") or {}
        planned = (
            extra_env.get("SASE_AGENT_PLANNED_NAME")
            if isinstance(extra_env, dict)
            else None
        )
        return AgentLaunchResult(
            pid=123,
            workspace_num=int(kwargs.get("workspace_num", 0)),  # type: ignore[arg-type]
            workspace_dir=str(kwargs.get("workspace_dir", "/ws")),
            output_path="/out.txt",
            timestamp=str(kwargs.get("timestamp", "")),
            project_name=str(kwargs.get("project_name", "")),
            agent_name=planned if isinstance(planned, str) and planned else None,
        )

    spawn_mock = MagicMock(side_effect=fake_spawn)
    return spawn_mock


def test_single_prompt_launch_result_carries_auto_planned_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bare prompt with no explicit name gets a parent-allocated auto name."""
    patch_cd_metadata(monkeypatch)
    from sase.agent.launcher import launch_agents_from_cwd

    spawn = _make_spawn_capture()
    with (
        patch(
            "sase.main.utils.ensure_project_file_and_get_workspace_num",
            return_value=(None, None, None),
        ),
        patch("sase.history.prompt.add_or_update_prompt"),
        patch(
            "sase.core.agent_launch_facade.reserve_launch_timestamp_batch",
            return_value=["260501_120000"],
        ),
        patch("sase.agent.names.get_active_agent_names", return_value=set()),
        patch("sase.agent.launcher.spawn_agent_subprocess", spawn),
        patch("sase.running_field.get_first_available_axe_workspace"),
        patch("sase.running_field.get_workspace_directory_for_num"),
    ):
        # No "#" anchor so PlannedNameAllocator can safely auto-allocate.
        results = launch_agents_from_cwd("do work")

    assert len(results) == 1
    assert results[0].agent_name == "a"
    kwargs = spawn.call_args.kwargs
    assert kwargs["extra_env"]["SASE_AGENT_PLANNED_NAME"] == "a"


def test_single_prompt_launch_result_carries_explicit_name(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A ``%name:foo`` prompt makes the launch result carry ``foo``."""
    patch_cd_metadata(monkeypatch)
    from sase.agent.launcher import launch_agents_from_cwd

    spawn = _make_spawn_capture()
    with (
        patch(
            "sase.main.utils.ensure_project_file_and_get_workspace_num",
            return_value=(None, None, None),
        ),
        patch("sase.history.prompt.add_or_update_prompt"),
        patch(
            "sase.core.agent_launch_facade.reserve_launch_timestamp_batch",
            return_value=["260501_120000"],
        ),
        patch("sase.agent.names.get_active_agent_names", return_value=set()),
        patch("sase.agent.launcher.spawn_agent_subprocess", spawn),
        patch("sase.running_field.get_first_available_axe_workspace"),
        patch("sase.running_field.get_workspace_directory_for_num"),
    ):
        results = launch_agents_from_cwd(f"%name:foo\n#cd:{tmp_path} do work")

    assert len(results) == 1
    assert results[0].agent_name == "foo"
    kwargs = spawn.call_args.kwargs
    assert kwargs["extra_env"]["SASE_AGENT_PLANNED_NAME"] == "foo"


def test_single_prompt_with_unexpanded_xprompt_leaves_agent_name_unset(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A prompt whose name depends on xprompt expansion is not pre-planned."""
    patch_cd_metadata(monkeypatch)
    from sase.agent.launcher import launch_agents_from_cwd

    spawn = _make_spawn_capture()
    with (
        patch(
            "sase.main.utils.ensure_project_file_and_get_workspace_num",
            return_value=(None, None, None),
        ),
        patch("sase.history.prompt.add_or_update_prompt"),
        patch(
            "sase.core.agent_launch_facade.reserve_launch_timestamp_batch",
            return_value=["260501_120000"],
        ),
        patch("sase.agent.launcher.spawn_agent_subprocess", spawn),
        patch("sase.running_field.get_first_available_axe_workspace"),
        patch("sase.running_field.get_workspace_directory_for_num"),
    ):
        results = launch_agents_from_cwd(f"#somextprompt #cd:{tmp_path} do work")

    assert len(results) == 1
    kwargs = spawn.call_args.kwargs
    assert kwargs["extra_env"] is None or (
        "SASE_AGENT_PLANNED_NAME" not in (kwargs["extra_env"] or {})
    )
    assert results[0].agent_name is None
