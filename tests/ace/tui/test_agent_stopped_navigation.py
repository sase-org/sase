"""Stopped-agent jump navigation tests."""

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
        "sase.notifications.dismiss_notifications_matching_agents", dismiss
    )
    return dismiss


def test_has_stopped_agent_tracks_stopped_status_bucket() -> None:
    plan = make_agent(name="plan", status="PLAN", raw_suffix="plan")
    question = make_agent(name="question", status="QUESTION", raw_suffix="question")
    done = make_agent(name="done", status="DONE", raw_suffix="done")

    assert UnreadJumpApp([done])._has_stopped_agent() is False
    assert UnreadJumpApp([done, plan])._has_stopped_agent() is True
    assert UnreadJumpApp([question])._has_stopped_agent() is True


def test_jump_to_next_stopped_agent_uses_stopped_recency_and_wraps(
    notification_dismiss: Mock,
) -> None:
    older_plan = make_agent(
        name="older",
        status="PLAN",
        raw_suffix="older",
        start_time=datetime(2026, 5, 7, 8, 0, 0),
    )
    older_plan.plan_times = [datetime(2026, 5, 7, 10, 0, 0)]
    newest_question = make_agent(
        name="newest",
        status="QUESTION",
        raw_suffix="newest",
        start_time=datetime(2026, 5, 7, 7, 0, 0),
    )
    newest_question.questions_times = [datetime(2026, 5, 7, 12, 0, 0)]
    fallback_plan = make_agent(
        name="fallback",
        status="PLAN",
        raw_suffix="fallback",
        start_time=datetime(2026, 5, 7, 11, 0, 0),
        stop_time=None,
    )
    done = make_agent(
        name="done",
        status="DONE",
        raw_suffix="done",
        stop_time=datetime(2026, 5, 7, 13, 0, 0),
    )
    failed = make_agent(
        name="failed",
        status="FAILED",
        raw_suffix="failed",
        stop_time=datetime(2026, 5, 7, 14, 0, 0),
    )
    app = UnreadJumpApp(
        [older_plan, newest_question, done, failed, fallback_plan],
        visible=[2, 0, 3, 4, 1],
        current_idx=2,
    )
    app._unread_completed_agent_ids.add(done.identity)
    unread_before = set(app._unread_completed_agent_ids)

    assert app._jump_to_next_stopped_agent()
    assert app.current_idx == 1
    assert app._unread_completed_agent_ids == unread_before

    assert app._jump_to_next_stopped_agent()
    assert app.current_idx == 4

    assert app._jump_to_next_stopped_agent()
    assert app.current_idx == 0

    assert app._jump_to_next_stopped_agent()
    assert app.current_idx == 1
    assert app.patch_calls == []
    assert app.refresh_calls == []
    notification_dismiss.assert_not_called()


def test_jump_to_next_stopped_agent_ignores_non_stopped_rows() -> None:
    running = make_agent(name="running", status="RUNNING", raw_suffix="running")
    waiting = make_agent(name="waiting", status="WAITING INPUT", raw_suffix="waiting")
    done = make_agent(name="done", status="DONE", raw_suffix="done")
    failed = make_agent(name="failed", status="FAILED", raw_suffix="failed")
    app = UnreadJumpApp([running, waiting, done, failed], current_idx=0)

    assert not app._jump_to_next_stopped_agent()
    assert app.current_idx == 0
    assert app.patch_calls == []
    assert app.refresh_calls == []


def test_jump_to_next_stopped_agent_starts_at_newest_from_focused_banner() -> None:
    first = make_agent(
        name="first",
        status="PLAN",
        raw_suffix="first",
        start_time=datetime(2026, 5, 7, 9, 0, 0),
    )
    first.plan_times = [datetime(2026, 5, 7, 10, 0, 0)]
    second = make_agent(
        name="second",
        status="QUESTION",
        raw_suffix="second",
        start_time=datetime(2026, 5, 7, 9, 0, 0),
    )
    second.questions_times = [datetime(2026, 5, 7, 12, 0, 0)]
    app = UnreadJumpApp(
        [first, second],
        visible=[0, 1],
        stops=[("banner", ("group",)), ("agent", 1), ("agent", 0)],
    )
    app._current_group_key = ("group",)

    assert app._jump_to_next_stopped_agent()

    assert app.current_idx == 1
    assert app._current_group_key is None
    assert app.current_attempt_number is None
    assert app.refresh_calls == []


def test_jump_to_next_stopped_agent_finds_non_focused_panel_row() -> None:
    focused = make_agent(name="focused", status="RUNNING", raw_suffix="focused")
    target = make_agent(
        name="target",
        status="PLAN",
        raw_suffix="target",
        tag="chop",
        start_time=datetime(2026, 5, 7, 12, 0, 0),
    )
    target.plan_times = [datetime(2026, 5, 7, 12, 0, 0)]
    app = UnreadJumpApp(
        [focused, target],
        current_idx=0,
        with_panels=True,
        focused_key=None,
    )
    assert app._panel_group.panel_keys == [None, "chop"]
    assert app._panel_group.focused_idx == 0

    assert app._jump_to_next_stopped_agent()

    assert app.current_idx == 1
    assert app._panel_group.focused_idx == 1
    assert app.current_attempt_number is None
    assert app.patch_calls == []
    assert app.refresh_calls == [{"list_changed": True, "defer_detail": True}]
