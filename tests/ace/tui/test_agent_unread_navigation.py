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
    agent = make_agent(status="DONE")
    app = _UnreadJumpApp([agent])
    app._unread_completed_agent_ids.add(agent.identity)
    app._manual_unread_agent_ids.add(agent.identity)

    app._toggle_agent_unread()

    assert app._unread_completed_agent_ids == set()
    assert app._manual_unread_agent_ids == set()
    assert app.patch_calls == [agent]
    notification_dismiss.assert_not_called()
    assert app.notification_count_refresh_calls == 0


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
    done = make_agent(name="done", status="PLAN DONE")
    app = _UnreadJumpApp([done])
    app._unread_completed_agent_ids.add(done.identity)

    assert app._jump_to_next_unread_done_agent()

    assert done.identity not in app._unread_completed_agent_ids
    assert app.current_attempt_number is None
    assert app.patch_calls == [done]
    assert app.refresh_calls == []
    notification_dismiss.assert_not_called()
    assert app.notification_count_refresh_calls == 0


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


def test_manual_unread_does_not_block_global_completion_dismissal(
    notification_dismiss: Mock,
) -> None:
    """Phase 3 regression: per-row unread acknowledgement is independent of
    notification dismissal. A manually-unread row stays highlighted (the
    per-row helper returns False) but no longer holds a completion
    notification hostage — the bulk Agents-tab dismissal (Phase 2) clears
    completion notifications regardless of manual-unread state because it
    never consults ``_manual_unread_agent_ids``.
    """
    agent = make_agent(status="DONE")
    app = _UnreadJumpApp([agent])
    app._unread_completed_agent_ids.add(agent.identity)
    app._manual_unread_agent_ids.add(agent.identity)

    # The per-row helper preserves manual unread and never dismisses.
    assert not app._clear_agent_unread(agent)
    assert agent.identity in app._unread_completed_agent_ids
    assert agent.identity in app._manual_unread_agent_ids
    notification_dismiss.assert_not_called()
    assert app.notification_count_refresh_calls == 0

    # Acknowledgement on the manual-unread row leaves it visually unread and
    # still does not dismiss its notification through the per-row path.
    assert not app._acknowledge_agent_unread(agent)
    assert agent.identity in app._unread_completed_agent_ids
    notification_dismiss.assert_not_called()


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
