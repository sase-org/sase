"""Visible kinship index for Agents-tab rows."""

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
    """Return True when ``name`` follows ``ancestor`` at a name boundary."""
    if not name or not ancestor:
        return False
    candidate_parts = name.split(".")
    ancestor_parts = ancestor.split(".")
    if any(not part for part in candidate_parts + ancestor_parts):
        return False
    candidate = name.casefold()
    parent = ancestor.casefold()
    return candidate.startswith((f"{parent}.", f"{parent}--"))


def agent_hood(agent: Agent) -> str | None:
    """Return the case-folded hood key for ``agent``.

    An agent's *hood* is its immediate dotted namespace: everything in
    ``Agent.agent_name`` up to (but not including) the final dotted
    segment.  ``foo.bar`` lives in the ``foo`` hood and ``foo.bar.baz``
    lives in the ``foo.bar`` hood, regardless of whether an agent named
    ``foo.bar`` exists.

    Dotless names (e.g. ``foo``) have no immediate parent hood, so this helper
    returns ``None`` for them; :class:`AgentNeighborIndex` still includes their
    full name as an own-name hood.  Names with any empty dotted segment
    (``.bar``, ``foo.``, ``foo..bar``) are malformed and produce no hood.
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
    _hood_neighbor_groups_by_global_idx: dict[
        int, tuple[tuple[str, tuple[int, ...]], ...]
    ] = field(default_factory=dict)
    _ancestors_by_global_idx: dict[int, tuple[int, ...]] = field(default_factory=dict)
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
        visible_indices_by_name: dict[str, list[int]] = {}
        hood_chain_by_global_idx: dict[int, tuple[str, ...]] = {}
        members_by_hood: dict[str, list[int]] = {}

        for row in rows:
            panel_idx_by_global_idx[row.global_idx] = row.panel_idx
            if not agent_is_rendered_in_agents_panel(row.agent):
                continue
            name = agent_name_key(row.agent)
            if name is None:
                continue
            name_by_global_idx[row.global_idx] = name
            visible_indices_by_name.setdefault(name, []).append(row.global_idx)
            hood_chain = _agent_hood_chain(name)
            hood_chain_by_global_idx[row.global_idx] = hood_chain
            for hood in hood_chain:
                members_by_hood.setdefault(hood, []).append(row.global_idx)

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
            all_ranges = _descendant_ranges(all_names, name)
            descendant_count_by_global_idx[global_idx] = sum(
                end - start for start, end in all_ranges
            )

            visible_ranges = _descendant_ranges(visible_names, name)
            descendant_records = sorted(
                record
                for start, end in visible_ranges
                for record in visible_name_records[start:end]
            )
            descendants = tuple(idx for _name, idx in descendant_records)
            if descendants:
                descendants_by_global_idx[global_idx] = descendants

        ancestors_by_global_idx: dict[int, tuple[int, ...]] = {}
        for global_idx, name in name_by_global_idx.items():
            ancestors: list[int] = []
            for prefix in _agent_boundary_prefixes(name):
                ancestors.extend(visible_indices_by_name.get(prefix, ()))
            if ancestors:
                ancestors_by_global_idx[global_idx] = tuple(
                    idx for idx in ancestors if idx != global_idx
                )

        hood_neighbor_groups_by_global_idx: dict[
            int, tuple[tuple[str, tuple[int, ...]], ...]
        ] = {}
        neighbors_by_global_idx: dict[int, tuple[int, ...]] = {}
        for global_idx, hood_chain in hood_chain_by_global_idx.items():
            assigned = {
                global_idx,
                *ancestors_by_global_idx.get(global_idx, ()),
                *descendants_by_global_idx.get(global_idx, ()),
            }
            groups: list[tuple[str, tuple[int, ...]]] = []
            for hood in reversed(hood_chain):
                members = tuple(
                    idx for idx in members_by_hood[hood] if idx not in assigned
                )
                if not members:
                    continue
                groups.append((hood, members))
                assigned.update(members)
            if not groups:
                continue
            grouped = tuple(groups)
            hood_neighbor_groups_by_global_idx[global_idx] = grouped
            neighbors_by_global_idx[global_idx] = tuple(
                idx for _hood, members in grouped for idx in members
            )

        return cls(
            _neighbors_by_global_idx=neighbors_by_global_idx,
            _hood_neighbor_groups_by_global_idx=(hood_neighbor_groups_by_global_idx),
            _ancestors_by_global_idx=ancestors_by_global_idx,
            _descendants_by_global_idx=descendants_by_global_idx,
            _descendant_count_by_global_idx=descendant_count_by_global_idx,
            _panel_idx_by_global_idx=panel_idx_by_global_idx,
        )

    def neighbors_for(self, global_idx: int) -> tuple[int, ...]:
        """Return visible neighbor global indices for ``global_idx``."""
        return self._neighbors_by_global_idx.get(global_idx, ())

    def hood_neighbor_groups_for(
        self, global_idx: int
    ) -> tuple[tuple[str, tuple[int, ...]], ...]:
        """Return deepest-first shared-hood groups in visible render order."""
        return self._hood_neighbor_groups_by_global_idx.get(global_idx, ())

    def ancestors_for(self, global_idx: int) -> tuple[int, ...]:
        """Return visible ancestor global indices for ``global_idx``."""
        return self._ancestors_by_global_idx.get(global_idx, ())

    def descendants_for(self, global_idx: int) -> tuple[int, ...]:
        """Return visible descendant global indices for ``global_idx``."""
        return self._descendants_by_global_idx.get(global_idx, ())

    def neighbor_count(self, global_idx: int) -> int:
        """Return the number of visible neighbors for ``global_idx``."""
        return len(self.neighbors_for(global_idx))

    def ancestor_count(self, global_idx: int) -> int:
        """Return the number of visible ancestors for ``global_idx``."""
        return len(self.ancestors_for(global_idx))

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


def _descendant_ranges(names: list[str], ancestor: str) -> tuple[tuple[int, int], ...]:
    """Return sorted-name ranges following either supported name boundary."""
    return tuple(
        _prefix_range(names, f"{ancestor}{separator}") for separator in ("--", ".")
    )


def _agent_boundary_prefixes(name: str) -> tuple[str, ...]:
    """Return proper name-boundary prefixes, nearest first."""
    boundary_offsets = {index for index, char in enumerate(name) if char == "."}
    boundary_offsets.update(
        index for index in range(len(name) - 1) if name[index : index + 2] == "--"
    )
    return tuple(
        name[:offset] for offset in sorted(boundary_offsets, reverse=True) if offset > 0
    )


def _agent_hood_chain(name: str) -> tuple[str, ...]:
    """Return every dotted hood containing ``name``, root to own-name hood."""
    parts = name.split(".")
    return tuple(".".join(parts[:depth]) for depth in range(1, len(parts) + 1))
