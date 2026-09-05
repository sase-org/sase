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
from ._agent_tree import agent_is_tree_child
from .agent_panels import (
    PanelKey,
    agent_is_rendered_in_agents_panel,
    panel_key_per_agent,
)


@dataclass
class _PanelSlice:
    """The agents that belong to a single panel, with reverse-index maps."""

    agents: list[Agent] = field(default_factory=list)
    global_indices: list[int] = field(default_factory=list)
    global_to_local: dict[int, int] = field(default_factory=dict)


@dataclass
class AgentPanelIndex:
    """O(1) lookup of panel slices, non-child positions, and counts."""

    keys_per_agent: list[PanelKey] = field(default_factory=list)
    panels: dict[PanelKey, _PanelSlice] = field(default_factory=dict)
    non_child_indices: list[int] = field(default_factory=list)
    completed_count: int = 0
    hidden_starting_indices: list[int] = field(default_factory=list)

    def slice_for(self, key: PanelKey) -> _PanelSlice:
        return self.panels.get(key, _PanelSlice())

    def local_idx_for(self, key: PanelKey, global_idx: int) -> int:
        """Return the panel-local index of ``global_idx`` in panel ``key``.

        Returns ``-1`` when the global index does not belong to that panel
        (matches the sentinel used by ``AgentList.update_highlight``).
        """
        return self.panels.get(key, _PanelSlice()).global_to_local.get(global_idx, -1)

    def non_child_position(self, current_idx: int) -> int:
        """1-based non-child position of ``current_idx`` for the info panel."""
        from bisect import bisect_right

        if not self.non_child_indices and not self.keys_per_agent:
            return 0
        return bisect_right(self.non_child_indices, current_idx)

    @property
    def non_child_total(self) -> int:
        return len(self.non_child_indices)

    @property
    def top_level_total(self) -> int:
        """Total top-level rows, including hidden STARTING rows.

        ``non_child_total`` counts only the rendered/selectable top-level
        rows and drives row position and navigation semantics. The
        info-panel headline additionally includes transient top-level
        STARTING rows: they are hidden from the panel slices but still
        contribute to the displayed agent total. ``hidden_starting_indices``
        already excludes workflow children, so this never double-counts.
        """
        return len(self.non_child_indices) + len(self.hidden_starting_indices)


def build_agent_panel_index(
    agents: list[Agent],
    *,
    dismissable_statuses: Iterable[str],
    merge_tribe_panels: bool = False,
) -> AgentPanelIndex:
    """Build an :class:`AgentPanelIndex` for ``agents``."""
    keys_per_agent = panel_key_per_agent(agents, merge_tribe_panels=merge_tribe_panels)
    panels: dict[PanelKey, _PanelSlice] = {}
    non_child_indices: list[int] = []
    hidden_starting_indices: list[int] = []
    dismissable = set(dismissable_statuses)
    completed_identities: set[tuple[object, str, str | None]] = set()
    for i, agent in enumerate(agents):
        key = keys_per_agent[i]
        if not agent_is_rendered_in_agents_panel(agent):
            if not agent_is_tree_child(agent):
                hidden_starting_indices.append(i)
            continue
        slot = panels.get(key)
        if slot is None:
            slot = _PanelSlice()
            panels[key] = slot
        local = len(slot.agents)
        slot.agents.append(agent)
        slot.global_indices.append(i)
        slot.global_to_local[i] = local
        if not agent_is_tree_child(agent):
            non_child_indices.append(i)
        completed_candidates = (
            tuple(agent.runtime_children) if agent.is_clan_container else (agent,)
        )
        for candidate in completed_candidates:
            if candidate.status in dismissable:
                completed_identities.add(candidate.identity)
    return AgentPanelIndex(
        keys_per_agent=keys_per_agent,
        panels=panels,
        non_child_indices=non_child_indices,
        completed_count=len(completed_identities),
        hidden_starting_indices=hidden_starting_indices,
    )
