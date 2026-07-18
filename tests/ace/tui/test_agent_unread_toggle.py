"""Unread agent toggle and bulk acknowledgment tests."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from ._agent_unread_helpers import make_agent
from ._agent_unread_navigation_helpers import UnreadJumpApp
from sase.ace.tui.models._agent_tree import project_clan_tree


@pytest.fixture(autouse=True)
def notification_dismiss(monkeypatch: pytest.MonkeyPatch) -> Mock:
    dismiss = Mock(return_value=0)
    monkeypatch.setattr(
        "sase.notifications.dismiss_agent_completion_notifications_matching_agents",
        dismiss,
    )
    return dismiss


def test_toggle_agent_unread_marks_selected_row_without_moving(
    notification_dismiss: Mock,
) -> None:
    agent = make_agent(status="RUNNING")
    app = UnreadJumpApp([agent])

    app._toggle_agent_unread()

    assert app.current_idx == 0
    assert app._unread_completed_agent_ids == {agent.identity}
    assert app._manual_unread_agent_ids == {agent.identity}
    assert app.patch_calls == [agent]
    assert app.refresh_calls == []
    notification_dismiss.assert_not_called()


def test_toggle_agent_unread_again_marks_selected_row_read(
    notification_dismiss: Mock,
) -> None:
    notification_dismiss.return_value = 1
    agent = make_agent(status="DONE")
    app = UnreadJumpApp([agent])
    app._unread_completed_agent_ids.add(agent.identity)
    app._manual_unread_agent_ids.add(agent.identity)

    app._toggle_agent_unread()

    assert app._unread_completed_agent_ids == set()
    assert app._manual_unread_agent_ids == set()
    assert app.patch_calls == [agent]
    notification_dismiss.assert_called_once_with(
        [{"cl_name": agent.cl_name, "raw_suffix": agent.raw_suffix}]
    )
    assert app.notification_count_refresh_calls == 1


def test_toggle_agent_unread_refreshes_when_patch_fails() -> None:
    agent = make_agent(status="DONE")
    app = UnreadJumpApp([agent], patch_result=False)

    app._toggle_agent_unread()

    assert app.refresh_calls == [{"list_changed": True, "defer_detail": True}]


def test_toggle_agent_unread_ignores_focused_banner() -> None:
    agent = make_agent(status="DONE")
    app = UnreadJumpApp([agent])
    app._current_group_key = ("demo",)

    app._toggle_agent_unread()

    assert app._unread_completed_agent_ids == set()
    assert app._manual_unread_agent_ids == set()
    assert app.patch_calls == []


def test_navigation_away_from_manual_unread_arms_it_without_clearing() -> None:
    first = make_agent(name="first", status="DONE", raw_suffix="first")
    second = make_agent(name="second", status="DONE", raw_suffix="second")
    app = UnreadJumpApp([first, second])
    app._unread_completed_agent_ids.add(first.identity)
    app._manual_unread_agent_ids.add(first.identity)

    app._navigate_agents_panel(1)

    assert app.current_idx == 1
    assert first.identity in app._unread_completed_agent_ids
    assert first.identity not in app._manual_unread_agent_ids
    assert app.patch_calls == []


def test_navigation_back_to_armed_manual_unread_acknowledges_it() -> None:
    first = make_agent(name="first", status="DONE", raw_suffix="first")
    second = make_agent(name="second", status="DONE", raw_suffix="second")
    app = UnreadJumpApp([first, second], current_idx=1)
    app._unread_completed_agent_ids.add(first.identity)

    app._navigate_agents_panel(-1)

    assert app.current_idx == 0
    assert first.identity not in app._unread_completed_agent_ids
    assert app.patch_calls == [first]


def test_keyboard_navigation_onto_clan_never_acknowledges_member() -> None:
    origin = make_agent(name="origin", status="RUNNING", raw_suffix="origin")
    member = make_agent(name="research.done", status="DONE", raw_suffix="done")
    member.agent_clan = "research"
    member.agent_clan_generation = "generation"
    container = project_clan_tree([member])[0]
    app = UnreadJumpApp([origin, container])
    app._unread_completed_agent_ids.add(member.identity)
    app._manual_unread_agent_ids.add(member.identity)

    app._navigate_agents_panel(1)

    assert app._agents[app.current_idx] is container
    assert app._unread_completed_agent_ids == {member.identity}
    assert app._manual_unread_agent_ids == {member.identity}
    assert app.patch_calls == []


def test_has_unread_completed_agent_includes_plan_done() -> None:
    agent = make_agent(status="PLAN DONE")
    app = UnreadJumpApp([agent])
    app._unread_completed_agent_ids.add(agent.identity)

    assert app._has_unread_completed_agent()


def test_manual_unread_guards_per_row_dismissal(
    notification_dismiss: Mock,
) -> None:
    """A manually-unread row is never cleared or dismissed through the
    per-row helper. The user has to explicitly toggle the manual marker off
    before the row can be acknowledged and its notification dismissed.
    """
    agent = make_agent(status="DONE")
    app = UnreadJumpApp([agent])
    app._unread_completed_agent_ids.add(agent.identity)
    app._manual_unread_agent_ids.add(agent.identity)

    assert not app._clear_agent_unread_and_dismiss_notification(agent)
    assert agent.identity in app._unread_completed_agent_ids
    assert agent.identity in app._manual_unread_agent_ids
    notification_dismiss.assert_not_called()
    assert app.notification_count_refresh_calls == 0

    assert not app._acknowledge_agent_unread(agent)
    assert agent.identity in app._unread_completed_agent_ids
    notification_dismiss.assert_not_called()


def test_mark_all_unread_done_agents_read_clears_state_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dismiss = Mock(return_value=2)
    monkeypatch.setattr(
        "sase.notifications.dismiss_agent_completion_notifications_matching_agents",
        dismiss,
    )
    first = make_agent(name="first", status="DONE", raw_suffix="first")
    second = make_agent(name="second", status="FAILED", raw_suffix="second")
    running = make_agent(name="running", status="RUNNING", raw_suffix="running")
    app = UnreadJumpApp([first, second, running])
    app._unread_completed_agent_ids.update(
        {first.identity, second.identity, running.identity}
    )
    app._manual_unread_agent_ids.update({first.identity, second.identity})

    count = app._mark_all_unread_done_agents_read()

    assert count == 2
    assert app._unread_completed_agent_ids == {running.identity}
    assert app._manual_unread_agent_ids == set()
    dismiss.assert_called_once_with(
        [
            {"cl_name": first.cl_name, "raw_suffix": first.raw_suffix},
            {"cl_name": second.cl_name, "raw_suffix": second.raw_suffix},
        ]
    )
    assert app.notification_count_refresh_calls == 1
    assert app.refresh_calls == []
    assert app.patch_calls == [first, second]


def test_mark_all_unread_done_agents_read_noops_without_terminal_unread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dismiss = Mock(return_value=0)
    monkeypatch.setattr(
        "sase.notifications.dismiss_agent_completion_notifications_matching_agents",
        dismiss,
    )
    running = make_agent(name="running", status="RUNNING", raw_suffix="running")
    app = UnreadJumpApp([running])
    app._unread_completed_agent_ids.add(running.identity)

    assert app._mark_all_unread_done_agents_read() == 0

    assert app._unread_completed_agent_ids == {running.identity}
    dismiss.assert_not_called()
    assert app.notification_count_refresh_calls == 0
    assert app.refresh_calls == []
    assert app.patch_calls == []
