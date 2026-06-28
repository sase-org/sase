"""Visible neighbor index for Agents-tab rows (dotted-name hoods)."""

from __future__ import annotations

from dataclasses import dataclass, field

from .agent import Agent
from .agent_panels import agent_is_rendered_in_agents_panel


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
    name = agent.agent_name
    if not name:
        return None
    hood, sep, last = name.rpartition(".")
    if not sep or not hood or not last:
        return None
    if any(not segment for segment in hood.split(".")):
        return None
    return hood.casefold()


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
    _panel_idx_by_global_idx: dict[int, int] = field(default_factory=dict)

    @classmethod
    def from_visible_rows(cls, rows: list[AgentNeighborRow]) -> AgentNeighborIndex:
        """Build an index from visible rows in actual render order."""
        panel_idx_by_global_idx: dict[int, int] = {}
        hood_by_global_idx: dict[int, str] = {}
        members_by_hood: dict[str, list[int]] = {}

        for row in rows:
            panel_idx_by_global_idx[row.global_idx] = row.panel_idx
            if not agent_is_rendered_in_agents_panel(row.agent):
                continue
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

        return cls(
            _neighbors_by_global_idx=neighbors_by_global_idx,
            _panel_idx_by_global_idx=panel_idx_by_global_idx,
        )

    def neighbors_for(self, global_idx: int) -> tuple[int, ...]:
        """Return visible neighbor global indices for ``global_idx``."""
        return self._neighbors_by_global_idx.get(global_idx, ())

    def neighbor_count(self, global_idx: int) -> int:
        """Return the number of visible neighbors for ``global_idx``."""
        return len(self.neighbors_for(global_idx))

    def panel_idx_for(self, global_idx: int) -> int | None:
        """Return the rendered panel index containing ``global_idx``."""
        return self._panel_idx_by_global_idx.get(global_idx)
