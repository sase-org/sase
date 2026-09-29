"""Tab strip ids, descriptors, refresh, cycling, and empty states.

``AgentTabsSwitchStripMixin`` maps strip widget ids back to tab keys,
projects query-aware descriptors, pushes them on change, cycles the
active tab, and describes the active tab's empty cause.
"""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from sase.core.agent_tab import (
    DEFAULT_AGENT_TAB_KEY,
    AgentTabKey,
    agent_tab_key_token,
)

from ...models.agent_tab_index import AgentTabCatalogEntry
from ._agent_tabs_catalog import (
    active_tab_label_for_owner,
    agent_tab_health_for_owner,
    bulk_scope_label_for_owner,
    catalog_view_for_owner,
    strip_visible_for_owner,
)

if TYPE_CHECKING:
    from ...models.agent_tab_descriptors import AgentTabStyleInputs
    from ...widgets.agent_tab_strip import AgentTabEmptyState

log = logging.getLogger(__name__)


def _all_tabs_level_active(owner: Any) -> bool:
    """Return True when the All-tabs ladder level is effectively active."""
    try:
        from ...models.agent_panel_layout import AgentPanelLayout
        from ._panel_layout import effective_panel_layout_for_owner

        return effective_panel_layout_for_owner(owner) is AgentPanelLayout.ALL_TABS
    except Exception:
        return False


def _strip_id_for_key(key: AgentTabKey) -> str:
    """Return the ``PanelTabStrip`` id for *key*.

    Persistable keys use their token; unresolved-machine keys (which have
    no token) use a session-scoped ``unresolved:<alias>`` id.
    """
    token = agent_tab_key_token(key)
    if token is not None:
        return token
    return f"unresolved:{key.value}"


def _key_for_strip_id(
    tab_id: str, entries: tuple[AgentTabCatalogEntry, ...]
) -> AgentTabKey | None:
    """Map a clicked strip id back to its tab key, or None when unknown.

    Only catalog entries match: strip ids are built from the catalog view,
    so anything else is a stale or foreign click and must not switch to a
    phantom tab.
    """
    for entry in entries:
        if _strip_id_for_key(entry.key) == tab_id:
            return entry.key
    return None


def _top_level_count(rows: list[Any]) -> int:
    """Count top-level rows, degrading to the raw count on error."""
    try:
        from ...models._agent_tree import agent_is_tree_child

        count = 0
        for row in rows:
            try:
                if not agent_is_tree_child(row):
                    count += 1
            except Exception:
                count += 1
        return count
    except Exception:
        return len(rows)


