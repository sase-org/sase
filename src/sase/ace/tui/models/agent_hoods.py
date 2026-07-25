"""Identity-stable kinship index for Agents-tab rows."""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .agent import Agent
from .agent_panels import agent_is_rendered_in_agents_panel

if TYPE_CHECKING:
    from .agent import AgentType
    from .agent_panels import PanelKey

type AgentIdentity = tuple["AgentType", str, str | None]


def agent_name_key(agent: Agent) -> str | None:
    """Return a case-folded valid dotted agent name key."""
    if agent.is_clan_container:
        return None
    name = agent.presented_identity_name
    if not name:
        return None
    parts = name.split(".")
    if any(not part for part in parts):
        return None
    return name.casefold()


def agent_owns_lane(agent: Agent) -> bool:
    """Return whether ``agent`` owns an agent-lane metadata document."""
    if agent.is_clan_container:
        return False
    if agent.is_workflow_child or agent.is_hidden_step:
        return False
    if agent.is_family_member_child:
        return False
    return agent_name_key(agent) is not None


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
    """Return the case-folded immediate dotted namespace for ``agent``."""
    name = agent_name_key(agent)
    if name is None:
        return None
    hood, sep, last = name.rpartition(".")
    if not sep or not hood or not last:
        return None
    return hood


@dataclass(frozen=True, slots=True)
class AgentNeighborRow:
    """One rendered or clan-revealable Agents-tab navigation target."""

    global_idx: int | None
    panel_idx: int | None
    agent: Agent
    hood: str | None = None
    panel_key: PanelKey = None
    display_order: int = 0
    clan_fold_key: str | None = None

    @property
    def identity(self) -> AgentIdentity:
        return self.agent.identity

    @property
    def is_prospective(self) -> bool:
        return self.global_idx is None and self.clan_fold_key is not None


