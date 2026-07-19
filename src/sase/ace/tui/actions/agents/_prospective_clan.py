"""Pure projection of rows hidden only by collapsed outer clan folds."""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType
    from ...models.agent_panels import PanelKey

type AgentIdentity = tuple["AgentType", str, str | None]


@dataclass(frozen=True, slots=True)
class ProspectiveClanMember:
    """A real agent row revealed by relaxing one collapsed clan fold."""

    agent: Agent
    panel_key: PanelKey
    panel_idx: int
    display_order: int
    clan_fold_key: str

    @property
    def identity(self) -> AgentIdentity:
        return self.agent.identity


@dataclass(frozen=True, slots=True)
class _ProspectiveClanProjection:
    """Rendered ordering plus the subset newly revealable through clans."""

    members: dict[AgentIdentity, ProspectiveClanMember]
    display_order_by_identity: dict[AgentIdentity, int]


class _FoldStateProjection:
    """Read-only fold-state adapter for a copied prospective snapshot."""

    def __init__(self, levels: dict[str, object]) -> None:
        self._levels = levels

    def get(self, key: str) -> object:
        from ...models.fold_state import FoldLevel

        return self._levels.get(key, FoldLevel.COLLAPSED)


def _projection_panel_fold_registry(owner: Any, panel_key: PanelKey) -> Any:
    """Return an isolated snapshot of one panel's grouping-fold state."""
    from ...models.agent_group_fold import (
        AgentGroupFoldRegistry,
        AgentPanelFoldScope,
    )
    from ...models.group_fold import GroupFoldRegistry

    registry_owner = getattr(owner, "_group_fold_registry", None)
    if not isinstance(registry_owner, AgentGroupFoldRegistry):
        return registry_owner
    scope = AgentPanelFoldScope(
        panel_key=panel_key,
        merged=bool(getattr(owner, "_agent_panels_grouped", False)),
    )
    registry = GroupFoldRegistry()
    for snapshot in registry_owner.snapshot():
        if snapshot.scope == scope:
            registry.restore(snapshot.collapsed)
            break
    return registry


def _collapsed_clan_member_folds(
    owner: Any,
    complete: list[Agent],
    requested_fold_keys: Collection[str] | None,
) -> dict[AgentIdentity, str]:
    """Map unambiguous real descendants to their collapsed outer clan."""
    from ...models._agent_tree import (
        agent_fold_key,
        agent_parent_fold_key,
        tree_parent_lookup,
    )
    from ...models.fold_state import FoldLevel

    fold_manager = getattr(owner, "_fold_manager", None)
    if fold_manager is None:
        return {}
    requested = set(requested_fold_keys) if requested_fold_keys is not None else None
    collapsed_clan_keys: set[str] = set()
    for container in complete:
        if not container.is_clan_container:
            continue
        fold_key = agent_fold_key(container)
        if (
            fold_key is None
            or fold_manager.get(fold_key) is not FoldLevel.COLLAPSED
            or (requested is not None and fold_key not in requested)
        ):
            continue
        collapsed_clan_keys.add(fold_key)

    parents = tree_parent_lookup(complete)
    fold_keys_by_identity: dict[AgentIdentity, list[str]] = {}
    for agent in complete:
        if agent.is_clan_container:
            continue
        current = agent
        visited: set[int] = set()
        for _ in range(len(complete) + 1):
            if id(current) in visited:
                break
            visited.add(id(current))
            parent_key = agent_parent_fold_key(current)
            if parent_key is None:
                break
            if parent_key in collapsed_clan_keys:
                fold_keys_by_identity.setdefault(agent.identity, []).append(parent_key)
                break
            parent = parents.get(parent_key)
            if parent is None:
                break
            current = parent

    # A duplicated identity cannot be targeted safely; the reveal preflight
    # rejects it too, so omit it from discovery rather than choosing a clan.
    return {
        identity: member_fold_keys[0]
        for identity, member_fold_keys in fold_keys_by_identity.items()
        if len(member_fold_keys) == 1
    }


