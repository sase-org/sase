"""Unread agent toggle and jump navigation tests."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import Mock

import pytest

from sase.ace.tui.actions.agents._core import AgentsMixinCore
from sase.ace.tui.actions.navigation._basic import BasicNavigationMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_panels import AgentPanelGroup, panel_key_per_agent

from ._agent_unread_helpers import make_agent


@pytest.fixture(autouse=True)
def notification_dismiss(monkeypatch: pytest.MonkeyPatch) -> Mock:
    dismiss = Mock(return_value=0)
    monkeypatch.setattr(
        "sase.notifications.dismiss_notifications_matching_agents", dismiss
    )
    return dismiss


class _UnreadJumpApp(AgentsMixinCore, BasicNavigationMixin):
    def __init__(
        self,
        agents: list[Agent],
        *,
        visible: list[int] | None = None,
        stops: list[tuple[str, int | tuple[str, ...]]] | None = None,
        current_idx: int = 0,
        patch_result: bool = True,
        with_panels: bool = False,
        focused_key: str | None = None,
        merge_tag_panels: bool = False,
    ) -> None:
        self._agents = agents
        self.current_idx = current_idx
        self.current_attempt_number: int | None = 3
        self._current_group_key: tuple[str, ...] | None = None
        self._agent_panels_grouped = merge_tag_panels
        if with_panels:
            self._panel_group = AgentPanelGroup.from_agents(
                agents, focused_key, merge_tag_panels=merge_tag_panels
            )
        self._unread_completed_agent_ids: set[tuple[AgentType, str, str | None]] = set()
        self._manual_unread_agent_ids: set[tuple[AgentType, str, str | None]] = set()
        self._visible = visible
        self._stops = stops
        self._patch_result = patch_result
        self.patch_calls: list[Agent] = []
        self.refresh_calls: list[dict[str, Any]] = []
        self.debounced_refresh_calls = 0
        self.notification_count_refresh_calls = 0

    def _agents_visible_order(self) -> list[int]:
        if self._visible is not None:
            return self._visible
        return list(range(len(self._agents)))

    def _panel_navigation_stops(self) -> list[tuple[str, int | tuple[str, ...]]]:
        if self._stops is not None:
            return self._stops
        return [("agent", idx) for idx in self._agents_visible_order()]

    def _panel_keys_per_agent(self) -> list[str | None]:
        return panel_key_per_agent(
            self._agents,
            merge_tag_panels=getattr(self, "_agent_panels_grouped", False),
        )

    def _try_patch_agent_row(self, agent: Agent) -> bool:
        self.patch_calls.append(agent)
        return self._patch_result

    def _refresh_agents_display(self, **kwargs: Any) -> None:
        self.refresh_calls.append(kwargs)

    def _refresh_agents_display_debounced(self) -> None:
        self.debounced_refresh_calls += 1

    def _refresh_notification_count(self) -> None:
        self.notification_count_refresh_calls += 1


def test_toggle_agent_unread_marks_selected_row_without_moving(
    notification_dismiss: Mock,
) -> None:
    agent = make_agent(status="RUNNING")
    app = _UnreadJumpApp([agent])

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
    app = _UnreadJumpApp([agent])
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
    app = _UnreadJumpApp([agent], patch_result=False)

    app._toggle_agent_unread()

    assert app.refresh_calls == [{"list_changed": True, "defer_detail": True}]


def test_toggle_agent_unread_ignores_focused_banner() -> None:
    agent = make_agent(status="DONE")
    app = _UnreadJumpApp([agent])
    app._current_group_key = ("demo",)

    app._toggle_agent_unread()

    assert app._unread_completed_agent_ids == set()
    assert app._manual_unread_agent_ids == set()
    assert app.patch_calls == []


def test_navigation_away_from_manual_unread_arms_it_without_clearing() -> None:
    first = make_agent(name="first", status="DONE", raw_suffix="first")
    second = make_agent(name="second", status="DONE", raw_suffix="second")
    app = _UnreadJumpApp([first, second])
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
    app = _UnreadJumpApp([first, second], current_idx=1)
    app._unread_completed_agent_ids.add(first.identity)

    app._navigate_agents_panel(-1)

    assert app.current_idx == 0
    assert first.identity not in app._unread_completed_agent_ids
    assert app.patch_calls == [first]


def test_has_unread_completed_agent_includes_plan_done() -> None:
    agent = make_agent(status="PLAN DONE")
    app = _UnreadJumpApp([agent])
    app._unread_completed_agent_ids.add(agent.identity)

    assert app._has_unread_completed_agent()


def test_has_stopped_agent_tracks_stopped_status_bucket() -> None:
    plan = make_agent(name="plan", status="PLAN", raw_suffix="plan")
    question = make_agent(name="question", status="QUESTION", raw_suffix="question")
    done = make_agent(name="done", status="DONE", raw_suffix="done")

    assert _UnreadJumpApp([done])._has_stopped_agent() is False
    assert _UnreadJumpApp([done, plan])._has_stopped_agent() is True
    assert _UnreadJumpApp([question])._has_stopped_agent() is True


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
    app = _UnreadJumpApp(
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
    app = _UnreadJumpApp([oldest, newest], current_idx=0)
    app._unread_completed_agent_ids.update({oldest.identity, newest.identity})

    assert app._jump_to_next_unread_done_agent()

    assert app.current_idx == 1
    assert newest.identity not in app._unread_completed_agent_ids


def test_jump_to_next_unread_done_agent_ignores_running_and_read_done() -> None:
    running = make_agent(name="running", status="RUNNING", raw_suffix="running")
    read_done = make_agent(name="read", status="DONE", raw_suffix="read")
    unread_done = make_agent(name="unread", status="DONE", raw_suffix="unread")
    app = _UnreadJumpApp([running, read_done, unread_done], current_idx=0)
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
    app = _UnreadJumpApp(
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
    app = _UnreadJumpApp([done])
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
    app = _UnreadJumpApp([done], patch_result=False)
    app._unread_completed_agent_ids.add(done.identity)

    assert app._jump_to_next_unread_done_agent()

    assert done.identity not in app._unread_completed_agent_ids
    assert app.refresh_calls == [{"list_changed": True, "defer_detail": True}]


def test_jump_to_next_unread_done_agent_clears_banner_focus_and_refreshes() -> None:
    done = make_agent(name="done", status="DONE")
    app = _UnreadJumpApp([done], current_idx=0)
    app._current_group_key = ("done",)
    app._unread_completed_agent_ids.add(done.identity)

    assert app._jump_to_next_unread_done_agent()

    assert app.current_idx == 0
    assert app._current_group_key is None
    assert done.identity not in app._unread_completed_agent_ids
    assert app.refresh_calls == [{"list_changed": True, "defer_detail": True}]


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
    app = _UnreadJumpApp(
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


def test_jump_to_next_unread_done_agent_finds_non_focused_panel_row() -> None:
    focused = make_agent(name="focused", status="RUNNING", raw_suffix="focused")
    target = make_agent(
        name="target",
        status="PLAN DONE",
        raw_suffix="target",
        tag="chop",
        stop_time=datetime(2026, 5, 7, 12, 0, 0),
    )
    app = _UnreadJumpApp(
        [focused, target],
        current_idx=0,
        with_panels=True,
        focused_key=None,
    )
    assert app._panel_group.panel_keys == [None, "chop"]
    assert app._panel_group.focused_idx == 0
    app._unread_completed_agent_ids.add(target.identity)

    assert app._jump_to_next_unread_done_agent()

    assert app.current_idx == 1
    assert app._panel_group.focused_idx == 1
    assert target.identity not in app._unread_completed_agent_ids
    assert app.patch_calls == []
    assert app.refresh_calls == [{"list_changed": True, "defer_detail": True}]


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
    app = _UnreadJumpApp(
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
    app = _UnreadJumpApp([running, waiting, done, failed], current_idx=0)

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
    app = _UnreadJumpApp(
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
    app = _UnreadJumpApp(
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


def test_manual_unread_guards_per_row_dismissal(
    notification_dismiss: Mock,
) -> None:
    """A manually-unread row is never cleared or dismissed through the
    per-row helper. The user has to explicitly toggle the manual marker off
    before the row can be acknowledged and its notification dismissed.
    """
    agent = make_agent(status="DONE")
    app = _UnreadJumpApp([agent])
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
    app = _UnreadJumpApp([first, second, running])
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
    assert app.refresh_calls == [{"list_changed": True}]
    assert app.patch_calls == []


def test_mark_all_unread_done_agents_read_noops_without_terminal_unread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dismiss = Mock(return_value=0)
    monkeypatch.setattr(
        "sase.notifications.dismiss_agent_completion_notifications_matching_agents",
        dismiss,
    )
    running = make_agent(name="running", status="RUNNING", raw_suffix="running")
    app = _UnreadJumpApp([running])
    app._unread_completed_agent_ids.add(running.identity)

    assert app._mark_all_unread_done_agents_read() == 0

    assert app._unread_completed_agent_ids == {running.identity}
    dismiss.assert_not_called()
    assert app.notification_count_refresh_calls == 0
    assert app.refresh_calls == []
    assert app.patch_calls == []


def test_jump_to_next_unread_done_agent_returns_false_when_no_unread_panels() -> None:
    focused = make_agent(name="focused", status="RUNNING", raw_suffix="focused")
    done = make_agent(name="done", status="DONE", raw_suffix="done", tag="chop")
    app = _UnreadJumpApp(
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