@dataclass(frozen=True)
class AgentNeighborIndex:
    """Render-order lookup for visible and clan-revealable agent rows."""

    _neighbors_by_row: dict[int, tuple[AgentNeighborRow, ...]] = field(
        default_factory=dict
    )
    _hood_neighbor_groups_by_row: dict[
        int, tuple[tuple[str, tuple[AgentNeighborRow, ...]], ...]
    ] = field(default_factory=dict)
    _ancestors_by_row: dict[int, tuple[AgentNeighborRow, ...]] = field(
        default_factory=dict
    )
    _descendants_by_row: dict[int, tuple[AgentNeighborRow, ...]] = field(
        default_factory=dict
    )
    _descendant_count_by_row: dict[int, int] = field(default_factory=dict)
    _row_by_key: dict[int, AgentNeighborRow] = field(default_factory=dict)
    _keys_by_identity: dict[AgentIdentity, tuple[int, ...]] = field(
        default_factory=dict
    )
    _key_by_global_idx: dict[int, int] = field(default_factory=dict)

    @classmethod
    def from_visible_rows(
        cls,
        rows: list[AgentNeighborRow],
        dismissed_agents: Iterable[Agent] = (),
    ) -> AgentNeighborIndex:
        """Build an index from deterministic prospective render order.

        The historical constructor name remains because model callers supply
        only visible rows. Application callers may additionally supply rows
        whose ``global_idx`` is ``None`` and whose stable identity can be
        revealed by expanding a collapsed clan.
        """
        visible_identities = {
            row.identity for row in rows if row.global_idx is not None
        }
        ordered_rows = [
            row
            for _position, row in sorted(
                enumerate(rows),
                key=lambda item: (item[1].display_order, item[0]),
            )
            if row.global_idx is not None or row.identity not in visible_identities
        ]
        row_by_key: dict[int, AgentNeighborRow] = {}
        keys_by_identity_lists: dict[AgentIdentity, list[int]] = {}
        key_by_global_idx: dict[int, int] = {}
        name_by_key: dict[int, str] = {}
        keys_by_name: dict[str, list[int]] = {}
        hood_chain_by_key: dict[int, tuple[str, ...]] = {}
        members_by_hood: dict[str, list[int]] = {}

        for row_key, row in enumerate(ordered_rows):
            if not agent_is_rendered_in_agents_panel(row.agent):
                continue
            row_by_key[row_key] = row
            keys_by_identity_lists.setdefault(row.identity, []).append(row_key)
            if row.global_idx is not None:
                key_by_global_idx[row.global_idx] = row_key
            name = agent_name_key(row.agent)
            if name is None:
                continue
            name_by_key[row_key] = name
            keys_by_name.setdefault(name, []).append(row_key)
            hood_chain = _agent_hood_chain(name)
            hood_chain_by_key[row_key] = hood_chain
            for hood in hood_chain:
                members_by_hood.setdefault(hood, []).append(row_key)

        renderable_name_records = sorted(
            (name, row_key) for row_key, name in name_by_key.items()
        )
        renderable_names = [name for name, _row_key in renderable_name_records]
        dismissed_names = [
            name
            for agent in dismissed_agents
            if (name := agent_name_key(agent)) is not None
        ]
        all_names = sorted([*renderable_names, *dismissed_names])

        descendants_by_row: dict[int, tuple[AgentNeighborRow, ...]] = {}
        descendant_keys_by_row: dict[int, tuple[int, ...]] = {}
        descendant_count_by_row: dict[int, int] = {}
        for row_key, name in name_by_key.items():
            all_ranges = _descendant_ranges(all_names, name)
            descendant_count_by_row[row_key] = sum(
                end - start for start, end in all_ranges
            )

            renderable_ranges = _descendant_ranges(renderable_names, name)
            descendant_records = sorted(
                record
                for start, end in renderable_ranges
                for record in renderable_name_records[start:end]
            )
            descendant_keys = tuple(
                target_key for _name, target_key in descendant_records
            )
            descendants = tuple(
                row_by_key[target_key] for target_key in descendant_keys
            )
            if descendants:
                descendant_keys_by_row[row_key] = descendant_keys
                descendants_by_row[row_key] = descendants

        ancestors_by_row: dict[int, tuple[AgentNeighborRow, ...]] = {}
        ancestor_keys_by_row: dict[int, tuple[int, ...]] = {}
        for row_key, name in name_by_key.items():
            ancestors: list[int] = []
            for prefix in _agent_boundary_prefixes(name):
                ancestors.extend(keys_by_name.get(prefix, ()))
            if ancestors:
                ancestor_keys = tuple(
                    target_key for target_key in ancestors if target_key != row_key
                )
                ancestor_keys_by_row[row_key] = ancestor_keys
                ancestors_by_row[row_key] = tuple(
                    row_by_key[target_key] for target_key in ancestor_keys
                )

        hood_groups_by_row: dict[
            int, tuple[tuple[str, tuple[AgentNeighborRow, ...]], ...]
        ] = {}
        neighbors_by_row: dict[int, tuple[AgentNeighborRow, ...]] = {}
        for row_key, hood_chain in hood_chain_by_key.items():
            assigned = {
                row_key,
                *ancestor_keys_by_row.get(row_key, ()),
                *descendant_keys_by_row.get(row_key, ()),
            }
            groups: list[tuple[str, tuple[AgentNeighborRow, ...]]] = []
            for hood in reversed(hood_chain):
                member_keys = tuple(
                    target_key
                    for target_key in members_by_hood[hood]
                    if target_key not in assigned
                )
                if not member_keys:
                    continue
                members = tuple(row_by_key[target_key] for target_key in member_keys)
                groups.append((hood, members))
                assigned.update(member_keys)
            if not groups:
                continue
            grouped = tuple(groups)
            hood_groups_by_row[row_key] = grouped
            neighbors_by_row[row_key] = tuple(
                row for _hood, members in grouped for row in members
            )

        return cls(
            _neighbors_by_row=neighbors_by_row,
            _hood_neighbor_groups_by_row=hood_groups_by_row,
            _ancestors_by_row=ancestors_by_row,
            _descendants_by_row=descendants_by_row,
            _descendant_count_by_row=descendant_count_by_row,
            _row_by_key=row_by_key,
            _keys_by_identity={
                identity: tuple(keys)
                for identity, keys in keys_by_identity_lists.items()
            },
            _key_by_global_idx=key_by_global_idx,
        )

    def _unique_key_for_identity(self, identity: AgentIdentity) -> int | None:
        keys = self._keys_by_identity.get(identity, ())
        return keys[0] if len(keys) == 1 else None

    def target_for_identity(self, identity: AgentIdentity) -> AgentNeighborRow | None:
        """Return the target record only when its stable identity is unique."""
        row_key = self._unique_key_for_identity(identity)
        return self._row_by_key.get(row_key) if row_key is not None else None

    def target_for_global_idx(self, global_idx: int) -> AgentNeighborRow | None:
        """Resolve a current index to its stable target record."""
        row_key = self._key_by_global_idx.get(global_idx)
        return self._row_by_key.get(row_key) if row_key is not None else None

    def neighbor_targets_for(
        self, identity: AgentIdentity
    ) -> tuple[AgentNeighborRow, ...]:
        row_key = self._unique_key_for_identity(identity)
        return self._neighbors_by_row.get(row_key, ()) if row_key is not None else ()

    def hood_neighbor_target_groups_for(
        self, identity: AgentIdentity
    ) -> tuple[tuple[str, tuple[AgentNeighborRow, ...]], ...]:
        row_key = self._unique_key_for_identity(identity)
        return (
            self._hood_neighbor_groups_by_row.get(row_key, ())
            if row_key is not None
            else ()
        )

    def ancestor_targets_for(
        self, identity: AgentIdentity
    ) -> tuple[AgentNeighborRow, ...]:
        row_key = self._unique_key_for_identity(identity)
        return self._ancestors_by_row.get(row_key, ()) if row_key is not None else ()

    def descendant_targets_for(
        self, identity: AgentIdentity
    ) -> tuple[AgentNeighborRow, ...]:
        row_key = self._unique_key_for_identity(identity)
        return self._descendants_by_row.get(row_key, ()) if row_key is not None else ()

    def related_target_identities_for(
        self, identity: AgentIdentity
    ) -> frozenset[AgentIdentity]:
        """Return all indexed ancestor/descendant/hood target identities."""
        return frozenset(
            row.identity
            for row in (
                *self.ancestor_targets_for(identity),
                *self.descendant_targets_for(identity),
                *self.neighbor_targets_for(identity),
            )
        )

    @staticmethod
    def _visible_indices(rows: tuple[AgentNeighborRow, ...]) -> tuple[int, ...]:
        return tuple(row.global_idx for row in rows if row.global_idx is not None)

    # Compatibility views retained for model callers and current-index probes.
    def neighbors_for(self, global_idx: int) -> tuple[int, ...]:
        row_key = self._key_by_global_idx.get(global_idx)
        if row_key is None:
            return ()
        return self._visible_indices(self._neighbors_by_row.get(row_key, ()))

    def hood_neighbor_groups_for(
        self, global_idx: int
    ) -> tuple[tuple[str, tuple[int, ...]], ...]:
        row_key = self._key_by_global_idx.get(global_idx)
        if row_key is None:
            return ()
        groups: list[tuple[str, tuple[int, ...]]] = []
        for hood, rows in self._hood_neighbor_groups_by_row.get(row_key, ()):
            indices = self._visible_indices(rows)
            if indices:
                groups.append((hood, indices))
        return tuple(groups)

    def ancestors_for(self, global_idx: int) -> tuple[int, ...]:
        row_key = self._key_by_global_idx.get(global_idx)
        if row_key is None:
            return ()
        return self._visible_indices(self._ancestors_by_row.get(row_key, ()))

    def descendants_for(self, global_idx: int) -> tuple[int, ...]:
        row_key = self._key_by_global_idx.get(global_idx)
        if row_key is None:
            return ()
        return self._visible_indices(self._descendants_by_row.get(row_key, ()))

    def neighbor_count(self, global_idx: int) -> int:
        row_key = self._key_by_global_idx.get(global_idx)
        if row_key is None:
            return 0
        return len(self._neighbors_by_row.get(row_key, ()))

    def ancestor_count(self, global_idx: int) -> int:
        row_key = self._key_by_global_idx.get(global_idx)
        if row_key is None:
            return 0
        return len(self._ancestors_by_row.get(row_key, ()))

    def descendant_count(self, global_idx: int) -> int:
        row_key = self._key_by_global_idx.get(global_idx)
        if row_key is None:
            return 0
        return self._descendant_count_by_row.get(row_key, 0)

    def panel_idx_for(self, global_idx: int) -> int | None:
        target = self.target_for_global_idx(global_idx)
        return target.panel_idx if target is not None else None


def _prefix_range(names: list[str], prefix: str) -> tuple[int, int]:
    start = bisect_left(names, prefix)
    end = bisect_left(names, prefix + chr(0x10FFFF))
    return start, end


def _descendant_ranges(names: list[str], ancestor: str) -> tuple[tuple[int, int], ...]:
    return tuple(
        _prefix_range(names, f"{ancestor}{separator}") for separator in ("--", ".")
    )


def _agent_boundary_prefixes(name: str) -> tuple[str, ...]:
    boundary_offsets = {index for index, char in enumerate(name) if char == "."}
    boundary_offsets.update(
        index for index in range(len(name) - 1) if name[index : index + 2] == "--"
    )
    return tuple(
        name[:offset] for offset in sorted(boundary_offsets, reverse=True) if offset > 0
    )


def _agent_hood_chain(name: str) -> tuple[str, ...]:
    parts = name.split(".")
    return tuple(".".join(parts[:depth]) for depth in range(1, len(parts) + 1))
