"""Stopped-agent jump navigation tests."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import Mock

import pytest

from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry

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
    assert app._entry_jump_agents_anchor_stack == [("banner", None, ("group",))]
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
    assert app.refresh_calls == [{"list_changed": False, "defer_detail": True}]


def test_jump_to_next_stopped_agent_back_jump_restores_without_acknowledging_unread() -> (
    None
):
    origin = make_agent(name="origin", status="DONE", raw_suffix="origin")
    target = make_agent(
        name="target",
        status="PLAN",
        raw_suffix="target",
        tag="chop",
        start_time=datetime(2026, 5, 7, 12, 0, 0),
    )
    target.plan_times = [datetime(2026, 5, 7, 12, 0, 0)]
    app = UnreadJumpApp(
        [origin, target],
        current_idx=0,
        with_panels=True,
        focused_key=None,
    )
    app._unread_completed_agent_ids.add(origin.identity)
    unread_before = set(app._unread_completed_agent_ids)

    assert app._jump_to_next_stopped_agent()
    assert app.current_idx == 1
    assert app._panel_group.focused_idx == 1
    assert app._entry_jump_agents_anchor_stack == [("agent", 0, None)]
    assert app._unread_completed_agent_ids == unread_before

    assert app._restore_agents_jump_anchor()
    assert app.current_idx == 0
    assert app._panel_group.focused_idx == 0
    assert app._current_group_key is None
    assert app._unread_completed_agent_ids == unread_before
    assert app._entry_jump_agents_anchor_stack == []


def test_stopped_jump_expands_collapsed_panel_without_acknowledging_state() -> None:
    origin = make_agent(name="origin", status="DONE", raw_suffix="origin")
    older = make_agent(
        name="older",
        status="PLAN",
        raw_suffix="older",
        tag="alpha",
        start_time=datetime(2026, 7, 16, 9, 0, 0),
    )
    older.plan_times = [datetime(2026, 7, 16, 10, 0, 0)]
    target = make_agent(
        name="target",
        status="QUESTION",
        raw_suffix="target",
        tag="alpha",
        start_time=datetime(2026, 7, 16, 8, 0, 0),
    )
    target.questions_times = [datetime(2026, 7, 16, 12, 0, 0)]
    app = UnreadJumpApp(
        [origin, older, target],
        current_idx=0,
        with_panels=True,
        collapsed_panels={"alpha"},
    )
    app._unread_completed_agent_ids.update({origin.identity, target.identity})
    app._manual_unread_agent_ids.add(origin.identity)
    unread_before = set(app._unread_completed_agent_ids)
    manual_before = set(app._manual_unread_agent_ids)

    assert app._jump_to_next_stopped_agent()

    assert app._collapsed_panel_keys == set()
    assert app._panel_group.focused_key == "alpha"
    assert app.current_idx == 2
    assert app._unread_completed_agent_ids == unread_before
    assert app._manual_unread_agent_ids == manual_before
    assert app.patch_calls == []
    assert app.refresh_calls == [{"list_changed": True, "defer_detail": True}]

    assert app._jump_to_next_stopped_agent()
    assert app.current_idx == 1
    assert app.refresh_calls == [{"list_changed": True, "defer_detail": True}]


def test_stopped_jump_from_collapsed_header_starts_at_newest_backing_row() -> None:
    newest = make_agent(
        name="newest",
        status="PLAN",
        raw_suffix="newest",
        tag="alpha",
        start_time=datetime(2026, 7, 16, 9, 0, 0),
    )
    newest.plan_times = [datetime(2026, 7, 16, 12, 0, 0)]
    older = make_agent(
        name="older",
        status="QUESTION",
        raw_suffix="older",
        tag="beta",
        start_time=datetime(2026, 7, 16, 8, 0, 0),
    )
    older.questions_times = [datetime(2026, 7, 16, 10, 0, 0)]
    app = UnreadJumpApp(
        [newest, older],
        current_idx=0,
        with_panels=True,
        focused_key="alpha",
        collapsed_panels={"alpha"},
    )
    assert app._current_agents_jump_anchor() == ("panel", "alpha")

    assert app._jump_to_next_stopped_agent()

    assert app.current_idx == 0
    assert app._panel_group.focused_key == "alpha"
    assert app._collapsed_panel_keys == set()
    assert app._entry_jump_agents_anchor_stack == [("panel", "alpha")]
    assert app._restore_agents_jump_anchor() is True
    assert app._collapsed_panel_keys == set()
    assert app._expanded_panel_focus is True


def test_stopped_jump_selects_newest_across_multiple_collapsed_panels() -> None:
    origin = make_agent(name="origin", status="RUNNING", raw_suffix="origin")
    alpha = make_agent(
        name="alpha",
        status="PLAN",
        raw_suffix="alpha",
        tag="alpha",
    )
    alpha.plan_times = [datetime(2026, 7, 16, 10, 0, 0)]
    beta = make_agent(
        name="beta",
        status="QUESTION",
        raw_suffix="beta",
        tag="beta",
    )
    beta.questions_times = [datetime(2026, 7, 16, 12, 0, 0)]
    app = UnreadJumpApp(
        [origin, alpha, beta],
        with_panels=True,
        collapsed_panels={"alpha", "beta"},
    )

    assert app._jump_to_next_stopped_agent()

    assert app.current_idx == 2
    assert app._panel_group.focused_key == "beta"
    assert app._collapsed_panel_keys == {"alpha"}


def test_stopped_jump_no_match_preserves_collapsed_panel_and_group_fold() -> None:
    hidden = make_agent(
        name="hidden",
        status="PLAN",
        raw_suffix="hidden",
        tag="alpha",
    )
    hidden.plan_times = [datetime(2026, 7, 16, 12, 0, 0)]
    sibling = make_agent(
        name="sibling",
        status="RUNNING",
        raw_suffix="sibling",
        tag="alpha",
    )
    app = UnreadJumpApp(
        [hidden, sibling],
        with_panels=True,
        focused_key="alpha",
        collapsed_panels={"alpha"},
    )
    app._group_fold_registry = AgentGroupFoldRegistry()
    registry = app._group_fold_registry.for_panel("alpha")
    registry.collapse(("demo",))

    assert app._jump_to_next_stopped_agent() is False
    assert app._collapsed_panel_keys == {"alpha"}
    assert app._panel_group.focused_key == "alpha"
    assert registry.is_collapsed(("demo",))
    assert app.refresh_calls == []
    assert not hasattr(app, "_agents_fold_state_intents")
