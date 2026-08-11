"""Group- and panel-scoped agent-lane collapse target resolution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent_panels import PanelKey
    from ...models.group_fold import GroupKey


@dataclass(frozen=True, slots=True)
class AgentLaneCollapseTarget:
    """One validated, group-scoped, saturating lane-collapse action."""

    panel_key: PanelKey
    group_key: GroupKey
    fold_keys: tuple[str, ...]
    reanchor_index: int | None = None


@dataclass(frozen=True, slots=True)
class _AgentPanelLaneCollapseTarget:
    """One validated, panel-wide, saturating lane-collapse action."""

    panel_key: PanelKey
    fold_keys: tuple[str, ...]
    reanchor_index: int | None = None


def _is_canonical_lane_owner(
    agent: Agent,
    *,
    fold_key: str,
    panel_agents: list[Agent],
    owners_by_key: dict[str, list[Agent]],
) -> bool:
    """Validate one standalone or direct-clan-member lane owner."""
    from ...models._agent_tree import agent_fold_key, agent_parent_fold_key

    if agent.is_clan_container or agent.is_child_row:
        return False
    owner_matches = owners_by_key.get(fold_key, [])
    if len(owner_matches) != 1 or owner_matches[0] is not agent:
        return False
    if agent_fold_key(agent) != fold_key:
        return False

    parent_key = agent_parent_fold_key(agent)
    if parent_key is None:
        return agent.tree_parent_key is None and agent.tree_depth == 0

    # The only valid lane owner below another structural row is a direct
    # clan member. Workflow steps and sequential-family members are aliases
    # of their outer lane and were rejected above via ``is_child_row``.
    if (
        agent.tree_parent_key != parent_key
        or agent.tree_depth != 1
        or not parent_key.startswith("clan:")
    ):
        return False
    clan_owners = [
        candidate
        for candidate in panel_agents
        if candidate.is_clan_container and agent_fold_key(candidate) == parent_key
    ]
    return len(clan_owners) == 1


def _open_canonical_lane_keys(
    owner: Any,
    *,
    panel_agents: list[Agent],
    global_indices: list[int],
    candidate_indices: tuple[int, ...],
) -> tuple[tuple[str, ...], dict[str, int]]:
    """Return validated open lane keys and their global owner indices."""
    from ...models._agent_tree import agent_fold_key
    from ...models.fold_state import FoldLevel

    # Fold keys live in one global manager, so duplicate validation must span
    # every loaded panel. Otherwise matching malformed owners in two tribe
    # panels would make a supposedly panel-local mutation affect both.
    owners_by_key: dict[str, list[Agent]] = {}
    loaded_agents = getattr(owner, "_agents_with_children", None) or getattr(
        owner, "_agents", panel_agents
    )
    for candidate in loaded_agents:
        candidate_key = agent_fold_key(candidate)
        if candidate_key is None or candidate.is_child_row:
            continue
        owners_by_key.setdefault(candidate_key, []).append(candidate)

    fold_counts = getattr(owner, "_fold_counts", {})
    fold_manager = owner._fold_manager
    open_keys: list[str] = []
    owner_global_index: dict[str, int] = {}
    seen: set[str] = set()
    for local_index in candidate_indices:
        if not (0 <= local_index < len(panel_agents)):
            continue
        candidate = panel_agents[local_index]
        fold_key = agent_fold_key(candidate)
        if fold_key is None or fold_key in seen:
            continue
        seen.add(fold_key)
        counts = fold_counts.get(fold_key)
        if counts is None or sum(counts) <= 0:
            continue
        if not _is_canonical_lane_owner(
            candidate,
            fold_key=fold_key,
            panel_agents=panel_agents,
            owners_by_key=owners_by_key,
        ):
            continue
        if fold_manager.get(fold_key) == FoldLevel.COLLAPSED:
            continue
        if not (0 <= local_index < len(global_indices)):
            continue
        open_keys.append(fold_key)
        owner_global_index[fold_key] = global_indices[local_index]

    return tuple(open_keys), owner_global_index


def resolve_group_lane_collapse_target(
    owner: Any,
    group_key: GroupKey,
) -> AgentLaneCollapseTarget | None:
    """Resolve every open canonical lane in one focused-panel group.

    Group membership comes from a fully expanded grouping projection. This
    recovers the complete target membership when the focused banner is a
    collapsed child whose next ``H`` target is its parent, without changing
    any persisted or in-memory grouping fold state during the probe.
    """
    from ...models._agent_tree import agent_parent_fold_key
    from ...models.agent_groups import build_agent_tree
    from ...models.group_fold import GroupFoldRegistry

    global_indices, panel_agents, _registry = owner._focused_panel_fold_context()
    target_group = next(
        (
            entry.group
            for entry in build_agent_tree(
                panel_agents,
                fold_registry=GroupFoldRegistry(),
                mode=owner._active_grouping_mode(),
            )
            if entry.kind == "group"
            and entry.group is not None
            and entry.group.group_key == group_key
        ),
        None,
    )
    if target_group is None:
        return None

    open_keys, owner_global_index = _open_canonical_lane_keys(
        owner,
        panel_agents=panel_agents,
        global_indices=global_indices,
        candidate_indices=target_group.agent_indices,
    )

    if not open_keys:
        return None

    reanchor_index: int | None = None
    if getattr(owner, "_current_group_key", None) is None:
        selected = owner._get_selected_agent()
        selected_parent_key = (
            agent_parent_fold_key(selected) if selected is not None else None
        )
        if selected_parent_key in owner_global_index:
            reanchor_index = owner_global_index[selected_parent_key]

    panel_group = getattr(owner, "_panel_group", None)
    panel_key = panel_group.focused_key if panel_group is not None else None
    return AgentLaneCollapseTarget(
        panel_key=panel_key,
        group_key=group_key,
        fold_keys=tuple(open_keys),
        reanchor_index=reanchor_index,
    )


def resolve_panel_lane_collapse_target(
    owner: Any,
    panel_key: PanelKey,
) -> _AgentPanelLaneCollapseTarget | None:
    """Resolve every open canonical lane in one selected tribe panel."""
    from ._navigation_order import rendered_panel_slice

    global_indices, panel_agents = rendered_panel_slice(owner, panel_key)
    open_keys, _owner_global_index = _open_canonical_lane_keys(
        owner,
        panel_agents=panel_agents,
        global_indices=global_indices,
        candidate_indices=tuple(range(len(panel_agents))),
    )
    if not open_keys:
        return None
    return _AgentPanelLaneCollapseTarget(
        panel_key=panel_key,
        fold_keys=open_keys,
    )


__all__ = [
    "AgentLaneCollapseTarget",
    "resolve_group_lane_collapse_target",
    "resolve_panel_lane_collapse_target",
]
