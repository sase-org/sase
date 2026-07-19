"""Identity-based display diffs for finalized Agents-tab lists."""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from ...models.agent import AgentType
from ...models.agent_panels import (
    AgentPanelGroup,
    PanelKey,
    agent_is_rendered_in_agents_panel,
    panel_key_per_agent,
)

if TYPE_CHECKING:
    from ...models import Agent

AgentIdentity = tuple[AgentType, str, str | None]


@dataclass(frozen=True)
class _AgentDisplayDiff:
    """Identity-level change summary between two finalized agent lists."""

    changed_same_position: tuple[int, ...]
    removed_identities: frozenset[AgentIdentity]
    added_indices: tuple[int, ...]
    moved_identities: frozenset[AgentIdentity]
    duplicate_identity: bool = False

    @property
    def has_changes(self) -> bool:
        return bool(
            self.changed_same_position
            or self.removed_identities
            or self.added_indices
            or self.moved_identities
            or self.duplicate_identity
        )

    @property
    def has_collection_changes(self) -> bool:
        return bool(
            self.removed_identities or self.added_indices or self.moved_identities
        )


def build_agent_display_diff(
    previous_agents: list[Agent],
    next_agents: list[Agent],
) -> _AgentDisplayDiff:
    """Return an identity-based diff between previous and next agent lists."""
    previous_ids = [agent.identity for agent in previous_agents]
    next_ids = [agent.identity for agent in next_agents]
    previous_id_set = set(previous_ids)
    next_id_set = set(next_ids)
    duplicate_identity = len(previous_id_set) != len(previous_ids) or len(
        next_id_set
    ) != len(next_ids)

    previous_index = {identity: idx for idx, identity in enumerate(previous_ids)}
    next_index = {identity: idx for idx, identity in enumerate(next_ids)}
    common = previous_id_set & next_id_set

    changed_same_position: list[int] = []
    for idx, (previous, next_agent) in enumerate(
        zip(previous_agents, next_agents, strict=False)
    ):
        if previous.identity != next_agent.identity:
            continue
        if previous != next_agent:
            changed_same_position.append(idx)

    added_indices = tuple(
        idx for idx, identity in enumerate(next_ids) if identity not in previous_id_set
    )
    moved_identities = frozenset(
        identity
        for identity in common
        if previous_index[identity] != next_index[identity]
    )

    return _AgentDisplayDiff(
        changed_same_position=tuple(changed_same_position),
        removed_identities=frozenset(previous_id_set - next_id_set),
        added_indices=added_indices,
        moved_identities=moved_identities,
        duplicate_identity=duplicate_identity,
    )


def panel_keys_for_display(
    agents: list[Agent],
    *,
    merge_tribe_panels: bool,
    collapsed_panel_keys: Collection[PanelKey] = (),
) -> tuple[PanelKey, ...]:
    """Return the rendered panel-key collection for *agents*."""
    return tuple(
        AgentPanelGroup.from_agents(
            agents,
            merge_tribe_panels=merge_tribe_panels,
            collapsed_panel_keys=collapsed_panel_keys,
        ).panel_keys
    )


def rendered_panel_key_by_identity(
    agents: list[Agent],
    *,
    merge_tribe_panels: bool,
) -> dict[AgentIdentity, PanelKey]:
    """Map rendered agent identities to their effective panel key."""
    keys = panel_key_per_agent(agents, merge_tribe_panels=merge_tribe_panels)
    return {
        agent.identity: keys[idx]
        for idx, agent in enumerate(agents)
        if agent_is_rendered_in_agents_panel(agent)
    }


def _rendered_panel_position_by_identity(
    agents: list[Agent],
    *,
    merge_tribe_panels: bool,
) -> dict[AgentIdentity, tuple[PanelKey, int]]:
    keys = panel_key_per_agent(agents, merge_tribe_panels=merge_tribe_panels)
    next_local_idx: dict[PanelKey, int] = {}
    positions: dict[AgentIdentity, tuple[PanelKey, int]] = {}
    for idx, agent in enumerate(agents):
        if not agent_is_rendered_in_agents_panel(agent):
            continue
        key = keys[idx]
        local_idx = next_local_idx.get(key, 0)
        next_local_idx[key] = local_idx + 1
        positions[agent.identity] = (key, local_idx)
    return positions


