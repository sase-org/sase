"""Shared helpers for the ``test_node_finder_snapshot*`` test modules.

Public helpers used by more than one ``test_node_finder_snapshot_*`` module
live here under public names so no new module imports a ``_``-prefixed
name from another new module.
"""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.actions.navigation._entry_jump_mode import EntryJumpModeMixin
from sase.ace.tui.models._agent_tree import agent_fold_key
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.models.node_finder import NodeFinderRole
from tests.ace.tui._member_jump_navigation_helpers import JumpHarness

__all__ = [
    "NodeFinderHarness",
    "expand_all_nodes",
    "snapshot_node_rows",
    "snapshot_row_by_name",
    "snapshot_started",
]


def snapshot_started() -> datetime:
    return datetime(2026, 7, 26, 9, 0, 0)


class NodeFinderHarness(JumpHarness, EntryJumpModeMixin):
    """Jump harness plus the query/load owner state the snapshot reads."""

    def __init__(self, complete: list[Agent], container: Agent) -> None:
        super().__init__(complete, container)
        self._agent_search_query = ""
        self._agent_load_state = None
        self._hidden_count = 0
        self.hide_non_run_agents = False

    def _refilter_agents(self, **kwargs: object) -> None:
        super()._refilter_agents(**kwargs)
        if not getattr(self, "_agent_search_query", ""):
            return
        from sase.ace.tui.actions.agents._prospective_clan import (
            apply_active_agent_query,
        )
        from sase.ace.tui.models.agent_panels import AgentPanelGroup

        self._agents = apply_active_agent_query(self, self._agents)
        focused_key = (
            self._panel_group.focused_key
            if getattr(self._panel_group, "panel_keys", None)
            else None
        )
        self._panel_group = AgentPanelGroup.from_agents(
            self._agents,
            focused_key,
            merge_tribe_panels=self._agent_panels_grouped,
        )
        if not self._agents:
            self.current_idx = 0
        else:
            self.current_idx = max(0, min(self.current_idx, len(self._agents) - 1))


def expand_all_nodes(app: NodeFinderHarness, agents: list[Agent]) -> None:
    for agent in agents:
        key = agent_fold_key(agent)
        if key:
            app._fold_manager.expand(key)
            app._fold_manager.expand(key)
    app._refilter_agents()


def snapshot_node_rows(snap) -> list:
    return [row for row in snap.rows if row.role is NodeFinderRole.NODE]


def snapshot_row_by_name(snap, name: str):
    return next(row for row in snapshot_node_rows(snap) if row.name == name)
