"""Group-scoped agent-house collapse target resolution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent_panels import PanelKey
    from ...models.group_fold import GroupKey


@dataclass(frozen=True, slots=True)
class AgentHouseCollapseTarget:
    """One validated, group-scoped, saturating house-collapse action."""

    panel_key: PanelKey
    group_key: GroupKey
    fold_keys: tuple[str, ...]
    reanchor_index: int | None = None


def _is_canonical_house_owner(
    agent: Agent,
    *,
    fold_key: str,
    panel_agents: list[Agent],
    owners_by_key: dict[str, list[Agent]],
) -> bool:
    """Validate one standalone or direct-clan-member house owner."""
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

    # The only valid house owner below another structural row is a direct
    # clan member. Workflow steps and sequential-family members are aliases
    # of their outer house and were rejected above via ``is_child_row``.
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


def resolve_group_house_collapse_target(
    owner: Any,
    group_key: GroupKey,
) -> AgentHouseCollapseTarget | None:
    """Resolve every open canonical house in one focused-panel group.

    Group membership comes from a fully expanded grouping projection. This
    recovers the complete target membership when the focused banner is a
    collapsed child whose next ``H`` target is its parent, without changing
    any persisted or in-memory grouping fold state during the probe.
    """
    from ...models._agent_tree import agent_fold_key, agent_parent_fold_key
    from ...models.agent_groups import build_agent_tree
    from ...models.fold_state import FoldLevel
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

    # Fold keys live in one global manager, so duplicate validation must span
    # every visible panel. Otherwise matching malformed owners in two tribe
    # panels would make a supposedly panel-local mutation affect both.
    owners_by_key: dict[str, list[Agent]] = {}
    for candidate in getattr(owner, "_agents", panel_agents):
        candidate_key = agent_fold_key(candidate)
        if candidate_key is None or candidate.is_child_row:
            continue
        owners_by_key.setdefault(candidate_key, []).append(candidate)

    fold_counts = getattr(owner, "_fold_counts", {})
    fold_manager = owner._fold_manager
    open_keys: list[str] = []
    owner_global_index: dict[str, int] = {}
    seen: set[str] = set()
    for local_index in target_group.agent_indices:
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
        if not _is_canonical_house_owner(
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
    return AgentHouseCollapseTarget(
        panel_key=panel_key,
        group_key=group_key,
        fold_keys=tuple(open_keys),
        reanchor_index=reanchor_index,
    )


__all__ = ["AgentHouseCollapseTarget", "resolve_group_house_collapse_target"]
