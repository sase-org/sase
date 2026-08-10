"""Panel- and group-scoped clan fold target resolution and transitions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ._folding_agent_tree import AgentStructuralFoldingMixin
from ._navigation_order import rendered_panel_slice

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent_group_fold import GroupKey
    from ...models.agent_panels import PanelKey
    from ...models.fold_state import FoldStateManager


@dataclass(frozen=True, slots=True)
class _AgentPanelClanCollapseTarget:
    """Validated open clan folds owned by one selected tribe panel."""

    panel_key: PanelKey
    fold_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _AgentGroupClanCollapseTarget:
    """Validated open clan folds owned by one panel/group scope."""

    panel_key: PanelKey
    group_key: GroupKey
    fold_keys: tuple[str, ...]
    reanchor_index: int | None = None


def _is_canonical_clan_owner(
    agent: Agent,
    *,
    fold_key: str,
    owners_by_key: dict[str, list[Agent]],
) -> bool:
    """Return whether one loaded row uniquely owns a synthetic clan fold."""
    from ...models._agent_tree import agent_fold_key, agent_parent_fold_key

    owner_matches = owners_by_key.get(fold_key, [])
    return bool(
        agent.is_clan_container
        and agent.agent_clan
        and agent.raw_suffix is None
        and not agent.is_child_row
        and agent_parent_fold_key(agent) is None
        and agent.tree_parent_key is None
        and agent.tree_depth == 0
        and agent_fold_key(agent) == fold_key
        and len(owner_matches) == 1
        and owner_matches[0] is agent
    )


def _open_canonical_clan_keys(
    owner: Any,
    *,
    panel_agents: list[Agent],
    global_indices: list[int],
    candidate_indices: tuple[int, ...],
) -> tuple[tuple[str, ...], dict[str, int]]:
    """Return validated open clan keys and their global owner indices."""
    from ...models._agent_tree import agent_fold_key
    from ...models.fold_state import FoldLevel

    # FoldStateManager is global across panels. Validate every candidate key
    # against the complete cached projection, including rows filtered out of
    # the current render, so a panel/group-local action cannot cross scopes.
    loaded_agents = getattr(owner, "_agents_with_children", None) or getattr(
        owner, "_agents", panel_agents
    )
    owners_by_key: dict[str, list[Agent]] = {}
    for candidate in loaded_agents:
        candidate_key = agent_fold_key(candidate)
        if candidate_key is not None:
            owners_by_key.setdefault(candidate_key, []).append(candidate)

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
        if not _is_canonical_clan_owner(
            candidate,
            fold_key=fold_key,
            owners_by_key=owners_by_key,
        ):
            continue
        if owner._fold_manager.get(fold_key) == FoldLevel.COLLAPSED:
            continue
        if not (0 <= local_index < len(global_indices)):
            continue
        open_keys.append(fold_key)
        owner_global_index[fold_key] = global_indices[local_index]

    return tuple(open_keys), owner_global_index


def resolve_panel_clan_collapse_target(
    owner: Any,
    panel_key: PanelKey,
) -> _AgentPanelClanCollapseTarget | None:
    """Resolve every open canonical clan fold in one panel's stable order."""
    global_indices, panel_agents = rendered_panel_slice(owner, panel_key)
    open_keys, _owner_global_index = _open_canonical_clan_keys(
        owner,
        panel_agents=panel_agents,
        global_indices=global_indices,
        candidate_indices=tuple(range(len(panel_agents))),
    )

    if not open_keys:
        return None
    return _AgentPanelClanCollapseTarget(panel_key, open_keys)


