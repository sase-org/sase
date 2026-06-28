"""Visible neighbor index for Agents-tab rows (dotted-name hoods)."""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Iterable
from dataclasses import dataclass, field

from .agent import Agent
from .agent_panels import agent_is_rendered_in_agents_panel


def agent_name_key(agent: Agent) -> str | None:
    """Return a case-folded valid dotted agent name key."""
    name = agent.agent_name
    if not name:
        return None
    parts = name.split(".")
    if any(not part for part in parts):
        return None
    return name.casefold()


def is_agent_descendant(name: str | None, ancestor: str | None) -> bool:
    """Return True when ``name`` is nested under ``ancestor`` by dotted name."""
    if not name or not ancestor:
        return False
    candidate_parts = name.split(".")
    ancestor_parts = ancestor.split(".")
    if any(not part for part in candidate_parts + ancestor_parts):
        return False
    candidate = name.casefold()
    parent = ancestor.casefold()
    return candidate.startswith(f"{parent}.")


def agent_hood(agent: Agent) -> str | None:
    """Return the case-folded hood key for ``agent``.

    An agent's *hood* is its immediate dotted namespace: everything in
    ``Agent.agent_name`` up to (but not including) the final dotted
    segment.  ``foo.bar`` lives in the ``foo`` hood and ``foo.bar.baz``
    lives in the ``foo.bar`` hood, regardless of whether an agent named
    ``foo.bar`` exists.

    Dotless names (e.g. ``foo``) have no named hood in this V1, so they do
    not participate in hood-neighbor navigation.  Names with any empty
    dotted segment (``.bar``, ``foo.``, ``foo..bar``) are malformed and
    likewise produce no hood.
    """
    name = agent_name_key(agent)
    if name is None:
        return None
    hood, sep, last = name.rpartition(".")
    if not sep or not hood or not last:
        return None
    return hood


@dataclass(frozen=True)
class AgentNeighborRow:
    """One visible Agents-tab row used to build a neighbor index."""

    global_idx: int
    panel_idx: int
    agent: Agent
    hood: str | None = None


@dataclass(frozen=True)
class AgentNeighborIndex:
    """Render-order neighbor lookup for currently visible Agents-tab rows."""

    _neighbors_by_global_idx: dict[int, tuple[int, ...]] = field(default_factory=dict)
    _descendants_by_global_idx: dict[int, tuple[int, ...]] = field(default_factory=dict)
    _descendant_count_by_global_idx: dict[int, int] = field(default_factory=dict)
    _panel_idx_by_global_idx: dict[int, int] = field(default_factory=dict)

    @classmethod
    def from_visible_rows(
        cls,
        rows: list[AgentNeighborRow],
        dismissed_agents: Iterable[Agent] = (),
    ) -> AgentNeighborIndex:
        """Build an index from visible rows in actual render order."""
        panel_idx_by_global_idx: dict[int, int] = {}
        name_by_global_idx: dict[int, str] = {}
        hood_by_global_idx: dict[int, str] = {}
        members_by_hood: dict[str, list[int]] = {}

        for row in rows:
            panel_idx_by_global_idx[row.global_idx] = row.panel_idx
            if not agent_is_rendered_in_agents_panel(row.agent):
                continue
            name = agent_name_key(row.agent)
            if name is None:
                continue
            name_by_global_idx[row.global_idx] = name
            hood = row.hood if row.hood is not None else agent_hood(row.agent)
            if hood is None:
                continue
            hood_by_global_idx[row.global_idx] = hood
            members_by_hood.setdefault(hood, []).append(row.global_idx)

        neighbors_by_global_idx: dict[int, tuple[int, ...]] = {}
        for global_idx, hood in hood_by_global_idx.items():
            neighbors_by_global_idx[global_idx] = tuple(
                idx for idx in members_by_hood[hood] if idx != global_idx
            )

        visible_name_records = sorted(
            (name, global_idx) for global_idx, name in name_by_global_idx.items()
        )
        visible_names = [name for name, _idx in visible_name_records]
        dismissed_names = [
            name
            for agent in dismissed_agents
            if (name := agent_name_key(agent)) is not None
        ]
        all_names = sorted([*visible_names, *dismissed_names])

        descendants_by_global_idx: dict[int, tuple[int, ...]] = {}
        descendant_count_by_global_idx: dict[int, int] = {}
        for global_idx, name in name_by_global_idx.items():
            prefix = f"{name}."
            all_start, all_end = _prefix_range(all_names, prefix)
            descendant_count_by_global_idx[global_idx] = all_end - all_start

            visible_start, visible_end = _prefix_range(visible_names, prefix)
            descendants = tuple(
                idx for _name, idx in visible_name_records[visible_start:visible_end]
            )
            if descendants:
                descendants_by_global_idx[global_idx] = descendants

        return cls(
            _neighbors_by_global_idx=neighbors_by_global_idx,
            _descendants_by_global_idx=descendants_by_global_idx,
            _descendant_count_by_global_idx=descendant_count_by_global_idx,
            _panel_idx_by_global_idx=panel_idx_by_global_idx,
        )

    def neighbors_for(self, global_idx: int) -> tuple[int, ...]:
        """Return visible neighbor global indices for ``global_idx``."""
        return self._neighbors_by_global_idx.get(global_idx, ())

    def descendants_for(self, global_idx: int) -> tuple[int, ...]:
        """Return visible descendant global indices for ``global_idx``."""
        return self._descendants_by_global_idx.get(global_idx, ())

    def neighbor_count(self, global_idx: int) -> int:
        """Return the number of visible neighbors for ``global_idx``."""
        return len(self.neighbors_for(global_idx))

    def descendant_count(self, global_idx: int) -> int:
        """Return visible plus dismissed descendant count for ``global_idx``."""
        return self._descendant_count_by_global_idx.get(global_idx, 0)

    def panel_idx_for(self, global_idx: int) -> int | None:
        """Return the rendered panel index containing ``global_idx``."""
        return self._panel_idx_by_global_idx.get(global_idx)


def _prefix_range(names: list[str], prefix: str) -> tuple[int, int]:
    """Return the contiguous sorted range of names starting with ``prefix``."""
    start = bisect_left(names, prefix)
    end = bisect_left(names, prefix + chr(0x10FFFF))
    return start, end