def _apply_active_agent_query(owner: Any, agents: list[Agent]) -> list[Agent]:
    """Apply the same cached structured query used by the Agents view."""
    raw_query = getattr(owner, "_agent_search_query", "") or ""
    if not raw_query:
        return agents

    cached = getattr(owner, "_agent_query_cache", None)
    parsed = cached[1] if cached is not None and cached[0] == raw_query else None
    if parsed is None:
        from ....agent_query import AgentQueryParseError, parse_agent_query

        try:
            parsed = parse_agent_query(raw_query)
        except AgentQueryParseError:
            # The real finalize pipeline treats a bad query as unfiltered
            # after surfacing its parse error, so the projection must agree.
            return agents

    from sase.core.time import local_now

    from ....agent_query import evaluate_agent_query
    from ...models._agent_tree import filter_tree_rows

    content_index = getattr(owner, "_agent_content_search_index", None)
    now = local_now()
    return filter_tree_rows(
        agents,
        lambda agent: evaluate_agent_query(
            parsed,
            agent,
            now=now,
            content_cache=content_index,
        ),
    )


def prospective_clan_projection(
    owner: Any,
    complete: list[Agent],
    *,
    fold_keys: Collection[str] | None = None,
) -> _ProspectiveClanProjection:
    """Return rows that would render if collapsed clan folds were relaxed.

    Every other visibility input remains unchanged: inner workflow/family
    folds, active search, grouping folds, split/merged tribe assignment, and
    STARTING-row exclusion. Collapsed tribe panels are deliberately traversed
    because their rows remain revealable navigation targets.
    """
    from ...models import filter_agents_by_fold_state
    from ...models.agent_groups import GroupingMode, build_agent_tree
    from ...models.agent_panels import AgentPanelGroup, agents_for_panel
    from ...models.fold_state import FoldLevel

    member_folds = _collapsed_clan_member_folds(owner, complete, fold_keys)
    if not member_folds:
        return _ProspectiveClanProjection({}, {})

    fold_manager = getattr(owner, "_fold_manager", None)
    if fold_manager is None:
        return _ProspectiveClanProjection({}, {})
    levels: dict[str, object] = dict(fold_manager.snapshot())
    for fold_key in set(member_folds.values()):
        levels[fold_key] = FoldLevel.EXPANDED
    projected, _counts = filter_agents_by_fold_state(
        complete,
        _FoldStateProjection(levels),  # type: ignore[arg-type]
    )
    projected = _apply_active_agent_query(owner, projected)

    mode: GroupingMode = getattr(owner, "_grouping_mode", GroupingMode.STANDARD)
    merged = bool(getattr(owner, "_agent_panels_grouped", False))
    panel_group = AgentPanelGroup.from_agents(
        projected,
        merge_tribe_panels=merged,
        collapsed_panel_keys=getattr(owner, "_collapsed_panel_keys", ()),
    )
    dismissed = set(getattr(owner, "_dismissed_agents", set()))
    rendered: dict[AgentIdentity, ProspectiveClanMember] = {}
    order_by_identity: dict[AgentIdentity, int] = {}
    display_order = 0
    for panel_idx, panel_key in enumerate(panel_group.panel_keys):
        panel_agents = agents_for_panel(
            projected,
            panel_key,
            merge_tribe_panels=merged,
        )
        tree = build_agent_tree(
            panel_agents,
            fold_registry=_projection_panel_fold_registry(owner, panel_key),
            mode=mode,
        )
        for entry in tree:
            if entry.kind != "agent" or entry.agent_idx is None:
                continue
            if not (0 <= entry.agent_idx < len(panel_agents)):
                continue
            agent = panel_agents[entry.agent_idx]
            order_by_identity.setdefault(agent.identity, display_order)
            target_fold_key = member_folds.get(agent.identity)
            if target_fold_key is not None and agent.identity not in dismissed:
                rendered[agent.identity] = ProspectiveClanMember(
                    agent=agent,
                    panel_key=panel_key,
                    panel_idx=panel_idx,
                    display_order=display_order,
                    clan_fold_key=target_fold_key,
                )
            display_order += 1
    return _ProspectiveClanProjection(rendered, order_by_identity)


def prospective_clan_members(
    owner: Any,
    complete: list[Agent],
    *,
    fold_keys: Collection[str] | None = None,
) -> dict[AgentIdentity, ProspectiveClanMember]:
    """Return only the revealable member subset of a clan projection."""
    return prospective_clan_projection(
        owner,
        complete,
        fold_keys=fold_keys,
    ).members


__all__ = [
    "ProspectiveClanMember",
    "prospective_clan_members",
    "prospective_clan_projection",
]
