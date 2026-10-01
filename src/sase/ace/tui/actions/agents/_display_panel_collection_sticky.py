"""Session-sticky panel identity store and placement helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._display_panel_state import PanelRefreshStateMixin
from ._tab_scope import sticky_key_in_scope, unstick_panel_key

if TYPE_CHECKING:
    from ...models.agent import AgentType
    from ...models.agent_panels import PanelKey


class SessionStickyStoreMixin(PanelRefreshStateMixin):
    """Session-sticky mounting store, query scoping, and placement map."""

    def _session_sticky_query_value(self) -> str:
        """Return the committed Agents query that owns session-sticky panels."""
        return getattr(self, "_agent_search_query", "") or ""

    def _session_mounted_identity_map(
        self,
    ) -> dict[PanelKey, set[tuple[AgentType, str, str | None]]]:
        """Return the identities that mounted each key, cleared on query change."""
        query = self._session_sticky_query_value()
        last = getattr(self, "_session_sticky_query", None)
        mounted = getattr(self, "_session_mounted_panel_identities", None)
        if mounted is None:
            mounted = {}
            self._session_mounted_panel_identities = mounted  # type: ignore[attr-defined]
        if last is None:
            self._session_sticky_query = query  # type: ignore[attr-defined]
        elif last != query:
            mounted.clear()
            self._session_sticky_query = query  # type: ignore[attr-defined]
            backing = getattr(self, "_session_mounted_panel_backing", None)
            if backing is not None:
                backing.clear()
            unaccounted = getattr(self, "_session_sticky_unaccounted_since", None)
            if unaccounted is not None:
                unaccounted.clear()
            pending = getattr(self, "_session_sticky_pending_retired", None)
            if pending is not None:
                pending.clear()
        return mounted

    def _session_sticky_unaccounted_since_map(
        self,
    ) -> dict[tuple[AgentType, str, str | None], float]:
        """Return first-unaccounted monotonic timestamps per sticky identity.

        Cleared alongside the sticky store on a committed-query change, when
        an identity renders again, when it retires, and when it is no longer
        recorded under any key.
        """
        self._session_mounted_identity_map()
        unaccounted = getattr(self, "_session_sticky_unaccounted_since", None)
        if unaccounted is None:
            unaccounted = {}
            self._session_sticky_unaccounted_since = unaccounted  # type: ignore[attr-defined]
        return unaccounted

    def _session_sticky_pending_retired_set(self) -> set[PanelKey]:
        """Return authoritative retirements awaiting the next panel sync."""
        self._session_mounted_identity_map()
        pending = getattr(self, "_session_sticky_pending_retired", None)
        if pending is None:
            pending = set()
            self._session_sticky_pending_retired = pending  # type: ignore[attr-defined]
        return pending

    def _session_mounted_backing_map(
        self,
    ) -> dict[
        tuple[AgentType, str, str | None], set[tuple[AgentType, str, str | None]]
    ]:
        """Return container identities mapped to their backing member identities.

        The map unions every member set ever recorded under one committed
        query and is cleared with the sticky store on query change, so a
        synthetic clan container retires once all of its members are
        authoritatively gone even though the container itself is never
        dismissed.
        """
        # Route through the identity map so a committed-query change clears
        # the backing alongside the store no matter which helper runs first.
        self._session_mounted_identity_map()
        backing = getattr(self, "_session_mounted_panel_backing", None)
        if backing is None:
            backing = {}
            self._session_mounted_panel_backing = backing  # type: ignore[attr-defined]
        return backing

    def _session_mounted_panel_key_set(self) -> set[PanelKey]:
        """Return a snapshot of mounted-this-session keys for the active scope.

        With the flag off the sticky keys are bare panel keys, exactly as
        before; with the flag on only the active scope's panels are
        returned, so one tab's sticky panels never leak into another tab.
        """
        return {
            unstick_panel_key(key)
            for key in self._session_mounted_identity_map()
            if sticky_key_in_scope(self, key)
        }

    def _sticky_placement_map(
        self,
    ) -> dict[tuple[AgentType, str, str | None], tuple[PanelKey, bool]]:
        """Return roster identity -> (panel key, in active scope).

        Built over the tab- and fold-independent roster so a row that moved
        to another tribe, another tab, or a re-keyed container is positive
        evidence its old panel is empty. Panel keys use the same
        root-anchored rule as the renderer.
        """
        from ...models.agent_panels import normalize_panel_key, panel_key_per_agent
        from ...models.agent_tab_index import ALL_AGENT_TABS
        from ._tab_scope import current_agent_tab_scope

        roster = getattr(self, "_agents_with_children", None) or self._agents
        merge_tribe_panels = getattr(self, "_agent_panels_grouped", False)
        keys = panel_key_per_agent(roster, merge_tribe_panels=merge_tribe_panels)
        scope = current_agent_tab_scope(self)
        index = getattr(self, "_agent_tab_index", None)
        placement: dict[tuple[AgentType, str, str | None], tuple[PanelKey, bool]] = {}
        if scope is ALL_AGENT_TABS or index is None:
            for agent, key in zip(roster, keys, strict=True):
                placement[agent.identity] = (normalize_panel_key(key), True)
        else:
            for agent, key in zip(roster, keys, strict=True):
                try:
                    in_scope = index.key_for(agent) == scope
                except Exception:
                    in_scope = True
                placement[agent.identity] = (normalize_panel_key(key), in_scope)
        return placement
