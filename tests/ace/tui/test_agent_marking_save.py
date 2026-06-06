"""Tests for saving and dismissing marked Agents-tab groups."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

from sase.ace.tui.commands import build_command_catalog, execute_command
from sase.ace.tui.keymaps import load_keymap_registry
from sase.ace.tui.modals.save_agent_group_modal import SaveAgentGroupModal
from sase.ace.tui.models.agent import Agent, AgentType

from tests.ace.tui._agent_marking_helpers import (
    _FakeMarkApp,
    _cancel_save_modal,
    _confirm_save_modal,
    _make_agent,
)


def test_save_marked_agent_group_warns_when_no_agents_marked() -> None:
    app = _FakeMarkApp([_make_agent()])

    app.action_save_marked_agents()

    assert app.notifications == [("No agents marked", "warning")]
    assert app.pushed_modals == []
    assert app._scheduled == []


def test_save_marked_agents_opens_group_name_modal_before_dismissing() -> None:
    running = _make_agent(raw_suffix="20240101120000", status="RUNNING", pid=111)
    app = _FakeMarkApp([running])
    app._marked_agents = {running.identity}

    app.action_save_marked_agents()

    assert len(app.pushed_modals) == 1
    modal = app.pushed_modals[0]
    assert isinstance(modal, SaveAgentGroupModal)
    assert modal.candidate_count == 1
    assert app._dismissed_agents == set()
    assert app._marked_agents == {running.identity}
    assert app._agents == [running]
    assert app._scheduled == []


def test_save_marked_agent_group_cancel_preserves_marks() -> None:
    running = _make_agent(raw_suffix="20240101120000", status="RUNNING", pid=111)
    app = _FakeMarkApp([running])
    app._marked_agents = {running.identity}

    app.action_save_marked_agents()
    _cancel_save_modal(app)

    assert app._dismissed_agents == set()
    assert app._marked_agents == {running.identity}
    assert app._agents == [running]
    assert app._scheduled == []


def test_save_marked_running_agents_hides_without_kill() -> None:
    """Agents-tab S must not call the bulk kill or SIGTERM path."""
    running = _make_agent(raw_suffix="20240101120000", status="RUNNING", pid=111)
    app = _FakeMarkApp([running])
    app._marked_agents = {running.identity}

    with (
        patch.object(app, "_do_bulk_kill_agents") as mock_bulk_kill,
        patch.object(app, "_kill_process_group", create=True) as mock_killpg,
    ):
        app.action_save_marked_agents()
        _confirm_save_modal(app)

    mock_bulk_kill.assert_not_called()
    mock_killpg.assert_not_called()
    assert app._dismissed_agents == {running.identity}
    assert app._marked_agents == set()
    assert app._agents == []
    assert app._scheduled


def test_save_marked_group_persists_refs_in_display_order() -> None:
    """The saved group records marked agents and cascaded children in row order."""
    parent = _make_agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="parent_cl",
        raw_suffix="20240101120000",
        workflow="wf",
        pid=111,
    )
    child = _make_agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="parent_cl",
        raw_suffix="20240101120001",
        parent_workflow="wf",
        parent_timestamp="20240101120000",
        step_index=1,
        pid=None,
    )
    other = _make_agent(cl_name="other_cl", raw_suffix="20240101130000", pid=222)
    app = _FakeMarkApp([parent, child, other])
    app._marked_agents = {other.identity, parent.identity}

    app.action_save_marked_agents()
    _confirm_save_modal(app, name="Backend batch")

    assert len(app._recent_dismissed_agent_groups) == 1
    assert app._recent_dismissed_agent_groups[0].name == "Backend batch"

    saved_groups: list[Any] = []
    recent_groups: list[Any] = []
    saved_bundles: list[Agent] = []
    with (
        patch("sase.ace.dismissed_agents.save_dismissed_bundle") as mock_bundle,
        patch("sase.ace.dismissed_agents.save_dismissed_agents", return_value=True),
        patch(
            "sase.ace.dismissed_agents.save_dismissed_agent_group",
            side_effect=lambda group: saved_groups.append(group) or group,
        ),
        patch(
            "sase.ace.dismissed_agents.record_recent_dismissed_agent_group",
            side_effect=lambda group: recent_groups.append(group) or group,
        ),
        patch(
            "sase.ace.tui.actions.agents._marking.sync_dismissed_agent_artifact_index"
        ),
    ):
        mock_bundle.side_effect = lambda agent: saved_bundles.append(agent) or True
        callback, args = app._scheduled[0]
        asyncio.run(callback(*args))

    assert [agent.identity for agent in saved_bundles] == [
        parent.identity,
        child.identity,
        other.identity,
    ]
    assert len(saved_groups) == 1
    group = saved_groups[0]
    assert [ref.raw_suffix for ref in group.agent_refs] == [
        "20240101120000",
        "20240101120001",
        "20240101130000",
    ]
    assert [ref.is_workflow_child for ref in group.agent_refs] == [
        False,
        True,
        False,
    ]
    assert group.agent_count == 3
    assert group.top_level_agent_count == 2
    assert group.name == "Backend batch"
    assert recent_groups == saved_groups


def test_blank_save_preserves_generated_group_title() -> None:
    running = _make_agent(raw_suffix="20240101120000", status="DONE", pid=None)
    app = _FakeMarkApp([running])
    app._marked_agents = {running.identity}

    app.action_save_marked_agents()
    _confirm_save_modal(app)

    saved_groups: list[Any] = []
    with (
        patch("sase.ace.dismissed_agents.save_dismissed_bundle"),
        patch("sase.ace.dismissed_agents.save_dismissed_agents", return_value=True),
        patch(
            "sase.ace.dismissed_agents.save_dismissed_agent_group",
            side_effect=lambda group: saved_groups.append(group) or group,
        ),
        patch("sase.ace.dismissed_agents.record_recent_dismissed_agent_group"),
        patch(
            "sase.ace.tui.actions.agents._marking.sync_dismissed_agent_artifact_index"
        ),
    ):
        callback, args = app._scheduled[0]
        asyncio.run(callback(*args))

    assert len(saved_groups) == 1
    assert saved_groups[0].title == "1 agent in test_cl"
    assert saved_groups[0].name is None


def test_command_palette_save_marked_agents_opens_group_name_modal() -> None:
    running = _make_agent(raw_suffix="20240101120000", status="DONE", pid=None)
    app = _FakeMarkApp([running])
    app._marked_agents = {running.identity}
    catalog = {
        spec.id: spec for spec in build_command_catalog(load_keymap_registry({}))
    }

    execute_command(app, catalog["app.save_marked_agents"])  # type: ignore[arg-type]

    assert len(app.pushed_modals) == 1
    assert isinstance(app.pushed_modals[0], SaveAgentGroupModal)
