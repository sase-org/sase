"""Tests for marking collapsed and focused Agents-tab groups."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

from sase.ace.tui.models.agent import AgentType
from sase.ace.tui.models.agent_groups import GroupingMode
from sase.ace.tui.models.agent_panels import AgentPanelGroup

from tests.ace.tui._agent_marking_helpers import _FakeMarkApp, _make_agent


def test_toggle_mark_on_focused_group_marks_top_level_members_in_order() -> None:
    a1 = _make_agent(
        project_file="/tmp/projects/proj_a/proj_a.sase",
        cl_name="release-fix",
        raw_suffix="20240101120000",
    )
    a2 = _make_agent(
        project_file="/tmp/projects/proj_a/proj_a.sase",
        cl_name="release-fix",
        raw_suffix="20240101130000",
    )
    other = _make_agent(
        project_file="/tmp/projects/proj_a/proj_a.sase",
        cl_name="other-cl",
        raw_suffix="20240101140000",
    )
    app = _FakeMarkApp([a1, a2, other])
    app._group_fold_registry.collapse(("proj_a", "release-fix"))
    app._current_group_key = ("proj_a", "release-fix")

    app._toggle_mark_agent()

    assert app._marked_agents == {a1.identity, a2.identity}
    assert app._marked_agent_order == [a1.identity, a2.identity]
    assert other.identity not in app._marked_agents
    assert app.current_idx == 2
    assert app._current_group_key is None
    assert app.refresh_call_kwargs[-1] == {"list_changed": True, "defer_detail": False}


def test_toggle_mark_on_focused_group_unmarks_when_fully_marked() -> None:
    a1 = _make_agent(
        project_file="/tmp/projects/proj_a/proj_a.sase",
        cl_name="release-fix",
        raw_suffix="20240101120000",
    )
    a2 = _make_agent(
        project_file="/tmp/projects/proj_a/proj_a.sase",
        cl_name="release-fix",
        raw_suffix="20240101130000",
    )
    app = _FakeMarkApp([a1, a2])
    app._group_fold_registry.collapse(("proj_a", "release-fix"))
    app._current_group_key = ("proj_a", "release-fix")
    app._marked_agents = {a1.identity, a2.identity}
    app._marked_agent_order = [a1.identity, a2.identity]

    app._toggle_mark_agent()

    assert app._marked_agents == set()
    assert app._marked_agent_order == []


def test_toggle_mark_on_partially_marked_group_marks_all() -> None:
    a1 = _make_agent(
        project_file="/tmp/projects/proj_a/proj_a.sase",
        cl_name="release-fix",
        raw_suffix="20240101120000",
    )
    a2 = _make_agent(
        project_file="/tmp/projects/proj_a/proj_a.sase",
        cl_name="release-fix",
        raw_suffix="20240101130000",
    )
    outside = _make_agent(
        project_file="/tmp/projects/proj_b/proj_b.sase",
        cl_name="outside",
        raw_suffix="20240101140000",
    )
    app = _FakeMarkApp([a1, a2, outside])
    app._group_fold_registry.collapse(("proj_a", "release-fix"))
    app._current_group_key = ("proj_a", "release-fix")
    app._marked_agents = {a1.identity, outside.identity}
    app._marked_agent_order = [a1.identity, outside.identity]

    app._toggle_mark_agent()

    assert app._marked_agents == {a1.identity, a2.identity, outside.identity}
    assert app._marked_agent_order == [outside.identity, a1.identity, a2.identity]


def test_toggle_mark_on_focused_group_skips_workflow_children() -> None:
    parent = _make_agent(
        agent_type=AgentType.WORKFLOW,
        project_file="/tmp/projects/proj_a/proj_a.sase",
        cl_name="parent",
        raw_suffix="20240101120000",
    )
    child = _make_agent(
        project_file="/tmp/projects/proj_a/proj_a.sase",
        cl_name="parent",
        raw_suffix="20240101120100",
        parent_timestamp="20240101120000",
    )
    app = _FakeMarkApp([parent, child])
    app._group_fold_registry.collapse(("proj_a", "parent"))
    app._current_group_key = ("proj_a", "parent")

    app._toggle_mark_agent()

    assert parent.identity in app._marked_agents
    assert child.identity not in app._marked_agents


def test_toggle_mark_stale_group_key_falls_back_to_single_agent() -> None:
    a1 = _make_agent(raw_suffix="20240101120000")
    app = _FakeMarkApp([a1])
    app._current_group_key = ("ghost",)

    app._toggle_mark_agent()

    assert app._marked_agents == {a1.identity}
    assert app._current_group_key is None


def test_toggle_mark_focused_group_is_scoped_to_focused_panel() -> None:
    """Same-hour agents in another tribe panel stay unmarked."""
    now = datetime(2026, 7, 13, 12, 0, 0)
    epic_a = _make_agent(
        cl_name="epic-a",
        raw_suffix="20260713100500",
        start_time=datetime(2026, 7, 13, 10, 5, 0),
        tribe="epic",
    )
    no_tribe_a = _make_agent(
        cl_name="no-tribe-a",
        raw_suffix="20260713101000",
        start_time=datetime(2026, 7, 13, 10, 10, 0),
    )
    epic_b = _make_agent(
        cl_name="epic-b",
        raw_suffix="20260713102000",
        start_time=datetime(2026, 7, 13, 10, 20, 0),
        tribe="epic",
    )
    no_tribe_b = _make_agent(
        cl_name="no-tribe-b",
        raw_suffix="20260713103000",
        start_time=datetime(2026, 7, 13, 10, 30, 0),
    )
    app = _FakeMarkApp([epic_a, no_tribe_a, epic_b, no_tribe_b])
    app._panel_group = AgentPanelGroup.from_agents(app._agents, focused_key=None)
    app._grouping_mode = GroupingMode.BY_DATE
    app._current_group_key = ("Today", "10:00")
    app._group_fold_registry.collapse(app._current_group_key)

    with patch("sase.ace.tui.models.agent_groups._tree.local_now", return_value=now):
        assert app._toggle_mark_focused_group()

    assert app._marked_agents == {no_tribe_a.identity, no_tribe_b.identity}
    assert epic_a.identity not in app._marked_agents
    assert epic_b.identity not in app._marked_agents


def test_group_marked_agents_are_seen_by_bulk_kill() -> None:
    running = _make_agent(
        project_file="/tmp/projects/proj_a/proj_a.sase",
        cl_name="release-fix",
        raw_suffix="20240101120000",
        status="RUNNING",
        pid=111,
    )
    done = _make_agent(
        project_file="/tmp/projects/proj_a/proj_a.sase",
        cl_name="release-fix",
        raw_suffix="20240101130000",
        status="DONE",
        pid=None,
    )
    app = _FakeMarkApp([running, done])
    app._group_fold_registry.collapse(("proj_a", "release-fix"))
    app._current_group_key = ("proj_a", "release-fix")
    app._toggle_mark_agent()

    with patch.object(app, "_do_bulk_kill_agents") as mock_bulk:
        app._bulk_kill_marked_agents()
        app.pushed_callbacks[0](True)

    mock_bulk.assert_called_once_with([running], [done])


def test_group_mark_advance_lands_on_next_banner_stop() -> None:
    alpha = _make_agent(
        project_file="/tmp/projects/proj_a/proj_a.sase",
        cl_name="alpha",
        raw_suffix="20240101120000",
    )
    beta = _make_agent(
        project_file="/tmp/projects/proj_a/proj_a.sase",
        cl_name="beta",
        raw_suffix="20240101130000",
    )
    app = _FakeMarkApp([alpha, beta])
    app._group_fold_registry.collapse(("proj_a", "alpha"))
    app._group_fold_registry.collapse(("proj_a", "beta"))
    app._current_group_key = ("proj_a", "alpha")

    app._toggle_mark_agent()

    assert app._marked_agents == {alpha.identity}
    assert app._current_group_key == ("proj_a", "beta")
    assert app.current_idx == 1
