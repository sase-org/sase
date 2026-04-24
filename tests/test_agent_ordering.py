"""Tests for custom ordering in the Agents tab."""

from __future__ import annotations

from unittest.mock import patch

from sase.ace.tui.actions.agents._loading_helpers import apply_custom_order
from sase.ace.tui.actions.agents._ordering import AgentOrderingMixin
from sase.ace.tui.models.agent import Agent, AgentType


def _agent(
    name: str,
    suffix: str,
    *,
    agent_type: AgentType = AgentType.RUNNING,
    workflow: str | None = None,
    parent_timestamp: str | None = None,
    parent_workflow: str | None = None,
) -> Agent:
    return Agent(
        agent_type=agent_type,
        cl_name=name,
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=None,
        raw_suffix=suffix,
        workflow=workflow,
        parent_timestamp=parent_timestamp,
        parent_workflow=parent_workflow,
    )


def _names(agents: list[Agent]) -> list[str]:
    return [agent.cl_name for agent in agents]


def test_apply_custom_order_keeps_new_top_level_agents_first() -> None:
    old_a = _agent("old-a", "old-a")
    old_b = _agent("old-b", "old-b")
    fresh = _agent("fresh", "fresh")

    ordered = apply_custom_order(
        [fresh, old_b, old_a],
        [old_a.identity, old_b.identity],
    )

    assert _names(ordered) == ["fresh", "old-a", "old-b"]


def test_apply_custom_order_preserves_multiple_new_agent_order() -> None:
    old_a = _agent("old-a", "old-a")
    old_b = _agent("old-b", "old-b")
    fresh_a = _agent("fresh-a", "fresh-a")
    fresh_b = _agent("fresh-b", "fresh-b")

    ordered = apply_custom_order(
        [fresh_a, old_b, fresh_b, old_a],
        [old_a.identity, old_b.identity],
    )

    assert _names(ordered) == ["fresh-a", "fresh-b", "old-a", "old-b"]


def test_apply_custom_order_keeps_workflow_children_with_parent() -> None:
    fresh_parent = _agent(
        "fresh-parent",
        "fresh-parent-ts",
        agent_type=AgentType.WORKFLOW,
        workflow="fresh-workflow",
    )
    fresh_child = _agent(
        "fresh-child",
        "fresh-child-ts",
        parent_timestamp="fresh-parent-ts",
        parent_workflow="fresh-workflow",
    )
    old_parent = _agent(
        "old-parent",
        "old-parent-ts",
        agent_type=AgentType.WORKFLOW,
        workflow="old-workflow",
    )
    old_child = _agent(
        "old-child",
        "old-child-ts",
        parent_timestamp="old-parent-ts",
        parent_workflow="old-workflow",
    )

    ordered = apply_custom_order(
        [old_parent, old_child, fresh_parent, fresh_child],
        [old_parent.identity],
    )

    assert _names(ordered) == [
        "fresh-parent",
        "fresh-child",
        "old-parent",
        "old-child",
    ]


class _OrderingApp(AgentOrderingMixin):
    def __init__(
        self,
        agents: list[Agent],
        custom_order: list[tuple[AgentType, str, str | None]],
    ) -> None:
        self.current_tab = "agents"
        self.current_idx = 0
        self._agents = agents
        self._agent_custom_order = custom_order
        self.panel_indices_built = False
        self.display_refreshed = False

    def _get_selected_agent(self) -> Agent | None:
        return self._agents[self.current_idx]

    def _active_panel_indices(self) -> list[int]:
        return list(range(len(self._agents)))

    def _build_panel_indices(self) -> None:
        self.panel_indices_built = True

    def _refresh_agents_display(self, *, list_changed: bool) -> None:
        self.display_refreshed = list_changed


def test_move_agent_rebuilds_order_for_fresh_entry_before_swapping() -> None:
    old_a = _agent("old-a", "old-a")
    old_b = _agent("old-b", "old-b")
    fresh = _agent("fresh", "fresh")
    app = _OrderingApp([fresh, old_a, old_b], [old_a.identity, old_b.identity])

    with patch("sase.ace.agent_order.save_agent_order") as save_agent_order:
        app._move_agent(1)

    assert _names(app._agents) == ["old-a", "fresh", "old-b"]
    assert app._agent_custom_order == [old_a.identity, fresh.identity, old_b.identity]
    save_agent_order.assert_called_once_with(app._agent_custom_order)
    assert app.current_idx == 1
    assert app.panel_indices_built is True
    assert app.display_refreshed is True
