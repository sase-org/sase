"""Unread completed-agent row indicator state tests."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sase.ace.tui.actions.agents._loading_finalize import (
    _sync_unread_completed_agents,
)
from sase.ace.tui.actions.event_handlers import EventHandlersMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_panels import AgentPanelGroup, panel_key_per_agent
from sase.ace.tui.widgets.agent_list import AgentList


def _agent(
    *,
    name: str = "demo",
    status: str = "RUNNING",
    raw_suffix: str = "20260507090000",
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=name,
        project_file="/tmp/projects/demo/demo.gp",
        status=status,
        start_time=datetime(2026, 5, 7, 9, 0, 0),
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


class _UnreadFinalizeApp:
    def __init__(self, agents: list[Agent]) -> None:
        self._agents = agents
        self.current_idx = 0
        self._current_group_key: tuple[str, ...] | None = None
        self._unread_completed_agent_ids: set[tuple[AgentType, str, str | None]] = set()
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
