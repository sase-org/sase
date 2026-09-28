"""Active-tab scope state and tab-keyed panel helpers (scope-stage).

With the ``agent_tabs`` flag off every helper is the identity: the scope is
the default key, scoping returns its input unchanged, and panel/selection
keys stay bare. With the flag on, panel and selection keys are namespaced by
the scope token so folds, sticky panels, and selection memory are kept per
tab.
"""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from sase.core.agent_tab import DEFAULT_AGENT_TAB_KEY, AgentTabKey

from ...agent_tabs_flag import agent_tabs_enabled
from ...models.agent_tab_index import (
    ALL_AGENT_TABS,
    AgentTabScope,
    agent_tab_scope_token,
    scope_agents_to_tab,
)

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType
    from ...models.agent_panels import PanelKey
    from ...models.agent_tab_index import AgentTabIndex


def current_agent_tab_scope(owner: Any) -> AgentTabScope:
    """Return the active tab scope, defaulting to the default key.

    The flag-off default keeps fold scopes stable when the flag is later
    turned on.
    """
    if not agent_tabs_enabled():
        return DEFAULT_AGENT_TAB_KEY
    scope = getattr(owner, "_active_agent_tab", None)
    if scope is ALL_AGENT_TABS:
        return ALL_AGENT_TABS
    if isinstance(scope, AgentTabKey):
        return scope
    return DEFAULT_AGENT_TAB_KEY


def current_agent_tab_scope_token(owner: Any) -> str:
    """Return the hashable token for the owner's active tab scope."""
    return agent_tab_scope_token(current_agent_tab_scope(owner))


def refresh_agent_tab_index(owner: Any, roster: list[Agent] | None = None) -> Any:
    """Rebuild (memoized) the tab index over the tab-independent roster.

    Returns None with the flag off. The roster defaults to
    ``_agents_with_children`` so the index covers roots hidden by the query.
    """
    if not agent_tabs_enabled():
        owner._agent_tab_index = None
        return None
    from ...agent_tabs_settings import agent_tabs_view_config

    if roster is None:
        candidate = getattr(owner, "_agents_with_children", None)
        roster = candidate if isinstance(candidate, list) else []
    from ...models.agent_tab_index import cached_agent_tab_index

    try:
        view_config = agent_tabs_view_config()
    except Exception:
        owner._agent_tab_index = None
        return None
    index = cached_agent_tab_index(roster, view_config)
    owner._agent_tab_index = index
    # Tab-state-keys maintenance (startup selection, latch, machine
    # fallback). The hook only moves `_active_agent_tab` bookkeeping; the
    # caller re-applies the scope right after, so no rescope happens here.
    reconcile = getattr(owner, "_reconcile_active_agent_tab", None)
    if callable(reconcile):
        try:
            reconcile()
        except Exception:
            log.exception("Agent tab reconcile failed")
    return index


def _scoped_agents_for_owner(owner: Any, rows: list[Agent]) -> list[Agent]:
    """Return *rows* filtered to the owner's active tab (identity off-flag)."""
    if not agent_tabs_enabled():
        return rows
    index = getattr(owner, "_agent_tab_index", None)
    return scope_agents_to_tab(
        rows, index, current_agent_tab_scope(owner), enabled=True
    )


def remove_agents_from_views(
    owner: Any,
    identities: set[tuple[AgentType, str, str | None]],
    *,
    reproject_clan: bool = False,
) -> None:
    """Drop *identities* from the cached query result and the scoped view.

    Callers must have already updated ``_agents_with_children`` (including
    any clan re-projection). The cached tab-independent result is filtered
    first so a later tab switch cannot resurrect a removed row, then the
    active scope is re-applied.
    """
    removed = set(identities)
    query_result = getattr(owner, "_agents_query_result", None)
    if query_result is None:
        query_result = list(getattr(owner, "_agents", ()))
    filtered = [a for a in query_result if a.identity not in removed]
    if reproject_clan and len(filtered) != len(query_result):
        from ...models._agent_tree import project_clan_tree

        filtered = project_clan_tree(filtered)
    owner._agents_query_result = filtered
    refresh_agent_tab_index(owner)
    owner._agents = _scoped_agents_for_owner(owner, filtered)
    invalidate = getattr(owner, "_invalidate_agent_panel_cache", None)
    if callable(invalidate):
        invalidate()


