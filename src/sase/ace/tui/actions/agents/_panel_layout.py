"""Agents-tab panel layout ladder state and transitions.

The ladder (``Split by tribe`` → ``Merged`` → ``All tabs``) is stored as
an :class:`AgentPanelLayout` level plus a remembered last per-tab level.
It maps onto the existing ``(tab_scope, merged)`` scope key: the merged
half is mirrored into the legacy ``_agent_panels_grouped`` boolean so
every existing read site keeps working, and the tab-scope half resolves
to ``ALL_AGENT_TABS`` while the effective level is ``All tabs`` (see
:mod:`sase.ace.tui.actions.agents._tab_scope`).

With the ``agent_tabs`` flag off the ladder collapses to the historical
two-level toggle and every transition stays on the legacy refresh path,
so flag-off behavior is byte-identical.
"""

from __future__ import annotations

import logging
from typing import Any

from ...agent_tabs_flag import agent_tabs_enabled
from ...models.agent_panel_layout import (
    AgentPanelLayout,
    coerce_panel_layout,
    effective_panel_layout,
    layout_notify_label,
    panel_layout_is_merged,
)
from ._agent_tabs_catalog import (
    active_tab_label_for_owner,
    catalog_view_for_owner,
    strip_visible_for_owner,
)

log = logging.getLogger(__name__)


def ensure_panel_layout_state(owner: Any) -> None:
    """Initialize ladder fields for mixin tests that skip startup."""
    if getattr(owner, "_agent_panel_layout", None) is None:
        owner._agent_panel_layout = AgentPanelLayout.SPLIT
    elif not isinstance(owner._agent_panel_layout, AgentPanelLayout):
        owner._agent_panel_layout = coerce_panel_layout(owner._agent_panel_layout)
    if not isinstance(getattr(owner, "_agent_panel_layout_by_tab", None), dict):
        owner._agent_panel_layout_by_tab = {}
    if not hasattr(owner, "_agent_panel_layout_last_tab"):
        owner._agent_panel_layout_last_tab = None


def stored_panel_layout(owner: Any) -> AgentPanelLayout:
    """Return the stored ladder level (``SPLIT`` when unset)."""
    ensure_panel_layout_state(owner)
    level = getattr(owner, "_agent_panel_layout", AgentPanelLayout.SPLIT)
    return level if isinstance(level, AgentPanelLayout) else AgentPanelLayout.SPLIT


def multiple_agent_tabs_for_owner(owner: Any) -> bool:
    """Return True when the catalog offers two or more tabs (R6 gate)."""
    if not agent_tabs_enabled():
        return False
    try:
        return len(catalog_view_for_owner(owner)) >= 2
    except Exception:
        return False


def effective_panel_layout_for_owner(owner: Any) -> AgentPanelLayout:
    """Return the rendered level (R6: stored All tabs is Merged solo)."""
    stored = stored_panel_layout(owner)
    if not agent_tabs_enabled():
        return (
            stored
            if stored is not AgentPanelLayout.ALL_TABS
            else AgentPanelLayout.MERGED
        )
    return effective_panel_layout(stored, multiple_agent_tabs_for_owner(owner))


def panel_layout_merged_for_owner(owner: Any) -> bool:
    """Return True when the effective level renders one merged panel."""
    return panel_layout_is_merged(effective_panel_layout_for_owner(owner))


def sync_panel_grouped_bool(owner: Any) -> bool:
    """Mirror the effective level into ``_agent_panels_grouped``.

    Returns the merged value. Every legacy read site keys off the
    boolean, so it must be refreshed before any rescope or repaint.
    """
    merged = panel_layout_merged_for_owner(owner)
    owner._agent_panels_grouped = merged
    return merged


def _tab_token_for_key(key: Any) -> str | None:
    """Return the persistence token for one tab key, if resolvable."""
    try:
        from sase.core.agent_tab import agent_tab_key_token
    except Exception:
        return None
    try:
        token = agent_tab_key_token(key)
    except Exception:
        return None
    if token is not None:
        return token
    try:
        return f"unresolved:{key.value}"
    except Exception:
        return None


def remembered_layout_for_tab(owner: Any, key: Any) -> AgentPanelLayout:
    """Return the remembered per-tab level for *key* (``SPLIT`` default)."""
    ensure_panel_layout_state(owner)
    token = _tab_token_for_key(key)
    level = owner._agent_panel_layout_by_tab.get(token)
    return level if isinstance(level, AgentPanelLayout) else AgentPanelLayout.SPLIT


def _remember_layout_for_tab(owner: Any, key: Any, level: AgentPanelLayout) -> None:
    """Remember *level* as the per-tab level for *key* (never All tabs)."""
    if level is AgentPanelLayout.ALL_TABS:
        return
    token = _tab_token_for_key(key)
    if token is None:
        return
    ensure_panel_layout_state(owner)
    owner._agent_panel_layout_by_tab[token] = level