class AgentTabsSwitchStripMixin:
    """Strip ids, descriptors, refresh, cycling, and empty states."""

    _active_agent_tab: AgentTabKey
    _agent_tab_strip_signature: Any | None

    def _agent_tab_catalog_view(self) -> tuple[AgentTabCatalogEntry, ...]:
        """Return the strip's catalog view (index entries plus latch)."""
        return catalog_view_for_owner(self)

    def _agent_tab_strip_visible(self) -> bool:
        """Return True when the minimal tab strip should render."""
        return strip_visible_for_owner(self)

    def _agent_bulk_scope_label(self) -> str | None:
        """Return the bulk-confirmation scope wording for the active tab.

        ``on <tab label>`` when the flag is on and the strip is visible,
        ``across all tabs`` at the ``ALL_AGENT_TABS`` scope, else None (which
        keeps today's confirmation text byte-identical).
        """
        return bulk_scope_label_for_owner(self)

    def _cycle_agents_tab(self, step: int) -> None:
        """Cycle the active tab by *step* with wraparound.

        A no-op when the strip is hidden: with fewer than two tabs there is
        nowhere to go, and the latch keeps its own empty selection.
        """
        self._ensure_agent_tabs_state()  # type: ignore[attr-defined]
        if not self._agent_tab_strip_visible():
            return
        if getattr(self, "current_tab", None) != "agents":
            return
        entries = self._agent_tab_catalog_view()
        if len(entries) < 2:
            return
        active = self._active_agent_tab  # type: ignore[attr-defined]
        keys = [entry.key for entry in entries]
        try:
            pos = keys.index(active)
        except ValueError:
            pos = 0 if step > 0 else len(keys) - 1
            self._switch_agents_tab(keys[pos], reason="cycle")  # type: ignore[attr-defined]
            return
        self._switch_agents_tab(keys[(pos + step) % len(keys)], reason="cycle")  # type: ignore[attr-defined]

    def action_next_agents_tab(self) -> None:
        """Cycle to the next agent tab (``]``) with wraparound."""
        self._cycle_agents_tab(1)

    def action_prev_agents_tab(self) -> None:
        """Cycle to the previous agent tab (``[``) with wraparound."""
        self._cycle_agents_tab(-1)

    def action_pick_agents_tab(self) -> None:
        """Open the minimal tab picker and switch on select."""
        self._ensure_agent_tabs_state()  # type: ignore[attr-defined]
        if getattr(self, "current_tab", None) != "agents":
            return
        try:
            from textual.screen import ModalScreen
        except Exception:
            return
        if isinstance(getattr(self, "screen", None), ModalScreen):
            return
        entries = self._agent_tab_catalog_view()
        if len(entries) < 2:
            return
        active = self._active_agent_tab  # type: ignore[attr-defined]

        from ...modals.agent_tab_picker_modal import AgentTabPickerModal

        def _on_choice(chosen: AgentTabKey | None) -> None:
            if chosen is None or getattr(self, "current_tab", None) != "agents":
                return
            try:
                self._switch_agents_tab(chosen, reason="pick")  # type: ignore[attr-defined]
            except Exception:
                log.exception("Tab picker switch failed")

        try:
            descriptors = self._descriptors_for_strip(entries, active)
        except Exception:
            descriptors = ()
        try:
            self.push_screen(  # type: ignore[attr-defined]
                AgentTabPickerModal(entries, active, descriptors=descriptors),
                _on_choice,
            )
        except Exception:
            log.exception("Tab picker failed to open")

    def _on_agents_tab_strip_clicked(self, tab_id: str) -> None:
        """Switch to the clicked strip tab, ignoring unknown ids."""
        self._ensure_agent_tabs_state()  # type: ignore[attr-defined]
        key = _key_for_strip_id(tab_id, self._agent_tab_catalog_view())
        if key is None:
            return
        try:
            self._switch_agents_tab(key, reason="strip")  # type: ignore[attr-defined]
        except Exception:
            log.exception("Tab strip switch failed")

    def _descriptors_for_strip(
        self, entries: tuple[AgentTabCatalogEntry, ...], active: AgentTabKey | None
    ) -> tuple[Any, ...]:
        """Project query-aware descriptors for *entries* (no I/O).

        Existence comes from *entries* (built over the tab-independent
        roster); counts and attention come from the committed
        tab-independent query result. Style inputs are the token-cached
        worker resolution, so this stays free of disk and network work.
        """
        from ...models.agent_tab_descriptors import (
            AgentTabStyleInputs,
            project_agent_tab_descriptors,
            resolve_agent_tab_style_inputs,
        )

        index = getattr(self, "_agent_tab_index", None)
        key_for = getattr(index, "key_for", None) if index is not None else None
        if not callable(key_for):

            def key_for(
                _row: Any, _default: AgentTabKey = DEFAULT_AGENT_TAB_KEY
            ) -> AgentTabKey:
                return _default

        query_result = list(getattr(self, "_agents_query_result", None) or [])
        unread: set[Any] = getattr(self, "_unread_completed_agent_ids", set()) or set()
        load_state = getattr(self, "_agent_load_state", None)
        incomplete = bool(
            getattr(load_state, "has_more", False)
            or getattr(load_state, "query_incomplete", False)
        )
        health, extras, _active_text = agent_tab_health_for_owner(self)
        styles: AgentTabStyleInputs | None
        try:
            styles = resolve_agent_tab_style_inputs(allow_disk=False)
        except Exception:
            styles = None
        machine_mode = bool(styles.machine_mode) if styles is not None else False
        try:
            from ...models.agent_tab_descriptors import machine_off_tab_extras

            for off_key, off_text in machine_off_tab_extras(
                query_result,
                key_for,
                tuple(entries),
                machine_mode=machine_mode,
            ).items():
                if off_key in extras and extras[off_key]:
                    extras[off_key] = f"{extras[off_key]} · {off_text}"
                else:
                    extras[off_key] = off_text
        except Exception:  # noqa: BLE001 - off-tab counts are best-effort.
            pass
        jump_hints = dict(getattr(self, "_agent_tab_jump_hints", None) or {})
        return project_agent_tab_descriptors(
            tuple(entries),
            query_result,
            key_for,
            active_key=active,
            unread_ids=unread,
            incomplete=incomplete,
            health_by_key=health,
            arrivals=set(getattr(self, "_agent_tab_arrivals", set()) or set()),
            config_colors=dict(styles.colors) if styles is not None else {},
            config_icons=dict(styles.icons) if styles is not None else {},
            config_descriptions=dict(styles.descriptions) if styles is not None else {},
            enabled_projects=tuple(styles.enabled_projects)
            if styles is not None
            else (),
            machine_mode=machine_mode,
            jump_hints=jump_hints,
            extra_tooltips=extras,
        )

    def _refresh_agent_tab_strip(self) -> None:
        """Project descriptors and push them; skip on no change.

        ``AgentTabStrip`` owners get the full descriptors; a legacy
        ``PanelTabStrip`` owner keeps the minimal labels-only strip so
        phase-6 surfaces stay byte-identical.
        """
        self._ensure_agent_tabs_state()  # type: ignore[attr-defined]
        try:
            strip = self.query_one("#agents-tab-strip")  # type: ignore[attr-defined]
        except Exception:
            return
        from ...models.agent_tab_descriptors import descriptor_signature

        entries = self._agent_tab_catalog_view()
        active_key: AgentTabKey | None = self._active_agent_tab  # type: ignore[attr-defined]
        if _all_tabs_level_active(self):
            # The All-tabs level keeps the strip mounted with every tab lit
            # in its accent and no pill: there is never an "ALL" chip.
            active_key = None
        try:
            descriptors = self._descriptors_for_strip(entries, active_key)
        except Exception:
            log.exception("Tab strip descriptor projection failed")
            return
        signature = descriptor_signature(
            descriptors, active_key, self._agent_tab_strip_visible()
        )
        if signature == self._agent_tab_strip_signature:  # type: ignore[attr-defined]
            return
        set_descriptors = getattr(strip, "set_descriptors", None)
        if callable(set_descriptors):
            try:
                set_descriptors(descriptors, active_key)
            except Exception:
                # A failed push must not poison the gate: leave the old
                # signature so the next refresh retries the push.
                log.exception("Tab strip refresh failed")
                return
            self._agent_tab_strip_signature = signature  # type: ignore[attr-defined]
            return
        set_tabs = getattr(strip, "set_tabs", None)
        if not callable(set_tabs):
            return
        try:
            from ...widgets.panel_tab_strip import PanelTab

            set_tabs(
                [
                    PanelTab(
                        id=_strip_id_for_key(entry.key),
                        label=entry.label,
                        accent_color="",
                    )
                    for entry in entries
                ],
                active_tab=(
                    _strip_id_for_key(active_key) if active_key is not None else None
                ),
            )
        except Exception:
            log.exception("Tab strip refresh failed")
            return
        self._agent_tab_strip_signature = signature  # type: ignore[attr-defined]

    def _active_tab_health_text(self) -> str:
        """Return the right-side health text for the active machine tab."""
        _health, _extras, active_text = agent_tab_health_for_owner(self)
        return active_text

    def _active_tab_empty_state(self) -> AgentTabEmptyState | None:
        """Return the visible empty cause for the active tab, if empty."""
        from ...widgets.agent_tab_strip import (
            AgentTabEmptyState,
            agent_tab_empty_state,
        )

        scoped = list(getattr(self, "_agents", ()) or [])
        if scoped:
            return None
        if not self._agent_tab_strip_visible():
            if getattr(self, "_agent_tab_latched_key", None) is None:
                return None
        index = getattr(self, "_agent_tab_index", None)
        active = getattr(self, "_active_agent_tab", None)
        try:
            tab_has_roots = bool(index is not None and index.root_count(active) > 0)
        except Exception:
            tab_has_roots = False
        query = str(getattr(self, "_agent_search_query", "") or "")
        query_result = list(getattr(self, "_agents_query_result", None) or [])
        matches_elsewhere = _top_level_count(query_result)
        health, _extras, _active_text = agent_tab_health_for_owner(self)
        try:
            feed_unavailable = isinstance(active, AgentTabKey) and health.get(
                active, "ok"
            ) in ("invalid", "offline")
        except Exception:
            feed_unavailable = False
        return agent_tab_empty_state(
            scoped_count=0,
            tab_has_roots=tab_has_roots,
            query=query,
            matches_elsewhere=matches_elsewhere,
            feed_unavailable=bool(feed_unavailable),
            tab_label=active_tab_label_for_owner(self),
        )

    def _show_active_tab_empty_state(self, agent_detail: Any) -> bool:
        """Render the active tab's empty cause into the detail panel.

        Returns True when a cause was rendered and callers should skip
        the default empty state. Falls back to False (default empty) on
        any failure so the detail panel never goes blank.
        """
        state = self._active_tab_empty_state()
        if state is None:
            return False
        show_cause = getattr(agent_detail, "show_tab_empty_state", None)
        if not callable(show_cause):
            return False
        try:
            show_cause(state.title, state.detail)
        except Exception:
            return False
        return True


__all__ = [
    "AgentTabsSwitchStripMixin",
]
