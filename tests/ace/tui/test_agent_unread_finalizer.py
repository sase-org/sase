"""Unread agent finalization tests."""

from __future__ import annotations

from sase.ace.tui.actions.agents._loading_finalize import (
    _sync_unread_completed_agents,
)
from sase.ace.tui.actions.agents._core import AgentsMixinCore
from sase.ace.tui.models.agent import Agent, AgentType

from ._agent_unread_helpers import make_agent


class _UnreadFinalizeApp(AgentsMixinCore):
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
    agent = make_agent(status="DONE")
    app = _UnreadFinalizeApp([agent])
    app._agent_display_status_by_identity[agent.identity] = "RUNNING"

    _sync_unread_completed_agents(app, on_agents_tab=False)  # type: ignore[arg-type]

    assert app._unread_completed_agent_ids == {agent.identity}


def test_finalizer_marks_new_plan_done_agent_unread() -> None:
    agent = make_agent(status="PLAN DONE")
    app = _UnreadFinalizeApp([agent])
    app._agent_display_status_by_identity[agent.identity] = "RUNNING"

    _sync_unread_completed_agents(app, on_agents_tab=False)  # type: ignore[arg-type]

    assert app._unread_completed_agent_ids == {agent.identity}


def test_finalizer_does_not_mark_currently_selected_agent_unread() -> None:
    agent = make_agent(status="DONE")
    app = _UnreadFinalizeApp([agent])
    app._agent_display_status_by_identity[agent.identity] = "RUNNING"

    _sync_unread_completed_agents(app, on_agents_tab=True)  # type: ignore[arg-type]

    assert app._unread_completed_agent_ids == set()


def test_finalizer_clears_unread_for_saved_selection_on_agents_tab() -> None:
    agent = make_agent(status="DONE")
    app = _UnreadFinalizeApp([agent])
    app._unread_completed_agent_ids.add(agent.identity)
    app._agent_display_status_by_identity[agent.identity] = "DONE"

    _sync_unread_completed_agents(app, on_agents_tab=True)  # type: ignore[arg-type]

    assert app._unread_completed_agent_ids == set()


def test_finalizer_preserves_selected_manually_unread_agent() -> None:
    agent = make_agent(status="DONE")
    app = _UnreadFinalizeApp([agent])
    app._unread_completed_agent_ids.add(agent.identity)
    app._manual_unread_agent_ids.add(agent.identity)
    app._agent_display_status_by_identity[agent.identity] = "DONE"

    _sync_unread_completed_agents(app, on_agents_tab=True)  # type: ignore[arg-type]

    assert app._unread_completed_agent_ids == {agent.identity}
    assert app._manual_unread_agent_ids == {agent.identity}


def test_finalizer_does_not_mark_terminal_agent_on_first_seen_load() -> None:
    agent = make_agent(status="DONE")
    app = _UnreadFinalizeApp([agent])

    _sync_unread_completed_agents(app, on_agents_tab=False)  # type: ignore[arg-type]

    assert app._unread_completed_agent_ids == set()


def test_finalizer_prunes_unread_identities_no_longer_visible() -> None:
    visible = make_agent(name="visible", status="RUNNING", raw_suffix="visible")
    stale = make_agent(name="stale", status="DONE", raw_suffix="stale")
    app = _UnreadFinalizeApp([visible])
    app._unread_completed_agent_ids.add(stale.identity)

    _sync_unread_completed_agents(app, on_agents_tab=False)  # type: ignore[arg-type]

    assert app._unread_completed_agent_ids == set()


def test_finalizer_prunes_stale_manual_unread_identities() -> None:
    visible = make_agent(name="visible", status="RUNNING", raw_suffix="visible")
    stale = make_agent(name="stale", status="DONE", raw_suffix="stale")
    app = _UnreadFinalizeApp([visible])
    app._unread_completed_agent_ids.add(stale.identity)
    app._manual_unread_agent_ids.add(stale.identity)

    _sync_unread_completed_agents(app, on_agents_tab=False)  # type: ignore[arg-type]

    assert app._unread_completed_agent_ids == set()
    assert app._manual_unread_agent_ids == set()
