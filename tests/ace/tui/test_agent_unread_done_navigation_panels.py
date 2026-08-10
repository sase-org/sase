"""Panel-aware unread completed-agent jump navigation tests."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import Mock

import pytest

from ._agent_unread_helpers import make_agent
from ._agent_unread_navigation_helpers import UnreadJumpApp


@pytest.fixture(autouse=True)
def notification_dismiss(monkeypatch: pytest.MonkeyPatch) -> Mock:
    dismiss = Mock(return_value=0)
    monkeypatch.setattr(
        "sase.notifications.dismiss_agent_completion_notifications_matching_agents",
        dismiss,
    )
    return dismiss


def test_jump_to_next_unread_done_agent_finds_non_focused_panel_row() -> None:
    focused = make_agent(name="focused", status="RUNNING", raw_suffix="focused")
    target = make_agent(
        name="target",
        status="PLAN DONE",
        raw_suffix="target",
        tribe="alpha",
        stop_time=datetime(2026, 5, 7, 12, 0, 0),
    )
    app = UnreadJumpApp(
        [focused, target],
        current_idx=0,
        with_panels=True,
        focused_key=None,
    )
    assert app._panel_group.panel_keys == [None, "alpha"]
    assert app._panel_group.focused_idx == 0
    app._unread_completed_agent_ids.add(target.identity)

    assert app._jump_to_next_unread_done_agent()

    assert app.current_idx == 1
    assert app._panel_group.focused_idx == 1
    assert target.identity not in app._unread_completed_agent_ids
    assert app.patch_calls == [target]
    assert app.refresh_calls == [{"list_changed": False, "defer_detail": True}]


def test_jump_to_next_unread_done_agent_back_jump_restores_origin() -> None:
    origin = make_agent(name="origin", status="RUNNING", raw_suffix="origin")
    target = make_agent(
        name="target",
        status="DONE",
        raw_suffix="target",
        tribe="chop",
        stop_time=datetime(2026, 5, 7, 12, 0, 0),
    )
    app = UnreadJumpApp(
        [origin, target],
        current_idx=0,
        with_panels=True,
        focused_key=None,
    )
    app._unread_completed_agent_ids.add(target.identity)

    assert app._jump_to_next_unread_done_agent()
    assert app.current_idx == 1
    assert app._panel_group.focused_idx == 1
    assert app._entry_jump_agents_anchor_stack == [("agent", 0, None)]

    assert app._restore_agents_jump_anchor()
    assert app.current_idx == 0
    assert app._panel_group.focused_idx == 0
    assert app._current_group_key is None
    assert app._entry_jump_agents_anchor_stack == []


def test_unread_jump_expands_collapsed_panel_and_selects_exact_row(
    notification_dismiss: Mock,
) -> None:
    notification_dismiss.return_value = 1
    origin = make_agent(name="origin", status="RUNNING", raw_suffix="origin")
    first_alpha = make_agent(
        name="first-alpha",
        status="RUNNING",
        raw_suffix="first-alpha",
        tribe="alpha",
    )
    target = make_agent(
        name="target",
        status="DONE",
        raw_suffix="target",
        tribe="alpha",
        stop_time=datetime(2026, 7, 16, 15, 0, 0),
    )
    beta = make_agent(
        name="beta",
        status="RUNNING",
        raw_suffix="beta",
        tribe="beta",
    )
    app = UnreadJumpApp(
        [origin, first_alpha, target, beta],
        current_idx=0,
        with_panels=True,
        focused_key=None,
        collapsed_panels={"alpha"},
    )
    app._unread_completed_agent_ids.add(target.identity)
    assert app._panel_group.panel_keys == [None, "beta", "alpha"]

    assert app._jump_to_next_unread_done_agent()

    assert app._collapsed_panel_keys == set()
    assert app._panel_group.panel_keys == [None, "alpha", "beta"]
    assert app._panel_group.focused_key == "alpha"
    assert app.current_idx == 2
    assert app._agents[app.current_idx] is target
    assert app.current_attempt_number is None
    assert target.identity not in app._unread_completed_agent_ids
    assert app.patch_calls == []
    assert app.refresh_calls == [{"list_changed": True, "defer_detail": True}]
    assert app._entry_jump_agents_anchor_stack == [("agent", 0, None)]
    notification_dismiss.assert_called_once_with(
        [{"cl_name": target.cl_name, "raw_suffix": target.raw_suffix}]
    )
    assert app.notification_count_refresh_calls == 1


def test_unread_jump_expands_manually_guarded_target_without_acknowledging(
    notification_dismiss: Mock,
) -> None:
    origin = make_agent(name="origin", status="RUNNING", raw_suffix="origin")
    target = make_agent(
        name="target",
        status="DONE",
        raw_suffix="target",
        tribe="alpha",
        stop_time=datetime(2026, 7, 16, 15, 0, 0),
    )
    app = UnreadJumpApp(
        [origin, target],
        with_panels=True,
        collapsed_panels={"alpha"},
    )
    app._unread_completed_agent_ids.add(target.identity)
    app._manual_unread_agent_ids.add(target.identity)

    assert app._jump_to_next_unread_done_agent()

    assert app._collapsed_panel_keys == set()
    assert app._panel_group.focused_key == "alpha"
    assert app.current_idx == 1
    assert target.identity in app._unread_completed_agent_ids
    assert target.identity in app._manual_unread_agent_ids
    assert app.patch_calls == []
    assert app.refresh_calls == [{"list_changed": True, "defer_detail": True}]
    notification_dismiss.assert_not_called()


def test_unread_jump_history_survives_panel_repartition_back_and_forward() -> None:
    target = make_agent(
        name="target",
        status="DONE",
        raw_suffix="target",
        tribe="alpha",
        stop_time=datetime(2026, 7, 16, 15, 0, 0),
    )
    beta = make_agent(
        name="beta",
        status="RUNNING",
        raw_suffix="beta",
        tribe="beta",
    )
    origin = make_agent(
        name="origin",
        status="RUNNING",
        raw_suffix="origin",
        tribe="gamma",
    )
    app = UnreadJumpApp(
        [target, beta, origin],
        current_idx=2,
        with_panels=True,
        focused_key="gamma",
        collapsed_panels={"alpha"},
    )
    app._unread_completed_agent_ids.add(target.identity)
    assert app._panel_group.panel_keys == ["beta", "gamma", "alpha"]

    assert app._jump_to_next_unread_done_agent()
    assert app._panel_group.panel_keys == ["alpha", "beta", "gamma"]
    assert app._entry_jump_agents_anchor_stack == [("agent", 2, "gamma")]

    assert app._restore_agents_jump_anchor()
    assert app._panel_group.focused_key == "gamma"
    assert app.current_idx == 2

    app.action_jump_to_entry_forward()
    assert app._panel_group.focused_key == "alpha"
    assert app.current_idx == 0


def test_jump_to_next_unread_done_agent_returns_false_when_no_unread_panels() -> None:
    focused = make_agent(name="focused", status="RUNNING", raw_suffix="focused")
    done = make_agent(name="done", status="DONE", raw_suffix="done", tribe="chop")
    app = UnreadJumpApp(
        [focused, done],
        current_idx=0,
        with_panels=True,
        focused_key=None,
    )

    assert not app._jump_to_next_unread_done_agent()

    assert app.current_idx == 0
    assert app._panel_group.focused_idx == 0
    assert app.patch_calls == []
    assert app.refresh_calls == []
