"""Synchronous tab switching with per-tab memory and the minimal strip.

``_switch_agents_tab`` synchronously re-scopes the cached query result
with per-tab selection memory, and the strip refreshes on every switch.
"""

from __future__ import annotations

import asyncio
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
    from textual.worker import Worker

    from ...models import Agent
    from ...models.agent import AgentType
    from ...models.agent_tab_descriptors import AgentTabStyleInputs
    from ...models.agent_tab_index import AgentTabIndex
    from ...widgets.agent_tab_strip import AgentTabEmptyState

log = logging.getLogger(__name__)

_TAB_SWITCH_PERF_ACTION = "agents_tab_switch"
_NO_SAVED_PANEL_KEY = object()


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


def _selected_identity_for_owner(owner: Any) -> Any | None:
    """Return the currently selected agent identity, if any."""
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
    return getattr(owner, "_agents_last_identity", None)


def _selected_row_index_for_owner(owner: Any) -> int:
    """Return the active tab's selected row index, defaulting to its first row."""
    try:
        agents = getattr(owner, "_agents", ()) or ()
        if getattr(owner, "current_tab", None) == "agents":
            idx = int(getattr(owner, "current_idx", 0))
        else:
            idx = int(getattr(owner, "_agents_last_idx", 0))
        return max(0, idx) if agents else 0
    except Exception:
        return 0


def _focused_panel_key_for_owner(owner: Any) -> Any:
    """Return the focused whole-panel key, if any."""
    for resolver_name in ("_resolve_focused_panel", "_resolve_focused_collapsed_panel"):
        resolver = getattr(owner, resolver_name, None)
        if not callable(resolver):
            continue
        try:
            focus = resolver()
        except Exception:
            continue
        if focus is not None:
            return getattr(focus, "panel_key", _NO_SAVED_PANEL_KEY)
    return _NO_SAVED_PANEL_KEY


def _scroll_anchor_for_owner(owner: Any) -> Any | None:
    """Return the Agents list scroll offset, if queryable."""
    try:
        node = owner.query_one("#agent-list-panel")  # type: ignore[attr-defined]
        return node.scroll_y
    except Exception:
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


