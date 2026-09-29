"""Synchronous tab switching and All-tabs drill-in (tab-state-keys).

``AgentTabsSwitchCoreMixin`` synchronously re-scopes the cached query
result to the active tab, restores the target tab's memory, refreshes
the strip, and schedules persistence.
"""

from __future__ import annotations

import logging

from sase.core.agent_tab import AgentTabKey

log = logging.getLogger(__name__)

_TAB_SWITCH_PERF_ACTION = "agents_tab_switch"


class AgentTabsSwitchCoreMixin:
    """Synchronous tab switching and All-tabs drill-in."""

    _active_agent_tab: AgentTabKey
    _agent_tab_latched_key: AgentTabKey | None

    def _switch_agents_tab(self, key: AgentTabKey, *, reason: str = "") -> bool:
        """Synchronously switch to *key*; True when the scope changed.

        Saves the current tab's memory, re-scopes the cached query result
        without I/O, restores the target tab's memory, refreshes the strip,
        and schedules persistence. A no-op when *key* equals the
        active key.
        """
        del reason
        self._ensure_agent_tabs_state()  # type: ignore[attr-defined]
        if not isinstance(key, AgentTabKey):
            return False
        try:
            from ...models.agent_panel_layout import AgentPanelLayout
            from ._panel_layout import ensure_panel_layout_state, stored_panel_layout

            ensure_panel_layout_state(self)
            if stored_panel_layout(self) is AgentPanelLayout.ALL_TABS:
                return self._drill_into_tab_from_all(key)
        except Exception:
            log.exception("Panel layout drill-in check failed")
        if key == self._active_agent_tab:  # type: ignore[attr-defined]
            return False
        perf_begin = getattr(self, "_jk_perf_begin", None)
        if callable(perf_begin):
            try:
                perf_begin(_TAB_SWITCH_PERF_ACTION)
            except Exception:
                pass
        self._remember_active_tab_memory()  # type: ignore[attr-defined]
        self._active_agent_tab = key  # type: ignore[attr-defined]
        self._agent_tabs_user_switched = True  # type: ignore[attr-defined]
        try:
            self._agent_tab_arrivals.discard(key)  # type: ignore[attr-defined]
        except Exception:
            pass
        if key != getattr(self, "_agent_tab_latched_key", None):
            self._agent_tab_latched_key = None  # type: ignore[attr-defined]
        rescope = getattr(self, "_rescope_agents_to_active_tab", None)
        if callable(rescope):
            try:
                rescope()
            except Exception:
                log.exception("Tab switch re-scope failed")
        self._restore_tab_memory(key)  # type: ignore[attr-defined]
        self._refresh_agent_tab_strip()  # type: ignore[attr-defined]
        self._agent_tab_state_changed()  # type: ignore[attr-defined]
        perf = getattr(self, "_jk_perf", None)
        if perf is not None:
            try:
                perf.mark_model_updated()
            except Exception:
                pass
            call_after = getattr(self, "call_after_refresh", None)
            if callable(call_after):
                try:
                    call_after(perf.mark_painted)
                except Exception:
                    pass
        return True

    def _drill_into_tab_from_all(self, key: AgentTabKey, *, reason: str = "") -> bool:
        """Drill from the All-tabs level into *key*.

        Choosing a tab (strip click, ``[``/``]``, picker) at the All-tabs
        level enters that tab at its remembered per-tab level. The target
        tab's own selection memory is restored. Always applies, even when
        *key* is the tab the ladder was entered from.
        """
        del reason
        from ._panel_layout import (
            ensure_panel_layout_state,
            remembered_layout_for_tab,
            sync_panel_grouped_bool,
        )

        self._ensure_agent_tabs_state()  # type: ignore[attr-defined]
        ensure_panel_layout_state(self)
        level = remembered_layout_for_tab(self, key)
        self._agent_panel_layout = level  # type: ignore[attr-defined]
        self._active_agent_tab = key  # type: ignore[attr-defined]
        self._agent_panel_layout_last_tab = None  # type: ignore[attr-defined]
        self._agent_tabs_user_switched = True  # type: ignore[attr-defined]
        try:
            self._agent_tab_arrivals.discard(key)  # type: ignore[attr-defined]
        except Exception:
            pass
        if key != getattr(self, "_agent_tab_latched_key", None):
            self._agent_tab_latched_key = None  # type: ignore[attr-defined]
        sync_panel_grouped_bool(self)
        rescope = getattr(self, "_rescope_agents_to_active_tab", None)
        if callable(rescope):
            try:
                rescope()
            except Exception:
                log.exception("Drill-in re-scope failed")
        self._restore_tab_memory(key)  # type: ignore[attr-defined]
        self._refresh_agent_tab_strip()  # type: ignore[attr-defined]
        state_changed = getattr(self, "_agent_tab_state_changed", None)
        if callable(state_changed):
            try:
                state_changed()
            except Exception:
                pass
        update_info = getattr(self, "_update_agents_info_panel", None)
        if callable(update_info):
            try:
                update_info()
            except Exception:
                pass
        return True


__all__ = [
    "AgentTabsSwitchCoreMixin",
]