def merged_panel_title_for_owner(owner: Any) -> str | None:
    """Return the merged-panel title override for the ladder.

    The All-tabs level renders ``All agents · every tab`` (the title
    builder appends the ``· N`` count). The Merged level shows the active
    tab's label while the strip is visible. Otherwise None, which keeps
    today's ``All agents`` wording byte-identical.
    """
    if not agent_tabs_enabled():
        return None
    try:
        if effective_panel_layout_for_owner(owner) is AgentPanelLayout.ALL_TABS:
            return "All agents · every tab"
        if not panel_layout_merged_for_owner(owner):
            return None
        if not strip_visible_for_owner(owner):
            return None
        return active_tab_label_for_owner(owner)
    except Exception:
        return None


def _selected_identity(owner: Any) -> Any | None:
    """Return the selected agent identity, if any."""
    try:
        agents = getattr(owner, "_agents", ()) or ()
        if getattr(owner, "current_tab", None) == "agents":
            idx = int(getattr(owner, "current_idx", 0))
        else:
            idx = int(getattr(owner, "_agents_last_idx", 0))
        if 0 <= idx < len(agents):
            return agents[idx].identity
    except Exception:
        pass
    return None


def _selected_agent_tab_key(owner: Any) -> Any | None:
    """Return the tab key of the selected row, if resolvable."""
    try:
        agents = getattr(owner, "_agents", ()) or ()
        if getattr(owner, "current_tab", None) == "agents":
            idx = int(getattr(owner, "current_idx", 0))
        else:
            idx = int(getattr(owner, "_agents_last_idx", 0))
        if not 0 <= idx < len(agents):
            return None
        index = getattr(owner, "_agent_tab_index", None)
        key_for = getattr(index, "key_for", None)
        if not callable(key_for):
            return None
        return key_for(agents[idx])
    except Exception:
        return None


def _restore_identity_selection(owner: Any, identity: Any | None) -> bool:
    """Select the row matching *identity*; True when found."""
    if identity is None:
        return False
    try:
        agents = list(getattr(owner, "_agents", ()) or [])
        for pos, row in enumerate(agents):
            try:
                if row.identity == identity:
                    break
            except Exception:
                continue
        else:
            return False
        if getattr(owner, "current_tab", None) == "agents":
            owner.current_idx = pos
        owner._agents_last_idx = pos
        try:
            owner._agents_last_identity = agents[pos].identity
        except Exception:
            owner._agents_last_identity = identity
        return True
    except Exception:
        return False


def _restore_nearest_selection(owner: Any, identity: Any | None, hint: int = 0) -> None:
    """Fall back to the nearest surviving row for *identity*."""
    try:
        from ...util.selection import restore_selection_by_identity

        agents = list(getattr(owner, "_agents", ()) or [])
        if not agents:
            if getattr(owner, "current_tab", None) == "agents":
                owner.current_idx = 0
            owner._agents_last_idx = 0
            return
        prior_row = restore_selection_by_identity(
            agents,
            prior_identity=identity,
            prior_visual_row=int(hint or 0),
            identity_fn=lambda row: row.identity,
        )
        if prior_row is None or not 0 <= prior_row < len(agents):
            prior_row = 0
        if getattr(owner, "current_tab", None) == "agents":
            owner.current_idx = prior_row
        owner._agents_last_idx = prior_row
        try:
            owner._agents_last_identity = agents[prior_row].identity
        except Exception:
            owner._agents_last_identity = identity
    except Exception:
        log.exception("Panel layout selection restore failed")


