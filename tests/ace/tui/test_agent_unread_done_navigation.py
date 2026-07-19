"""Core unread completed-agent jump navigation tests."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import Mock

import pytest

from ._agent_unread_helpers import make_agent
from ._agent_unread_navigation_helpers import LeaderUnreadJumpApp, UnreadJumpApp


@pytest.fixture(autouse=True)
def notification_dismiss(monkeypatch: pytest.MonkeyPatch) -> Mock:
    dismiss = Mock(return_value=0)
    monkeypatch.setattr(
        "sase.notifications.dismiss_agent_completion_notifications_matching_agents",
        dismiss,
    )
    return dismiss


def test_jump_to_next_unread_done_agent_uses_completion_recency_and_wraps() -> None:
    older = make_agent(
        name="older",
        status="DONE",
        raw_suffix="older",
        stop_time=datetime(2026, 5, 7, 10, 0, 0),
    )
    newest = make_agent(
        name="newest",
        status="DONE",
        raw_suffix="newest",
        stop_time=datetime(2026, 5, 7, 12, 0, 0),
    )
    running = make_agent(
        name="running",
        status="RUNNING",
        raw_suffix="running",
        stop_time=datetime(2026, 5, 7, 13, 0, 0),
    )
    middle = make_agent(
        name="middle",
        status="FAILED",
        raw_suffix="middle",
        stop_time=datetime(2026, 5, 7, 11, 0, 0),
    )
    app = UnreadJumpApp(
        [older, newest, running, middle],
        visible=[2, 0, 3, 1],
        current_idx=2,
    )
    app._unread_completed_agent_ids.update(
        {older.identity, newest.identity, running.identity, middle.identity}
    )

    assert app._jump_to_next_unread_done_agent()
    assert app.current_idx == 1
    assert newest.identity not in app._unread_completed_agent_ids

    assert app._jump_to_next_unread_done_agent()
    assert app.current_idx == 3
    assert middle.identity not in app._unread_completed_agent_ids

    assert app._jump_to_next_unread_done_agent()
    assert app.current_idx == 0
    assert older.identity not in app._unread_completed_agent_ids

    assert not app._jump_to_next_unread_done_agent()
    assert app.current_idx == 0


def test_repeated_leader_j_walks_unread_done_agents_by_recency(
    notification_dismiss: Mock,
) -> None:
    notification_dismiss.return_value = 1
    oldest = make_agent(
        name="oldest",
        status="DONE",
        raw_suffix="oldest",
        tag="zeta",
        stop_time=datetime(2026, 5, 7, 10, 0, 0),
    )
    newest = make_agent(
        name="newest",
        status="PLAN DONE",
        raw_suffix="newest",
        tag="alpha",
        stop_time=datetime(2026, 5, 7, 13, 0, 0),
    )
    running = make_agent(
        name="running",
        status="RUNNING",
        raw_suffix="running",
        stop_time=datetime(2026, 5, 7, 14, 0, 0),
    )
    middle = make_agent(
        name="middle",
        status="FAILED",
        raw_suffix="middle",
        tag="beta",
        stop_time=datetime(2026, 5, 7, 12, 0, 0),
    )
    app = LeaderUnreadJumpApp(
        [oldest, newest, running, middle],
        current_idx=2,
    )
    app._unread_completed_agent_ids.update(
        {oldest.identity, newest.identity, middle.identity}
    )

    assert app._handle_leader_key("j") is True
    assert app.current_idx == 1
    assert app._panel_group.focused_key == "alpha"
    assert app._entry_jump_agents_anchor_stack == [("agent", 2, None)]

    assert app._handle_leader_key("comma") is True
    assert app.current_idx == 3
    assert app._panel_group.focused_key == "beta"
    assert app._entry_jump_agents_anchor_stack == [
        ("agent", 2, None),
        ("agent", 1, "alpha"),
    ]

    assert app._handle_leader_key("comma") is True
    assert app.current_idx == 0
    assert app._panel_group.focused_key == "zeta"
    assert app._entry_jump_agents_anchor_stack == [
        ("agent", 2, None),
        ("agent", 1, "alpha"),
        ("agent", 3, "beta"),
    ]

    assert app._handle_leader_key("comma") is True
    assert app.current_idx == 0
    assert app._last_leader_key == "j"
    assert app._entry_jump_agents_anchor_stack == [
        ("agent", 2, None),
        ("agent", 1, "alpha"),
        ("agent", 3, "beta"),
    ]
    assert app._unread_completed_agent_ids == set()
    assert app.notifications == ["No unread completed agents"]
    assert app.current_tab_refresh_calls == 4
    assert app.refresh_calls == [
        {"list_changed": False, "defer_detail": True},
        {"list_changed": False, "defer_detail": True},
        {"list_changed": False, "defer_detail": True},
    ]
    assert app.patch_calls == [newest, middle, oldest]
    assert notification_dismiss.call_count == 3
    assert app.notification_count_refresh_calls == 3


def test_jump_to_next_unread_done_agent_wraps_from_oldest_to_newest() -> None:
    oldest = make_agent(
        name="oldest",
        status="DONE",
        raw_suffix="oldest",
        stop_time=datetime(2026, 5, 7, 10, 0, 0),
    )
    newest = make_agent(
        name="newest",
        status="DONE",
        raw_suffix="newest",
        stop_time=datetime(2026, 5, 7, 12, 0, 0),
    )
    app = UnreadJumpApp([oldest, newest], current_idx=0)
    app._unread_completed_agent_ids.update({oldest.identity, newest.identity})

    assert app._jump_to_next_unread_done_agent()

    assert app.current_idx == 1
    assert newest.identity not in app._unread_completed_agent_ids


def test_jump_to_next_unread_done_agent_ignores_running_and_read_done() -> None:
    running = make_agent(name="running", status="RUNNING", raw_suffix="running")
    read_done = make_agent(name="read", status="DONE", raw_suffix="read")
    unread_done = make_agent(name="unread", status="DONE", raw_suffix="unread")
    app = UnreadJumpApp([running, read_done, unread_done], current_idx=0)
    app._unread_completed_agent_ids.add(unread_done.identity)

    assert app._jump_to_next_unread_done_agent()
    assert app.current_idx == 2
    assert app.patch_calls == [unread_done]


def test_jump_to_next_unread_done_agent_uses_start_time_when_stop_time_missing() -> (
    None
):
    fallback_newest = make_agent(
        name="fallback",
        status="DONE",
        raw_suffix="fallback",
        start_time=datetime(2026, 5, 7, 12, 0, 0),
        stop_time=None,
    )
    stopped_older = make_agent(
        name="stopped",
        status="DONE",
        raw_suffix="stopped",
        start_time=datetime(2026, 5, 7, 8, 0, 0),
        stop_time=datetime(2026, 5, 7, 11, 0, 0),
    )
    missing_time = make_agent(
        name="missing",
        status="FAILED",
        raw_suffix="missing",
        start_time=None,
        stop_time=None,
    )
    app = UnreadJumpApp(
        [stopped_older, missing_time, fallback_newest],
        current_idx=99,
    )
    app._unread_completed_agent_ids.update(
        {fallback_newest.identity, stopped_older.identity, missing_time.identity}
    )

    assert app._jump_to_next_unread_done_agent()
    assert app.current_idx == 2
    assert fallback_newest.identity not in app._unread_completed_agent_ids

    assert app._jump_to_next_unread_done_agent()
    assert app.current_idx == 0
    assert stopped_older.identity not in app._unread_completed_agent_ids

    assert app._jump_to_next_unread_done_agent()
    assert app.current_idx == 1
    assert missing_time.identity not in app._unread_completed_agent_ids


def test_jump_to_next_unread_done_agent_acknowledges_target_unread_state(
    notification_dismiss: Mock,
) -> None:
    notification_dismiss.return_value = 1
    done = make_agent(name="done", status="PLAN DONE")
    app = UnreadJumpApp([done])
    app._unread_completed_agent_ids.add(done.identity)

    assert app._jump_to_next_unread_done_agent()

    assert done.identity not in app._unread_completed_agent_ids
    assert app.current_attempt_number is None
    assert app.patch_calls == [done]
    assert app.refresh_calls == []
    notification_dismiss.assert_called_once_with(
        [{"cl_name": done.cl_name, "raw_suffix": done.raw_suffix}]
    )
    assert app.notification_count_refresh_calls == 1


def test_jump_to_next_unread_done_agent_falls_back_to_full_refresh() -> None:
    done = make_agent(name="done", status="FAILED")
    app = UnreadJumpApp([done], patch_result=False)
    app._unread_completed_agent_ids.add(done.identity)

    assert app._jump_to_next_unread_done_agent()

    assert done.identity not in app._unread_completed_agent_ids
    assert app.refresh_calls == [{"list_changed": True, "defer_detail": True}]


def test_jump_to_next_unread_done_agent_clears_banner_focus_and_refreshes() -> None:
    done = make_agent(name="done", status="DONE")
    app = UnreadJumpApp(
        [done],
        current_idx=0,
        stops=[("banner", ("done",)), ("agent", 0)],
    )
    app._current_group_key = ("done",)
    app._unread_completed_agent_ids.add(done.identity)

    assert app._jump_to_next_unread_done_agent()

    assert app.current_idx == 0
    assert app._current_group_key is None
    assert app._entry_jump_agents_anchor_stack == [("banner", None, ("done",))]
    assert done.identity not in app._unread_completed_agent_ids
    assert app.patch_calls == [done]
    assert app.refresh_calls == [{"list_changed": False, "defer_detail": True}]


def test_jump_to_next_unread_done_agent_starts_at_newest_from_focused_banner() -> None:
    first = make_agent(
        name="first",
        status="DONE",
        raw_suffix="first",
        stop_time=datetime(2026, 5, 7, 10, 0, 0),
    )
    second = make_agent(
        name="second",
        status="DONE",
        raw_suffix="second",
        stop_time=datetime(2026, 5, 7, 12, 0, 0),
    )
    app = UnreadJumpApp(
        [first, second],
        visible=[0, 1],
        stops=[("banner", ("group",)), ("agent", 1), ("agent", 0)],
    )
    app._current_group_key = ("group",)
    app._unread_completed_agent_ids.update({first.identity, second.identity})

    assert app._jump_to_next_unread_done_agent()

    assert app.current_idx == 1
    assert app._current_group_key is None
    assert app._unread_completed_agent_ids == {first.identity}