class AgentTabsSwitchMixin:
    """Synchronous tab switching with per-tab memory and the strip."""

    _active_agent_tab: AgentTabKey
    _agent_tab_index: AgentTabIndex | None
    _agent_tab_memory: dict[AgentTabKey, tuple[Any | None, int, Any, Any | None]]
    _agent_tab_latched_key: AgentTabKey | None
    _agent_tab_known_labels: dict[AgentTabKey, str]
    _agent_tab_prev_catalog_keys: tuple[AgentTabKey, ...]
    _agent_tabs_reconciled_once: bool
    _agent_tabs_user_switched: bool
    _agent_tab_load_started: bool
    _agent_tab_load_resolved: bool
    _agent_tab_loaded_key: AgentTabKey | None
    _agent_tab_load_worker: Worker[Any] | None
    _agent_tab_save_pending: AgentTabKey | None
    _agent_tab_save_task: asyncio.Task[None] | None
    _agent_tab_save_generation: int
    _agent_tab_save_completed_generation: int
    _agent_tab_strip_signature: Any | None
    _agent_tab_arrivals: set[AgentTabKey]
    _agent_tab_seen_identities: set[Any]
    _agent_tab_arrivals_baselined: bool
    _agent_tab_jump_hints: dict[AgentTabKey, str]

    def _ensure_agent_tabs_state(self) -> None:
        """Initialize tab-switch fields for mixin tests that skip startup."""
        defaults: tuple[tuple[str, object], ...] = (
            ("_active_agent_tab", DEFAULT_AGENT_TAB_KEY),
            ("_agent_tab_index", None),
            ("_agent_tab_memory", {}),
            ("_agent_tab_latched_key", None),
            ("_agent_tab_known_labels", {}),
            ("_agent_tab_prev_catalog_keys", ()),
            ("_agent_tabs_reconciled_once", False),
            ("_agent_tabs_user_switched", False),
            ("_agent_tab_load_started", False),
            ("_agent_tab_load_resolved", False),
            ("_agent_tab_loaded_key", None),
            ("_agent_tab_load_worker", None),
            ("_agent_tab_save_pending", None),
            ("_agent_tab_save_task", None),
            ("_agent_tab_save_generation", 0),
            ("_agent_tab_save_completed_generation", 0),
            ("_agent_tab_strip_signature", None),
            ("_agent_tab_arrivals", set()),
            ("_agent_tab_seen_identities", set()),
            ("_agent_tab_arrivals_baselined", False),
            ("_agent_tab_jump_hints", {}),
        )
        for name, value in defaults:
            if not hasattr(self, name):
                setattr(self, name, value)
        active = getattr(self, "_active_agent_tab", None)
        if not isinstance(active, AgentTabKey):
            self._active_agent_tab = DEFAULT_AGENT_TAB_KEY  # type: ignore[attr-defined]

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

    def _remember_active_tab_memory(self) -> None:
        """Save the active tab's selection, panel, and scroll memory."""
        self._ensure_agent_tabs_state()
        active = self._active_agent_tab  # type: ignore[attr-defined]
        self._agent_tab_memory[active] = (  # type: ignore[attr-defined]
            _selected_identity_for_owner(self),
            _selected_row_index_for_owner(self),
            _focused_panel_key_for_owner(self),
            _scroll_anchor_for_owner(self),
        )

    def _restore_tab_memory(self, key: AgentTabKey) -> None:
        """Restore *key*'s remembered selection with nearest-row fallback."""
        self._ensure_agent_tabs_state()
        memory = self._agent_tab_memory.get(key)  # type: ignore[attr-defined]
        if memory is None:
            identity, remembered_idx, panel_key, scroll_anchor = (
                None,
                0,
                _NO_SAVED_PANEL_KEY,
                None,
            )
        else:
            identity, remembered_idx, panel_key, scroll_anchor = memory
        agents = list(getattr(self, "_agents", ()) or [])
        prior_row: int | None = None
        if identity is not None:
            for pos, row in enumerate(agents):
                try:
                    if row.identity == identity:
                        prior_row = pos
                        break
                except Exception:
                    continue
        if prior_row is None and agents:
            try:
                from ...util.selection import restore_selection_by_identity

                prior_row = restore_selection_by_identity(
                    agents,
                    prior_identity=identity,
                    prior_visual_row=int(remembered_idx or 0),
                    identity_fn=lambda row: row.identity,
                )
            except Exception:
                prior_row = 0
            if prior_row is None or not 0 <= prior_row < len(agents):
                prior_row = 0
        new_idx = prior_row if prior_row is not None else 0
        if not agents:
            new_idx = 0
        if getattr(self, "current_tab", None) == "agents":
            try:
                self.current_idx = new_idx  # type: ignore[attr-defined]
            except Exception:
                pass
        self._agents_last_idx = new_idx  # type: ignore[attr-defined]
        if agents and 0 <= new_idx < len(agents):
            try:
                self._agents_last_identity = agents[new_idx].identity  # type: ignore[attr-defined]
            except Exception:
                self._agents_last_identity = identity  # type: ignore[attr-defined]
        else:
            self._agents_last_identity = None  # type: ignore[attr-defined]
        restored_saved_panel = False
        if panel_key is None or isinstance(panel_key, str):
            panel_group = getattr(self, "_panel_group", None)
            if panel_group is not None:
                panel_keys = getattr(panel_group, "panel_keys", ())
                try:
                    from ...models.agent_panels import normalize_panel_key

                    normalized_panel_key = normalize_panel_key(panel_key)
                    if normalized_panel_key in panel_keys:
                        panel_group.focused_idx = panel_keys.index(normalized_panel_key)
                        from ._panel_fold_intent import panel_is_collapsed

                        if not panel_is_collapsed(self, normalized_panel_key):
                            self._expanded_panel_focus = True  # type: ignore[attr-defined]
                        focus_panel = getattr(self, "_focus_focused_panel_widget", None)
                        if callable(focus_panel):
                            focus_panel()
                        restored_saved_panel = True
                except Exception:
                    pass
        if not restored_saved_panel:
            # First visit, or the remembered panel is gone: select the
            # panel that holds the restored row and drop expanded-panel
            # focus so a previous tab's panel focus cannot carry over.
            self._expanded_panel_focus = False  # type: ignore[attr-defined]
            panel_group = getattr(self, "_panel_group", None)
            keys_for = getattr(self, "_panel_keys_per_agent", None)
            if (
                panel_group is not None
                and callable(keys_for)
                and agents
                and 0 <= new_idx < len(agents)
            ):
                try:
                    per_agent = keys_for()
                    if 0 <= new_idx < len(per_agent):
                        target_key = per_agent[new_idx]
                        panel_keys = getattr(panel_group, "panel_keys", ())
                        if target_key in panel_keys:
                            panel_group.focused_idx = panel_keys.index(target_key)
                    focus_panel = getattr(self, "_focus_focused_panel_widget", None)
                    if callable(focus_panel):
                        focus_panel()
                except Exception:
                    pass
        if scroll_anchor is not None:
            try:
                node = self.query_one("#agent-list-panel")  # type: ignore[attr-defined]
                node.scroll_y = scroll_anchor
            except Exception:
                pass

    def _switch_agents_tab(self, key: AgentTabKey, *, reason: str = "") -> bool:
        """Synchronously switch to *key*; True when the scope changed.

        Saves the current tab's memory, re-scopes the cached query result
        without I/O, restores the target tab's memory, refreshes the strip,
        and schedules persistence. A no-op when *key* equals the
        active key.
        """
        del reason
        self._ensure_agent_tabs_state()
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
        self._remember_active_tab_memory()
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
        self._restore_tab_memory(key)
        self._refresh_agent_tab_strip()
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

        self._ensure_agent_tabs_state()
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
        self._restore_tab_memory(key)
        self._refresh_agent_tab_strip()
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

    def _cycle_agents_tab(self, step: int) -> None:
        """Cycle the active tab by *step* with wraparound.

        A no-op when the strip is hidden: with fewer than two tabs there is
        nowhere to go, and the latch keeps its own empty selection.
        """
        self._ensure_agent_tabs_state()
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
            self._switch_agents_tab(keys[pos], reason="cycle")
            return
        self._switch_agents_tab(keys[(pos + step) % len(keys)], reason="cycle")

    def action_next_agents_tab(self) -> None:
        """Cycle to the next agent tab (``]``) with wraparound."""
        self._cycle_agents_tab(1)

    def action_prev_agents_tab(self) -> None:
        """Cycle to the previous agent tab (``[``) with wraparound."""
        self._cycle_agents_tab(-1)

    def action_pick_agents_tab(self) -> None:
        """Open the minimal tab picker and switch on select."""
        self._ensure_agent_tabs_state()
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
                self._switch_agents_tab(chosen, reason="pick")
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
        self._ensure_agent_tabs_state()
        key = _key_for_strip_id(tab_id, self._agent_tab_catalog_view())
        if key is None:
            return
        try:
            self._switch_agents_tab(key, reason="strip")
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
        self._ensure_agent_tabs_state()
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

    def _track_tab_arrivals(self) -> None:
        """Mark inactive tabs that gained a new root since the last visit.

        New presentation-root identities on a non-active tab raise its
        arrival dot; visiting a tab clears its dot. The first catalog
        only baselines what exists so startup paints no dots. Pure
        in-memory work over the already-loaded roster.
        """
        self._ensure_agent_tabs_state()
        index = getattr(self, "_agent_tab_index", None)
        if index is None:
            return
        key_for = getattr(index, "key_for", None)
        if not callable(key_for):
            return
        roster = list(getattr(self, "_agents_with_children", ()) or [])
        try:
            from ...models._agent_tree_anchor import presentation_anchor_lookup

            anchors = presentation_anchor_lookup(roster)
        except Exception:
            return
        active = self._active_agent_tab  # type: ignore[attr-defined]
        seen = self._agent_tab_seen_identities  # type: ignore[attr-defined]
        arrivals = self._agent_tab_arrivals  # type: ignore[attr-defined]
        baselined = bool(getattr(self, "_agent_tab_arrivals_baselined", False))
        current_identities: set[Any] = set()
        seen_root_ids: set[int] = set()
        for row in roster:
            try:
                anchor = anchors.get(id(row), row)
            except Exception:
                anchor = row
            if id(anchor) in seen_root_ids:
                continue
            seen_root_ids.add(id(anchor))
            try:
                identity = anchor.identity
            except Exception:
                continue
            current_identities.add(identity)
            if identity in seen:
                continue
            seen.add(identity)
            if not baselined:
                continue
            try:
                key = key_for(anchor)
            except Exception:
                continue
            if key != active:
                arrivals.add(key)
        try:
            seen.intersection_update(current_identities)
        except Exception:
            pass
        self._agent_tab_arrivals_baselined = True  # type: ignore[attr-defined]
        try:
            arrivals.discard(active)
        except Exception:
            pass

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
    "AgentTabsSwitchMixin",
]