def _rescope_agents_to_active_tab(owner: Any) -> None:
    """Re-apply the active tab scope to the cached query result (no I/O).

    Applies the scope, invalidates the panel cache, re-syncs the panel
    group, reconciles fold registries for the new scope, and refreshes the
    display through the existing incremental or rebuild path.
    """
    from ...models.agent_group_fold import enumerate_panel_group_keys
    from ...models.agent_groups import GroupingMode
    from ._fold_scope import reconcile_panel_fold_registries

    query_result = list(getattr(owner, "_agents_query_result", None) or [])
    previous_agents = list(getattr(owner, "_agents", ()))
    owner._agents = _scoped_agents_for_owner(owner, query_result)
    invalidate = getattr(owner, "_invalidate_agent_panel_cache", None)
    if callable(invalidate):
        invalidate()
    sync_group = getattr(owner, "_sync_panel_group", None)
    if callable(sync_group):
        sync_group()
    grouping_mode = getattr(owner, "_grouping_mode", None)
    if grouping_mode is None:
        grouping_mode = GroupingMode.STANDARD
    reconcile_panel_fold_registries(
        owner,
        enumerate_panel_group_keys(
            owner._agents,
            mode=grouping_mode,
            merged=bool(getattr(owner, "_agent_panels_grouped", False)),
            tab_scope=current_agent_tab_scope_token(owner),
        ),
    )
    if getattr(owner, "current_tab", None) == "agents":
        incremental = getattr(owner, "_refresh_agents_display_after_finalize", None)
        if callable(incremental):
            incremental(previous_agents=previous_agents, defer_detail=True)
        else:
            refresh = getattr(owner, "_refresh_agents_display", None)
            if callable(refresh):
                refresh(list_changed=True, defer_detail=True)


def _selection_scope_token(owner: Any) -> str | None:
    """Return the scoping token, or None when selection keys stay bare."""
    if not agent_tabs_enabled():
        return None
    return current_agent_tab_scope_token(owner)


def _scoped_selection_key(owner: Any, panel_key: PanelKey) -> Any:
    """Return the selection-memory key for *panel_key* under the active scope."""
    token = _selection_scope_token(owner)
    if token is None:
        return panel_key
    return (token, panel_key)


def scoped_selection_get(owner: Any, panel_key: PanelKey, default: Any = None) -> Any:
    """Return the remembered stop for *panel_key* in the active scope."""
    memory = getattr(owner, "_panel_selection_memory", None)
    if not isinstance(memory, dict):
        return default
    return memory.get(_scoped_selection_key(owner, panel_key), default)


def scoped_selection_set(owner: Any, panel_key: PanelKey, stop: Any) -> None:
    """Remember *stop* for *panel_key* in the active scope."""
    memory = getattr(owner, "_panel_selection_memory", None)
    if not isinstance(memory, dict):
        memory = {}
        owner._panel_selection_memory = memory
    memory[_scoped_selection_key(owner, panel_key)] = stop


def scoped_selection_pop(owner: Any, panel_key: PanelKey, default: Any = None) -> Any:
    """Drop the remembered stop for *panel_key* in the active scope."""
    memory = getattr(owner, "_panel_selection_memory", None)
    if not isinstance(memory, dict):
        return default
    return memory.pop(_scoped_selection_key(owner, panel_key), default)


def scoped_sticky_key(owner: Any, panel_key: PanelKey) -> Any:
    """Return the session-sticky key for *panel_key* under the active scope."""
    token = _selection_scope_token(owner)
    if token is None:
        return panel_key
    return (token, panel_key)


def _sticky_key_scope(key: Any) -> str | None:
    """Return the scope token embedded in a sticky/selection key, if any."""
    if isinstance(key, tuple) and len(key) == 2 and isinstance(key[0], str):
        return key[0]
    return None


def unstick_panel_key(key: Any) -> Any:
    """Strip the scope namespace from a sticky/selection key, if present."""
    if isinstance(key, tuple) and len(key) == 2 and isinstance(key[0], str):
        return key[1]
    return key


def sticky_key_in_scope(owner: Any, key: Any) -> bool:
    """Return True when *key* belongs to the owner's active scope."""
    token = _selection_scope_token(owner)
    if token is None:
        return _sticky_key_scope(key) is None
    if _sticky_key_scope(key) is None:
        return token == "default"
    return _sticky_key_scope(key) == token


class AgentTabScopeMixin:
    """Owner methods for the active-tab scope stage (no UI wiring)."""

    def _agent_tab_scope(self) -> AgentTabScope:
        """Return the active tab scope (default key when the flag is off)."""
        return current_agent_tab_scope(self)

    def _agent_tab_scope_token(self) -> str:
        """Return the hashable token for the active tab scope."""
        return current_agent_tab_scope_token(self)

    def _refresh_agent_tab_index(
        self, roster: list[Agent] | None = None
    ) -> AgentTabIndex | None:
        """Rebuild (memoized) the tab index; None with the flag off."""
        return refresh_agent_tab_index(self, roster)

    def _remove_agents_from_views(
        self,
        identities: set[tuple[AgentType, str, str | None]],
        *,
        reproject_clan: bool = False,
    ) -> None:
        """Drop *identities* from the cached result and the scoped view."""
        remove_agents_from_views(self, identities, reproject_clan=reproject_clan)

    def _rescope_agents_to_active_tab(self) -> None:
        """Re-apply the active tab scope without I/O (Phase 3 builds on this)."""
        _rescope_agents_to_active_tab(self)


__all__ = [
    "AgentTabScopeMixin",
    "current_agent_tab_scope",
    "current_agent_tab_scope_token",
    "refresh_agent_tab_index",
    "remove_agents_from_views",
    "scoped_selection_get",
    "scoped_selection_pop",
    "scoped_selection_set",
    "scoped_sticky_key",
    "sticky_key_in_scope",
    "unstick_panel_key",
]