def _resolve_group_clan_collapse_target(
    owner: Any,
    group_key: GroupKey,
) -> _AgentGroupClanCollapseTarget | None:
    """Resolve every open canonical clan in one focused-panel group."""
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

    open_keys, owner_global_index = _open_canonical_clan_keys(
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
    return _AgentGroupClanCollapseTarget(
        panel_key=panel_key,
        group_key=group_key,
        fold_keys=open_keys,
        reanchor_index=reanchor_index,
    )


def selected_enclosing_clan_fold_key(
    agents: list[Agent],
    selected_index: int,
) -> str | None:
    """Return the canonical clan fold structurally enclosing one selection."""
    if not (0 <= selected_index < len(agents)):
        return None

    from ...models._agent_tree import (
        agent_fold_key,
        presentation_anchor,
        presentation_anchor_lookup,
        tree_parent_lookup,
    )

    selected = agents[selected_index]
    if selected.is_clan_container:
        return agent_fold_key(selected)

    parent_lookup = tree_parent_lookup(agents)
    anchors = presentation_anchor_lookup(agents, parent_lookup)
    anchor = presentation_anchor(selected, parent_lookup, anchors)
    if not anchor.is_clan_container:
        return None
    return agent_fold_key(anchor)


class AgentPanelClanFoldingMixin(AgentStructuralFoldingMixin):
    """Add scoped clan folding to the Agents structural ladder."""

    _fold_manager: FoldStateManager

    def _resolve_focused_panel_clan_collapse_target(
        self,
    ) -> _AgentPanelClanCollapseTarget | None:
        """Resolve the panel-wide clan rung for selected-panel ``H``."""
        if self.current_tab != "agents" or getattr(
            self, "_agent_panels_grouped", False
        ):
            return None
        resolve_panel = getattr(self, "_resolve_focused_panel", None)
        panel_focus = resolve_panel() if callable(resolve_panel) else None
        if panel_focus is None or panel_focus.collapsed:
            return None
        return resolve_panel_clan_collapse_target(self, panel_focus.panel_key)

    def _resolve_agent_clan_collapse_target(
        self,
    ) -> _AgentGroupClanCollapseTarget | None:
        """Resolve the group-wide clan step that precedes structural ``H``."""
        resolve_group = getattr(self, "_resolve_group_collapse_target", None)
        group_key = resolve_group() if callable(resolve_group) else None
        if group_key is None:
            return None
        return _resolve_group_clan_collapse_target(self, group_key)

    def _narrow_agent_clan_collapse_target_to_selection(
        self,
        target: _AgentGroupClanCollapseTarget,
    ) -> _AgentGroupClanCollapseTarget | None:
        """Narrow one validated group-wide target to the selected open clan."""
        if getattr(self, "_current_group_key", None) is not None:
            return None

        from ...models._agent_tree import agent_fold_key

        agents = getattr(self, "_agents", [])
        selected_index = getattr(self, "current_idx", -1)
        selected_key = selected_enclosing_clan_fold_key(agents, selected_index)
        if selected_key is None or selected_key not in target.fold_keys:
            return None

        selected = agents[selected_index]
        reanchor_index: int | None = None
        if not (
            selected.is_clan_container and agent_fold_key(selected) == selected_key
        ):
            owner_indices = [
                index
                for index, candidate in enumerate(agents)
                if not candidate.is_child_row
                and agent_fold_key(candidate) == selected_key
            ]
            if len(owner_indices) != 1:
                return None
            reanchor_index = owner_indices[0]

        return _AgentGroupClanCollapseTarget(
            panel_key=target.panel_key,
            group_key=target.group_key,
            fold_keys=(selected_key,),
            reanchor_index=reanchor_index,
        )

    def _collapse_agent_clan_folds(
        self,
        target: _AgentGroupClanCollapseTarget | None = None,
    ) -> bool:
        """Drive every validated open clan in one grouping scope closed."""
        if target is None:
            target = self._resolve_agent_clan_collapse_target()
        if target is None:
            return False

        if target.reanchor_index is not None:
            self.current_idx = target.reanchor_index  # type: ignore[attr-defined]
        if not self._fold_manager.collapse_fully_all(list(target.fold_keys)):
            return False
        self._refilter_agents(  # type: ignore[attr-defined]
            refresh_content_index=False
        )
        if target.reanchor_index is not None:
            remember = getattr(self, "_remember_focused_panel_selection", None)
            if callable(remember):
                remember()
        return True

    def _collapse_focused_panel_clan_folds(
        self,
        target: _AgentPanelClanCollapseTarget | None = None,
    ) -> bool:
        """Drive every validated open clan in the selected panel closed."""
        if target is None:
            target = self._resolve_focused_panel_clan_collapse_target()
        if target is None:
            return False
        if not self._fold_manager.collapse_fully_all(list(target.fold_keys)):
            return False
        self._refilter_focused_panel_inner_fold(target.panel_key)  # type: ignore[attr-defined]
        return True


__all__ = [
    "AgentPanelClanFoldingMixin",
    "resolve_panel_clan_collapse_target",
    "selected_enclosing_clan_fold_key",
]
