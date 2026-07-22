"""Selected-panel clan fold target resolution and transitions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ._folding_agent_tree import AgentStructuralFoldingMixin
from ._navigation_order import rendered_panel_slice

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent_panels import PanelKey
    from ...models.fold_state import FoldStateManager


@dataclass(frozen=True, slots=True)
class _AgentPanelClanCollapseTarget:
    """Validated open clan folds owned by one selected tribe panel."""

    panel_key: PanelKey
    fold_keys: tuple[str, ...]


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


def _resolve_panel_clan_collapse_target(
    owner: Any,
    panel_key: PanelKey,
) -> _AgentPanelClanCollapseTarget | None:
    """Resolve every open canonical clan fold in one panel's stable order."""
    from ...models._agent_tree import agent_fold_key
    from ...models.fold_state import FoldLevel

    _global_indices, panel_agents = rendered_panel_slice(owner, panel_key)

    # FoldStateManager is global across panels. Validate every candidate key
    # against the complete cached projection, including rows filtered out of
    # the current render, so an alias cannot turn a panel-local action global.
    loaded_agents = getattr(owner, "_agents_with_children", None) or getattr(
        owner, "_agents", panel_agents
    )
    owners_by_key: dict[str, list[Agent]] = {}
    for candidate in loaded_agents:
        candidate_key = agent_fold_key(candidate)
        if candidate_key is not None:
            owners_by_key.setdefault(candidate_key, []).append(candidate)

    open_keys: list[str] = []
    seen: set[str] = set()
    for candidate in panel_agents:
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
        open_keys.append(fold_key)

    if not open_keys:
        return None
    return _AgentPanelClanCollapseTarget(panel_key, tuple(open_keys))


class AgentPanelClanFoldingMixin(AgentStructuralFoldingMixin):
    """Add selected-panel clan folding to the Agents structural ladder."""

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
        return _resolve_panel_clan_collapse_target(self, panel_focus.panel_key)

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


__all__ = ["AgentPanelClanFoldingMixin"]
