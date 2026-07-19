"""Selection contract for focused collapsed whole-agent panels."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.actions.agents._selection import AgentSelectionMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_panel_index import build_agent_panel_index
from sase.ace.tui.models.agent_panels import AgentPanelGroup


def _agent(name: str, tag: str | None) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=name,
        project_file="/tmp/sase/sase.sase",
        status="RUNNING",
        start_time=datetime(2026, 7, 17, 12, 0, 0),
        raw_suffix=name,
        tribe=tag,
    )


class _SelectionApp(AgentSelectionMixin):
    def __init__(
        self,
        agents: list[Agent],
        *,
        focused_key: str | None,
        collapsed: set[str | None],
    ) -> None:
        self.current_tab = "agents"
        self._agents = agents
        self._marked_agents = set()
        self._unread_completed_agent_ids = set()
        self._collapsed_panel_keys = collapsed
        self._panel_group = AgentPanelGroup.from_agents(
            agents,
            focused_key=focused_key,
            collapsed_panel_keys=collapsed,
        )
        key = self._panel_group.focused_key
        self.current_idx = next(
            index for index, agent in enumerate(agents) if agent.tribe == key
        )
        self._index = build_agent_panel_index(agents, dismissable_statuses={"DONE"})

    def _agent_panel_index(self):  # type: ignore[no-untyped-def]
        return self._index


def test_focused_collapsed_panel_has_no_selected_agent() -> None:
    agents = [_agent("alpha", "alpha"), _agent("beta", "beta")]
    app = _SelectionApp(agents, focused_key="alpha", collapsed={"alpha"})

    assert app._resolve_focused_collapsed_panel() is not None
    assert app._get_selected_agent() is None
    snapshot = app._focused_tribe_summary()
    assert snapshot is not None
    assert snapshot.label == "@alpha"
    assert snapshot.panel_collapsed is True
    assert [unit.label for unit in snapshot.units] == ["alpha"]


def test_collapsed_nonfocused_panel_does_not_hide_expanded_selection() -> None:
    agents = [_agent("alpha", "alpha"), _agent("beta", "beta")]
    app = _SelectionApp(agents, focused_key="beta", collapsed={"alpha"})

    assert app._resolve_focused_collapsed_panel() is None
    assert app._get_selected_agent() is agents[1]


def test_untagged_collapsed_focus_is_not_confused_with_missing_focus() -> None:
    agents = [_agent("untagged", None), _agent("beta", "beta")]
    app = _SelectionApp(agents, focused_key=None, collapsed={None})
    app.current_idx = 0

    focus = app._resolve_focused_collapsed_panel()
    assert focus is not None
    assert focus.panel_key is None
    assert app._get_selected_agent() is None


def test_resolver_requires_agents_tab_and_live_focused_key() -> None:
    agents = [_agent("alpha", "alpha")]
    app = _SelectionApp(agents, focused_key="alpha", collapsed={"alpha"})

    app.current_tab = "changespecs"
    assert app._resolve_focused_collapsed_panel() is None
    assert app._get_selected_agent() is agents[0]

    app.current_tab = "agents"
    app._panel_group.focused_idx = 5
    assert app._resolve_focused_collapsed_panel() is None
