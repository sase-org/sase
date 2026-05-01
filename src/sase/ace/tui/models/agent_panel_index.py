"""O(1) panel / lookup index over an agents list.

Built once whenever ``_agents`` is replaced (or when the active grouping /
fold signature changes) and reused across every j/k keystroke so the
panel-aware refresh paths don't rescan ``self._agents`` to derive panel
slices, non-child position counts, or dismissable totals.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from .agent import Agent
from .agent_panels import PanelKey, panel_key_per_agent


@dataclass
class PanelSlice:
    """The agents that belong to a single panel, with reverse-index maps."""

    agents: list[Agent] = field(default_factory=list)
    global_indices: list[int] = field(default_factory=list)
    global_to_local: dict[int, int] = field(default_factory=dict)


@dataclass
class AgentPanelIndex:
    """O(1) lookup of panel slices, non-child positions, and counts."""

    keys_per_agent: list[PanelKey] = field(default_factory=list)
    panels: dict[PanelKey, PanelSlice] = field(default_factory=dict)
    non_child_indices: list[int] = field(default_factory=list)
    completed_count: int = 0

    def slice_for(self, key: PanelKey) -> PanelSlice:
        return self.panels.get(key, PanelSlice())

    def local_idx_for(self, key: PanelKey, global_idx: int) -> int:
        """Return the panel-local index of ``global_idx`` in panel ``key``.

        Returns ``-1`` when the global index does not belong to that panel
        (matches the sentinel used by ``AgentList.update_highlight``).
        """
        return self.panels.get(key, PanelSlice()).global_to_local.get(global_idx, -1)

    def non_child_position(self, current_idx: int) -> int:
        """1-based non-child position of ``current_idx`` for the info panel."""
        from bisect import bisect_right

        if not self.non_child_indices and not self.keys_per_agent:
            return 0
        return bisect_right(self.non_child_indices, current_idx)

    @property
    def non_child_total(self) -> int:
        return len(self.non_child_indices)


def build_agent_panel_index(
    agents: list[Agent],
    *,
    dismissable_statuses: Iterable[str],
) -> AgentPanelIndex:
    """Build an :class:`AgentPanelIndex` for ``agents``."""
    keys_per_agent = panel_key_per_agent(agents)
    panels: dict[PanelKey, PanelSlice] = {}
    non_child_indices: list[int] = []
    dismissable = set(dismissable_statuses)
    completed_count = 0
    for i, agent in enumerate(agents):
        key = keys_per_agent[i]
        slot = panels.get(key)
        if slot is None:
            slot = PanelSlice()
            panels[key] = slot
        local = len(slot.agents)
        slot.agents.append(agent)
        slot.global_indices.append(i)
        slot.global_to_local[i] = local
        if not agent.is_workflow_child:
            non_child_indices.append(i)
        if agent.status in dismissable:
            completed_count += 1
    return AgentPanelIndex(
        keys_per_agent=keys_per_agent,
        panels=panels,
        non_child_indices=non_child_indices,
        completed_count=completed_count,
    )
