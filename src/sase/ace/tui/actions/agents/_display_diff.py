"""Identity-based display diffs for finalized Agents-tab lists."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, cast

from ...models.agent import AgentType
from ...models.agent_groups import (
    GroupingMode,
    rendered_group_keys,
    status_grouping_signature,
)
from ...models.agent_panels import (
    PanelKey,
    agent_is_rendered_in_agents_panel,
    panel_key_per_agent,
)

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent_panel_index import AgentPanelIndex

AgentIdentity = tuple[AgentType, str, str | None]

#: The fallback reasons a whole-roster predicate attributes to a panel; each is
#: also a member of ``AgentRefreshFallbackReason``.
PanelRebuildReason = Literal[
    "panel_membership_change",
    "status_membership_change",
    "workflow_tree_change",
]


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


@dataclass(frozen=True)
class PanelRebuildScope:
    """Panels an apply must rebuild whole, and the reason each one is named for.

    ``reasons`` holds one ``(panel key, reason)`` pair per attribution, in a
    stable order, so a partial rebuild stays as observable as a global one.
    ``rebuilt_removals`` are the removed identities that lived in a rebuilt
    panel: that panel is repainted from its new slice, so they need no
    in-place row removal first.
    """

    reasons: tuple[tuple[PanelKey, PanelRebuildReason], ...] = ()
    rebuilt_removals: frozenset[AgentIdentity] = frozenset()

    @property
    def keys(self) -> set[PanelKey]:
        return {key for key, _reason in self.reasons}


def _duplicate_identity_panel_keys(
    diff: _AgentDisplayDiff,
    previous_agents: list[Agent],
    next_agents: list[Agent],
    *,
    previous_index: AgentPanelIndex,
    next_index: AgentPanelIndex,
) -> set[PanelKey]:
    """Panels holding any occurrence of an identity that repeats in a roster.

    The identity-keyed diff cannot say which copy moved, changed, or left, so
    every panel that holds one, before or after, is unsafe to patch.
    """
    if not diff.duplicate_identity:
        return set()
    duplicated = {
        identity
        for roster in (previous_agents, next_agents)
        for identity, count in Counter(agent.identity for agent in roster).items()
        if count > 1
    }
    return {
        key
        for roster, index in (
            (previous_agents, previous_index),
            (next_agents, next_index),
        )
        for agent, key in zip(roster, index.keys_per_agent, strict=True)
        if agent.identity in duplicated
    }


def _by_status_membership_panel_keys(
    previous_agents: list[Agent],
    next_agents: list[Agent],
    *,
    previous_index: AgentPanelIndex,
    next_index: AgentPanelIndex,
) -> set[PanelKey]:
    """Panels whose ``BY_STATUS`` grouping structure would move rows.

    A panel is named when a row it held or now holds changed status bucket or
    launch anchor, or when the banner keys of its own slice differ. A new
    bucket in one panel therefore no longer names its siblings.
    """
    next_position = {agent.identity: idx for idx, agent in enumerate(next_agents)}
    keys: set[PanelKey] = set()
    for previous_idx, previous in enumerate(previous_agents):
        next_idx = next_position.get(previous.identity)
        # A row that had no Agents-tab row yet (a STARTING agent that just
        # became rendered) has nothing on screen to move: it is an arrival, and
        # the banner-key comparison below catches a new bucket.
        if next_idx is None or not agent_is_rendered_in_agents_panel(previous):
            continue
        if status_grouping_signature(previous) != status_grouping_signature(
            next_agents[next_idx]
        ):
            keys.add(previous_index.keys_per_agent[previous_idx])
            keys.add(next_index.keys_per_agent[next_idx])

    def banner_keys(index: AgentPanelIndex) -> dict[PanelKey, tuple[Any, ...]]:
        return {
            key: rendered_group_keys(slot.agents, GroupingMode.BY_STATUS)
            for key, slot in index.panels.items()
        }

    previous_banners = banner_keys(previous_index)
    next_banners = banner_keys(next_index)
    keys.update(
        key
        for key in previous_banners.keys() | next_banners.keys()
        if previous_banners.get(key) != next_banners.get(key)
    )
    return keys


def _is_workflow_shaped(agent: Agent) -> bool:
    return (
        agent.agent_type is AgentType.WORKFLOW
        or agent.is_workflow_child
        or agent.parent_timestamp is not None
        or agent.parent_workflow is not None
    )


def _workflow_structural_signature(agent: Agent) -> tuple[object, ...]:
    return (
        agent.status,
        agent.hidden,
        agent.is_workflow_child,
        agent.raw_suffix,
        agent.parent_timestamp,
        agent.parent_workflow,
    )


def _workflow_tree_panel_keys(
    previous_agents: list[Agent],
    next_agents: list[Agent],
    *,
    previous_index: AgentPanelIndex,
    next_index: AgentPanelIndex,
) -> set[PanelKey]:
    """Panels whose workflow tree changed between two rosters.

    A panel's workflow tree is the ordered ``(identity, structural signature)``
    of the workflow-shaped rows it holds, hidden ones included. An add, a
    removal, a structural change, a reparent, or a reorder among workflow rows
    changes it, and a row that moves panels changes both. A workflow row that
    only sits at a different roster index because a row arrived in a *different*
    panel changes nothing, and neither does a cosmetic field such as activity.
    """

    def trees(
        agents: list[Agent], index: AgentPanelIndex
    ) -> dict[PanelKey, tuple[tuple[AgentIdentity, tuple[object, ...]], ...]]:
        rows: dict[PanelKey, list[tuple[AgentIdentity, tuple[object, ...]]]] = {}
        for agent, key in zip(agents, index.keys_per_agent, strict=True):
            if _is_workflow_shaped(agent):
                rows.setdefault(key, []).append(
                    (agent.identity, _workflow_structural_signature(agent))
                )
        return {key: tuple(panel_rows) for key, panel_rows in rows.items()}

    previous_trees = trees(previous_agents, previous_index)
    next_trees = trees(next_agents, next_index)
    return {
        key
        for key in previous_trees.keys() | next_trees.keys()
        if previous_trees.get(key) != next_trees.get(key)
    }


def panel_rebuild_scope(
    diff: _AgentDisplayDiff,
    previous_agents: list[Agent],
    next_agents: list[Agent],
    *,
    previous_index: AgentPanelIndex,
    next_index: AgentPanelIndex,
    by_status: bool,
) -> PanelRebuildScope:
    """Attribute each whole-roster rebuild predicate to the panels it concerns.

    The three predicates used to answer "rebuild everything". Each now names
    the panel keys whose own slice it fires for, so the apply rebuilds those
    panels and leaves every other one to the cheap patch path. A diff that
    changes nothing short-circuits to an empty scope.
    """
    if not diff.has_changes:
        return PanelRebuildScope()
    attributions: tuple[tuple[PanelRebuildReason, set[PanelKey]], ...] = (
        (
            "panel_membership_change",
            _duplicate_identity_panel_keys(
                diff,
                previous_agents,
                next_agents,
                previous_index=previous_index,
                next_index=next_index,
            ),
        ),
        (
            "status_membership_change",
            _by_status_membership_panel_keys(
                previous_agents,
                next_agents,
                previous_index=previous_index,
                next_index=next_index,
            )
            if by_status
            else set(),
        ),
        (
            "workflow_tree_change",
            _workflow_tree_panel_keys(
                previous_agents,
                next_agents,
                previous_index=previous_index,
                next_index=next_index,
            ),
        ),
    )
    reasons = tuple(
        (key, reason)
        for reason, keys in attributions
        for key in sorted(keys, key=_panel_key_order)
    )
    rebuilt = {key for key, _reason in reasons}
    return PanelRebuildScope(
        reasons=reasons,
        rebuilt_removals=frozenset(
            agent.identity
            for agent, key in zip(
                previous_agents, previous_index.keys_per_agent, strict=True
            )
            if key in rebuilt and agent.identity in diff.removed_identities
        )
        if rebuilt and diff.removed_identities
        else frozenset(),
    )


def _panel_key_order(key: PanelKey) -> tuple[bool, str]:
    """Sort key: the reserved ``@default`` panel first, then tribes by name."""
    return (key is not None, key or "")