def set_panel_layout(owner: Any, level: AgentPanelLayout, *, reason: str = "") -> bool:
    """Apply ladder *level* with an anchor-preserving transition.

    Zooming out keeps the selected node; zooming in from All tabs lands
    on the selected node's tab. Choosing a tab while at All tabs drills
    in separately through the tab switch (see ``_switch_agents_tab``).
    Returns True when the stored level changed.
    """
    del reason
    ensure_panel_layout_state(owner)
    level = coerce_panel_layout(level)
    stored = stored_panel_layout(owner)
    if not agent_tabs_enabled():
        merged = panel_layout_is_merged(level)
        changed = bool(getattr(owner, "_agent_panels_grouped", False)) != merged
        owner._agent_panel_layout = (
            AgentPanelLayout.MERGED if merged else AgentPanelLayout.SPLIT
        )
        owner._agent_panels_grouped = merged
        if not changed:
            return False
        # Historical toggle path verbatim: the incremental finalize path
        # used on-flag can defer row paints, so flag-off keeps the direct
        # synchronous list repaint.
        if getattr(owner, "_panel_fold_hint_mode_active", False):
            teardown = getattr(owner, "_teardown_panel_fold_hint_mode", None)
            if callable(teardown):
                try:
                    teardown(refresh_titles=False)
                except Exception:
                    pass
        disarm = getattr(owner, "_disarm_panel_isolation_revert", None)
        if callable(disarm):
            try:
                disarm(refresh=False)
            except Exception:
                pass
        owner._expanded_panel_focus = False
        try:
            from ._panel_fold_intent import clear_panel_fold_intents

            clear_panel_fold_intents(owner)
        except Exception:
            pass
        owner._current_group_key = None
        owner._current_attempt_number = None
        invalidate = getattr(owner, "_invalidate_agent_panel_cache", None)
        if callable(invalidate):
            try:
                invalidate()
            except Exception:
                pass
        refresh = getattr(owner, "_refresh_agents_display", None)
        if callable(refresh):
            try:
                refresh(list_changed=True)
            except Exception:
                log.exception("Panel layout refresh failed")
        try:
            owner.notify(  # type: ignore[attr-defined]
                f"Panel layout: {layout_notify_label(owner._agent_panel_layout)}",
                timeout=1.5,
            )
        except Exception:
            pass
        return True
    if level is stored:
        sync_panel_grouped_bool(owner)
        return False
    identity = _selected_identity(owner)
    active = getattr(owner, "_active_agent_tab", None)
    if stored is AgentPanelLayout.ALL_TABS and level is not AgentPanelLayout.ALL_TABS:
        # Zoom in: land on the selected node's tab at the chosen level.
        target = _selected_agent_tab_key(owner)
        if target is None:
            target = getattr(owner, "_agent_panel_layout_last_tab", None)
        if target is None:
            target = active
        owner._agent_panel_layout_last_tab = None
        owner._agent_panel_layout = level
        if target is not None and target != active:
            owner._active_agent_tab = target
            try:
                owner._agent_tab_arrivals.discard(target)  # type: ignore[attr-defined]
            except Exception:
                pass
            state_changed = getattr(owner, "_agent_tab_state_changed", None)
            if callable(state_changed):
                try:
                    state_changed()
                except Exception:
                    pass
        _remember_layout_for_tab(owner, target, level)
        fallback = target
    else:
        if level is AgentPanelLayout.ALL_TABS:
            _remember_layout_for_tab(owner, active, stored)
            owner._agent_panel_layout_last_tab = active
        else:
            _remember_layout_for_tab(owner, active, level)
        owner._agent_panel_layout = level
        fallback = active
    sync_panel_grouped_bool(owner)
    _refresh_after_layout_change(owner, anek=identity, fallback_tab=fallback)
    try:
        owner.notify(  # type: ignore[attr-defined]
            f"Panel layout: {layout_notify_label(level)}",
            timeout=1.5,
        )
    except Exception:
        pass
    return True


def _refresh_after_layout_change(
    owner: Any, anek: Any = None, *, fallback_tab: Any = None
) -> None:
    """Rescope, restore the anchor, and repaint after a layout change."""
    if getattr(owner, "_panel_fold_hint_mode_active", False):
        teardown = getattr(owner, "_teardown_panel_fold_hint_mode", None)
        if callable(teardown):
            try:
                teardown(refresh_titles=False)
            except Exception:
                pass
    disarm = getattr(owner, "_disarm_panel_isolation_revert", None)
    if callable(disarm):
        try:
            disarm(refresh=False)
        except Exception:
            pass
    owner._expanded_panel_focus = False
    try:
        from ._panel_fold_intent import clear_panel_fold_intents

        clear_panel_fold_intents(owner)
    except Exception:
        pass
    owner._current_group_key = None
    owner._current_attempt_number = None
    rescope = getattr(owner, "_rescope_agents_to_active_tab", None)
    if callable(rescope):
        try:
            rescope()
        except Exception:
            log.exception("Panel layout re-scope failed")
    else:
        invalidate = getattr(owner, "_invalidate_agent_panel_cache", None)
        if callable(invalidate):
            try:
                invalidate()
            except Exception:
                pass
        refresh = getattr(owner, "_refresh_agents_display", None)
        if callable(refresh):
            try:
                refresh(list_changed=True)
            except Exception:
                log.exception("Panel layout refresh failed")
    if not _restore_identity_selection(owner, anek):
        if fallback_tab is not None:
            restore_tab = getattr(owner, "_restore_tab_memory", None)
            if callable(restore_tab):
                try:
                    restore_tab(fallback_tab)
                except Exception:
                    pass
                else:
                    _repaint_after_restore(owner)
                    return
        _restore_nearest_selection(owner, anek)
    _repaint_after_restore(owner)


def _repaint_after_restore(owner: Any) -> None:
    """Refresh the strip, titles, and info row after anchor restore."""
    refresh_display = getattr(owner, "_refresh_agents_display", None)
    if callable(refresh_display):
        try:
            refresh_display(list_changed=True)
        except Exception:
            pass
    refresh_strip = getattr(owner, "_refresh_agent_tab_strip", None)
    if callable(refresh_strip):
        try:
            refresh_strip()
        except Exception:
            pass
    update_info = getattr(owner, "_update_agents_info_panel", None)
    if callable(update_info):
        try:
            update_info()
        except Exception:
            pass


__all__ = [
    "effective_panel_layout_for_owner",
    "ensure_panel_layout_state",
    "merged_panel_title_for_owner",
    "multiple_agent_tabs_for_owner",
    "panel_layout_merged_for_owner",
    "remembered_layout_for_tab",
    "set_panel_layout",
    "stored_panel_layout",
    "sync_panel_grouped_bool",
]
