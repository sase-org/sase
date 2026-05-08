"""Unread completed-agent row indicator state tests."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sase.ace.tui.actions.agents._loading_finalize import (
    _sync_unread_completed_agents,
)
from sase.ace.tui.actions.agents._core import AgentsMixinCore
from sase.ace.tui.actions.event_handlers import EventHandlersMixin
from sase.ace.tui.actions.navigation._basic import BasicNavigationMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_panels import AgentPanelGroup, panel_key_per_agent
from sase.ace.tui.widgets.agent_list import AgentList

_DEFAULT_START_TIME = datetime(2026, 5, 7, 9, 0, 0)


def _agent(
    *,
    name: str = "demo",
    status: str = "RUNNING",
    raw_suffix: str = "20260507090000",
    start_time: datetime | None = _DEFAULT_START_TIME,
    stop_time: datetime | None = None,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=name,
        project_file="/tmp/projects/demo/demo.gp",
        status=status,
        start_time=start_time,
        stop_time=stop_time,
        raw_suffix=raw_suffix,
    )


class _SelectionEvent:
    def __init__(
        self,
        *,
        control: AgentList,
        index: int,
        group_key: tuple[str, ...] | None = None,
    ) -> None:
        self.control = control
        self.index = index
        self.attempt_number = None
        self.group_key = group_key


class _SelectionApp(EventHandlersMixin):
    def __init__(self, agents: list[Agent], *, patch_result: bool = True) -> None:
        self.current_tab = "agents"
        self.current_idx = 0
        self.current_attempt_number: int | None = None
        self._agents = agents
        self._agent_panels_grouped = False
        self._panel_group = AgentPanelGroup.from_agents(agents)
        self._current_group_key: tuple[str, ...] | None = None
        self._unread_completed_agent_ids: set[tuple[AgentType, str, str | None]] = set()
        self._manual_unread_agent_ids: set[tuple[AgentType, str, str | None]] = set()
        self._patch_result = patch_result
        self.patch_calls: list[Agent] = []
        self.refresh_calls: list[dict[str, Any]] = []

    def _panel_keys_per_agent(self) -> list[str | None]:
        return panel_key_per_agent(self._agents)

    def _try_patch_agent_row(self, agent: Agent) -> bool:
        self.patch_calls.append(agent)
        return self._patch_result

    def _refresh_agents_display(self, **kwargs: Any) -> None:
        self.refresh_calls.append(kwargs)


def test_agent_row_selection_clears_unread_and_patches_row() -> None:
    agent = _agent(status="DONE")
    app = _SelectionApp([agent])
    app._unread_completed_agent_ids.add(agent.identity)

    app.on_agent_list_selection_changed(
        _SelectionEvent(control=AgentList(id="agent-list-panel"), index=0)
    )

    assert agent.identity not in app._unread_completed_agent_ids
    assert app.patch_calls == [agent]
    assert app.refresh_calls == []


def test_agent_row_selection_refreshes_when_patch_cannot_land() -> None:
    agent = _agent(status="DONE")
    app = _SelectionApp([agent], patch_result=False)
    app._unread_completed_agent_ids.add(agent.identity)

    app.on_agent_list_selection_changed(
        _SelectionEvent(control=AgentList(id="agent-list-panel"), index=0)
    )

    assert agent.identity not in app._unread_completed_agent_ids
    assert app.refresh_calls == [{"list_changed": True, "defer_detail": True}]


def test_same_index_agent_row_selection_clears_stale_banner_focus_unread() -> None:
    agent = _agent(status="DONE")
    app = _SelectionApp([agent])
    app._current_group_key = ("demo",)
    app._unread_completed_agent_ids.add(agent.identity)

    app.on_agent_list_selection_changed(
        _SelectionEvent(control=AgentList(id="agent-list-panel"), index=0)
    )

    assert app.current_idx == 0
    assert app._current_group_key is None
    assert agent.identity not in app._unread_completed_agent_ids


def test_banner_selection_does_not_clear_agent_unread() -> None:
    agent = _agent(status="DONE")
    app = _SelectionApp([agent])
    app._unread_completed_agent_ids.add(agent.identity)

    app.on_agent_list_selection_changed(
        _SelectionEvent(
            control=AgentList(id="agent-list-panel"),
            index=0,
            group_key=("demo",),
        )
    )

    assert agent.identity in app._unread_completed_agent_ids


def test_manual_unread_mouse_selection_preserves_selected_row() -> None:
    agent = _agent(status="DONE")
    app = _SelectionApp([agent])
    app._unread_completed_agent_ids.add(agent.identity)
    app._manual_unread_agent_ids.add(agent.identity)

    app.on_agent_list_selection_changed(
        _SelectionEvent(control=AgentList(id="agent-list-panel"), index=0)
    )

    assert agent.identity in app._unread_completed_agent_ids
    assert agent.identity in app._manual_unread_agent_ids
    assert app.patch_calls == []


def test_manual_unread_mouse_selection_arms_then_acknowledges_on_return() -> None:
    first = _agent(name="first", status="DONE", raw_suffix="first")
    second = _agent(name="second", status="DONE", raw_suffix="second")
    app = _SelectionApp([first, second])
    app._unread_completed_agent_ids.add(first.identity)
    app._manual_unread_agent_ids.add(first.identity)

    app.on_agent_list_selection_changed(
        _SelectionEvent(control=AgentList(id="agent-list-panel"), index=1)
    )

    assert first.identity in app._unread_completed_agent_ids
    assert first.identity not in app._manual_unread_agent_ids

    app.on_agent_list_selection_changed(
        _SelectionEvent(control=AgentList(id="agent-list-panel"), index=0)
    )

    assert first.identity not in app._unread_completed_agent_ids
    assert app.patch_calls == [first]


class _UnreadFinalizeApp:
    def __init__(self, agents: list[Agent]) -> None:
        self._agents = agents
        self.current_idx = 0
        self._current_group_key: tuple[str, ...] | None = None
        self._unread_completed_agent_ids: set[tuple[AgentType, str, str | None]] = set()
        self._manual_unread_agent_ids: set[tuple[AgentType, str, str | None]] = set()
        self._agent_display_status_by_identity: dict[
            tuple[AgentType, str, str | None], str
        ] = {}


def test_finalizer_marks_new_terminal_agent_unread() -> None:
    agent = _agent(status="DONE")
    app = _UnreadFinalizeApp([agent])
    app._agent_display_status_by_identity[agent.identity] = "RUNNING"

    _sync_unread_completed_agents(app, on_agents_tab=False)  # type: ignore[arg-type]

    assert app._unread_completed_agent_ids == {agent.identity}


def test_finalizer_does_not_mark_currently_selected_agent_unread() -> None:
    agent = _agent(status="DONE")
    app = _UnreadFinalizeApp([agent])
    app._agent_display_status_by_identity[agent.identity] = "RUNNING"

    _sync_unread_completed_agents(app, on_agents_tab=True)  # type: ignore[arg-type]

    assert app._unread_completed_agent_ids == set()


def test_finalizer_clears_unread_for_saved_selection_on_agents_tab() -> None:
    agent = _agent(status="DONE")
    app = _UnreadFinalizeApp([agent])
    app._unread_completed_agent_ids.add(agent.identity)
    app._agent_display_status_by_identity[agent.identity] = "DONE"

    _sync_unread_completed_agents(app, on_agents_tab=True)  # type: ignore[arg-type]

    assert app._unread_completed_agent_ids == set()


def test_finalizer_preserves_selected_manually_unread_agent() -> None:
    agent = _agent(status="DONE")
    app = _UnreadFinalizeApp([agent])
    app._unread_completed_agent_ids.add(agent.identity)
    app._manual_unread_agent_ids.add(agent.identity)
    app._agent_display_status_by_identity[agent.identity] = "DONE"

    _sync_unread_completed_agents(app, on_agents_tab=True)  # type: ignore[arg-type]

    assert app._unread_completed_agent_ids == {agent.identity}
    assert app._manual_unread_agent_ids == {agent.identity}


def test_finalizer_does_not_mark_terminal_agent_on_first_seen_load() -> None:
    agent = _agent(status="DONE")
    app = _UnreadFinalizeApp([agent])

    _sync_unread_completed_agents(app, on_agents_tab=False)  # type: ignore[arg-type]

    assert app._unread_completed_agent_ids == set()


def test_finalizer_prunes_unread_identities_no_longer_visible() -> None:
    visible = _agent(name="visible", status="RUNNING", raw_suffix="visible")
    stale = _agent(name="stale", status="DONE", raw_suffix="stale")
    app = _UnreadFinalizeApp([visible])
    app._unread_completed_agent_ids.add(stale.identity)

    _sync_unread_completed_agents(app, on_agents_tab=False)  # type: ignore[arg-type]

    assert app._unread_completed_agent_ids == set()


def test_finalizer_prunes_stale_manual_unread_identities() -> None:
    visible = _agent(name="visible", status="RUNNING", raw_suffix="visible")
    stale = _agent(name="stale", status="DONE", raw_suffix="stale")
    app = _UnreadFinalizeApp([visible])
    app._unread_completed_agent_ids.add(stale.identity)
    app._manual_unread_agent_ids.add(stale.identity)

    _sync_unread_completed_agents(app, on_agents_tab=False)  # type: ignore[arg-type]

    assert app._unread_completed_agent_ids == set()
    assert app._manual_unread_agent_ids == set()


class _UnreadJumpApp(AgentsMixinCore, BasicNavigationMixin):
    def __init__(
        self,
        agents: list[Agent],
        *,
        visible: list[int] | None = None,
        stops: list[tuple[str, int | tuple[str, ...]]] | None = None,
        current_idx: int = 0,
        patch_result: bool = True,
    ) -> None:
        self._agents = agents
        self.current_idx = current_idx
        self.current_attempt_number: int | None = 3
        self._current_group_key: tuple[str, ...] | None = None
        self._unread_completed_agent_ids: set[tuple[AgentType, str, str | None]] = set()
        self._manual_unread_agent_ids: set[tuple[AgentType, str, str | None]] = set()
        self._visible = visible
        self._stops = stops
        self._patch_result = patch_result
        self.patch_calls: list[Agent] = []
        self.refresh_calls: list[dict[str, Any]] = []
        self.debounced_refresh_calls = 0

    def _agents_visible_order(self) -> list[int]:
        if self._visible is not None:
            return self._visible
        return list(range(len(self._agents)))

    def _panel_navigation_stops(self) -> list[tuple[str, int | tuple[str, ...]]]:
        if self._stops is not None:
            return self._stops
        return [("agent", idx) for idx in self._agents_visible_order()]

    def _try_patch_agent_row(self, agent: Agent) -> bool:
        self.patch_calls.append(agent)
        return self._patch_result

    def _refresh_agents_display(self, **kwargs: Any) -> None:
        self.refresh_calls.append(kwargs)

    def _refresh_agents_display_debounced(self) -> None:
        self.debounced_refresh_calls += 1


def test_toggle_agent_unread_marks_selected_row_without_moving() -> None:
    agent = _agent(status="RUNNING")
    app = _UnreadJumpApp([agent])

    app._toggle_agent_unread()

    assert app.current_idx == 0
    assert app._unread_completed_agent_ids == {agent.identity}
    assert app._manual_unread_agent_ids == {agent.identity}
    assert app.patch_calls == [agent]
    assert app.refresh_calls == []


def test_toggle_agent_unread_again_marks_selected_row_read() -> None:
    agent = _agent(status="DONE")
    app = _UnreadJumpApp([agent])
    app._unread_completed_agent_ids.add(agent.identity)
    app._manual_unread_agent_ids.add(agent.identity)

    app._toggle_agent_unread()

    assert app._unread_completed_agent_ids == set()
    assert app._manual_unread_agent_ids == set()
    assert app.patch_calls == [agent]


def test_toggle_agent_unread_refreshes_when_patch_fails() -> None:
    agent = _agent(status="DONE")
    app = _UnreadJumpApp([agent], patch_result=False)

    app._toggle_agent_unread()

    assert app.refresh_calls == [{"list_changed": True, "defer_detail": True}]


def test_toggle_agent_unread_ignores_focused_banner() -> None:
    agent = _agent(status="DONE")
    app = _UnreadJumpApp([agent])
    app._current_group_key = ("demo",)

    app._toggle_agent_unread()

    assert app._unread_completed_agent_ids == set()
    assert app._manual_unread_agent_ids == set()
    assert app.patch_calls == []


def test_navigation_away_from_manual_unread_arms_it_without_clearing() -> None:
    first = _agent(name="first", status="DONE", raw_suffix="first")
    second = _agent(name="second", status="DONE", raw_suffix="second")
    app = _UnreadJumpApp([first, second])
    app._unread_completed_agent_ids.add(first.identity)
    app._manual_unread_agent_ids.add(first.identity)

    app._navigate_agents_panel(1)

    assert app.current_idx == 1
    assert first.identity in app._unread_completed_agent_ids
    assert first.identity not in app._manual_unread_agent_ids
    assert app.patch_calls == []


def test_navigation_back_to_armed_manual_unread_acknowledges_it() -> None:
    first = _agent(name="first", status="DONE", raw_suffix="first")
    second = _agent(name="second", status="DONE", raw_suffix="second")
    app = _UnreadJumpApp([first, second], current_idx=1)
    app._unread_completed_agent_ids.add(first.identity)

    app._navigate_agents_panel(-1)

    assert app.current_idx == 0
    assert first.identity not in app._unread_completed_agent_ids
    assert app.patch_calls == [first]


def test_jump_to_next_unread_done_agent_uses_completion_recency_and_wraps() -> None:
    older = _agent(
        name="older",
        status="DONE",
        raw_suffix="older",
        stop_time=datetime(2026, 5, 7, 10, 0, 0),
    )
    newest = _agent(
        name="newest",
        status="DONE",
        raw_suffix="newest",
        stop_time=datetime(2026, 5, 7, 12, 0, 0),
    )
    running = _agent(
        name="running",
        status="RUNNING",
        raw_suffix="running",
        stop_time=datetime(2026, 5, 7, 13, 0, 0),
    )
    middle = _agent(
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

    assert app._jump_to_next_unread_done_agent()
    assert app.current_idx == 3

    assert app._jump_to_next_unread_done_agent()
    assert app.current_idx == 0

    assert app._jump_to_next_unread_done_agent()
    assert app.current_idx == 1


def test_jump_to_next_unread_done_agent_ignores_running_and_read_done() -> None:
    running = _agent(name="running", status="RUNNING", raw_suffix="running")
    read_done = _agent(name="read", status="DONE", raw_suffix="read")
    unread_done = _agent(name="unread", status="DONE", raw_suffix="unread")
    app = _UnreadJumpApp([running, read_done, unread_done], current_idx=0)
    app._unread_completed_agent_ids.add(unread_done.identity)

    assert app._jump_to_next_unread_done_agent()
    assert app.current_idx == 2
    assert app.patch_calls == [unread_done]


def test_jump_to_next_unread_done_agent_uses_start_time_when_stop_time_missing() -> (
    None
):
    fallback_newest = _agent(
        name="fallback",
        status="DONE",
        raw_suffix="fallback",
        start_time=datetime(2026, 5, 7, 12, 0, 0),
        stop_time=None,
    )
    stopped_older = _agent(
        name="stopped",
        status="DONE",
        raw_suffix="stopped",
        start_time=datetime(2026, 5, 7, 8, 0, 0),
        stop_time=datetime(2026, 5, 7, 11, 0, 0),
    )
    missing_time = _agent(
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

    assert app._jump_to_next_unread_done_agent()
    assert app.current_idx == 0

    assert app._jump_to_next_unread_done_agent()
    assert app.current_idx == 1


def test_jump_to_next_unread_done_agent_preserves_target_unread_state() -> None:
    done = _agent(name="done", status="DONE")
    app = _UnreadJumpApp([done])
    app._unread_completed_agent_ids.add(done.identity)

    assert app._jump_to_next_unread_done_agent()

    assert done.identity in app._unread_completed_agent_ids
    assert app.current_attempt_number is None
    assert app.refresh_calls == []


def test_jump_to_next_unread_done_agent_falls_back_to_full_refresh() -> None:
    done = _agent(name="done", status="FAILED")
    app = _UnreadJumpApp([done], patch_result=False)
    app._unread_completed_agent_ids.add(done.identity)

    assert app._jump_to_next_unread_done_agent()

    assert app.refresh_calls == [{"list_changed": True, "defer_detail": True}]


def test_jump_to_next_unread_done_agent_clears_banner_focus_and_refreshes() -> None:
    done = _agent(name="done", status="DONE")
    app = _UnreadJumpApp([done], current_idx=0)
    app._current_group_key = ("done",)
    app._unread_completed_agent_ids.add(done.identity)

    assert app._jump_to_next_unread_done_agent()

    assert app.current_idx == 0
    assert app._current_group_key is None
    assert app.debounced_refresh_calls == 1


def test_jump_to_next_unread_done_agent_starts_at_newest_from_focused_banner() -> None:
    first = _agent(
        name="first",
        status="DONE",
        raw_suffix="first",
        stop_time=datetime(2026, 5, 7, 10, 0, 0),
    )
    second = _agent(
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