def affected_panel_keys(
    diff: _AgentDisplayDiff,
    previous_agents: list[Agent],
    next_agents: list[Agent],
    *,
    merge_tribe_panels: bool,
) -> set[PanelKey]:
    """Return panels whose rendered membership or content changed."""
    previous_keys = rendered_panel_key_by_identity(
        previous_agents,
        merge_tribe_panels=merge_tribe_panels,
    )
    next_keys = rendered_panel_key_by_identity(
        next_agents,
        merge_tribe_panels=merge_tribe_panels,
    )
    previous_positions = _rendered_panel_position_by_identity(
        previous_agents,
        merge_tribe_panels=merge_tribe_panels,
    )
    next_positions = _rendered_panel_position_by_identity(
        next_agents,
        merge_tribe_panels=merge_tribe_panels,
    )
    keys: set[PanelKey] = set()

    for identity in diff.removed_identities:
        if identity in previous_keys:
            keys.add(previous_keys[identity])

    for idx in diff.added_indices:
        identity = next_agents[idx].identity
        if identity in next_keys:
            keys.add(next_keys[identity])

    for identity in diff.moved_identities:
        previous_pos = previous_positions.get(identity)
        next_pos = next_positions.get(identity)
        if previous_pos == next_pos:
            continue
        if identity in previous_keys:
            keys.add(previous_keys[identity])
        if identity in next_keys:
            keys.add(next_keys[identity])

    for idx in diff.changed_same_position:
        identity = next_agents[idx].identity
        if identity in next_keys:
            keys.add(next_keys[identity])

    return keys


def changed_same_position_panel_membership_keys(
    diff: _AgentDisplayDiff,
    previous_agents: list[Agent],
    next_agents: list[Agent],
    *,
    merge_tribe_panels: bool,
) -> set[PanelKey]:
    """Return panels needing rebuild for same-position panel/tribe changes."""
    if not diff.changed_same_position:
        return set()

    previous_keys = rendered_panel_key_by_identity(
        previous_agents,
        merge_tribe_panels=merge_tribe_panels,
    )
    next_keys = rendered_panel_key_by_identity(
        next_agents,
        merge_tribe_panels=merge_tribe_panels,
    )
    missing = object()
    keys: set[PanelKey] = set()
    for idx in diff.changed_same_position:
        previous = previous_agents[idx]
        next_agent = next_agents[idx]
        identity = next_agent.identity
        previous_key = previous_keys.get(identity, missing)
        next_key = next_keys.get(identity, missing)
        if previous_key != next_key:
            if previous_key is not missing:
                keys.add(cast(PanelKey, previous_key))
            if next_key is not missing:
                keys.add(cast(PanelKey, next_key))
            continue
        if (
            merge_tribe_panels
            and previous.tribe != next_agent.tribe
            and next_key is not missing
        ):
            keys.add(cast(PanelKey, next_key))
    return keys


def diff_touches_workflow_tree(
    diff: _AgentDisplayDiff,
    previous_agents: list[Agent],
    next_agents: list[Agent],
) -> bool:
    """Return True when incremental rendering would risk stale tree rows."""
    previous_by_id = {agent.identity: agent for agent in previous_agents}
    next_by_id = {agent.identity: agent for agent in next_agents}
    touched: set[AgentIdentity] = set(diff.removed_identities)
    touched.update(diff.moved_identities)
    touched.update(next_agents[idx].identity for idx in diff.added_indices)

    def is_workflow_shaped(agent: Agent | None) -> bool:
        if agent is None:
            return False
        return (
            agent.agent_type is AgentType.WORKFLOW
            or agent.is_workflow_child
            or agent.parent_timestamp is not None
            or agent.parent_workflow is not None
        )

    def structural_signature(agent: Agent) -> tuple[object, ...]:
        return (
            agent.status,
            agent.hidden,
            agent.is_workflow_child,
            agent.raw_suffix,
            agent.parent_timestamp,
            agent.parent_workflow,
        )

    for idx in diff.changed_same_position:
        previous = previous_agents[idx]
        next_agent = next_agents[idx]
        if structural_signature(previous) == structural_signature(next_agent):
            continue
        if is_workflow_shaped(previous) or is_workflow_shaped(next_agent):
            touched.add(next_agent.identity)

    for identity in touched:
        if is_workflow_shaped(previous_by_id.get(identity)) or is_workflow_shaped(
            next_by_id.get(identity)
        ):
            return True
    return False
