"""Synchronous tab switching with per-tab memory and the minimal strip.

With the ``agent_tabs`` flag off every entry point is a no-op: the scope
stays the default key, no strip appears, and ``[``/``]`` do nothing on the
Agents tab. With the flag on, ``_switch_agents_tab`` synchronously re-scopes
the cached query result with per-tab selection memory, and the strip
refreshes on every switch.
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

from ...agent_tabs_flag import agent_tabs_enabled
from ...models.agent_tab_index import AgentTabCatalogEntry
from ._agent_tabs_catalog import (
    bulk_scope_label_for_owner,
    catalog_view_for_owner,
    strip_visible_for_owner,
)

if TYPE_CHECKING:
    from textual.worker import Worker

    from ...models import Agent
    from ...models.agent import AgentType
    from ...models.agent_tab_index import AgentTabIndex

log = logging.getLogger(__name__)

_TAB_SWITCH_PERF_ACTION = "agents_tab_switch"
_NO_SAVED_PANEL_KEY = object()


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
        and schedules persistence. A no-op when the flag is off or *key*
        equals the active key.
        """
        del reason
        self._ensure_agent_tabs_state()
        if not agent_tabs_enabled():
            return False
        if not isinstance(key, AgentTabKey):
            return False
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
        if not agent_tabs_enabled():
            return
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
            self.push_screen(  # type: ignore[attr-defined]
                AgentTabPickerModal(entries, active), _on_choice
            )
        except Exception:
            log.exception("Tab picker failed to open")

    def _on_agents_tab_strip_clicked(self, tab_id: str) -> None:
        """Switch to the clicked strip tab, ignoring unknown ids."""
        self._ensure_agent_tabs_state()
        if not agent_tabs_enabled():
            return
        key = _key_for_strip_id(tab_id, self._agent_tab_catalog_view())
        if key is None:
            return
        try:
            self._switch_agents_tab(key, reason="strip")
        except Exception:
            log.exception("Tab strip switch failed")

    def _refresh_agent_tab_strip(self) -> None:
        """Push catalog labels and the active key; skip on no change."""
        self._ensure_agent_tabs_state()
        try:
            strip = self.query_one("#agents-tab-strip")  # type: ignore[attr-defined]
        except Exception:
            return
        entries = self._agent_tab_catalog_view()
        active = self._active_agent_tab  # type: ignore[attr-defined]
        signature = (
            tuple((entry.key, entry.label, entry.root_count) for entry in entries),
            active,
            self._agent_tab_strip_visible(),
        )
        if signature == self._agent_tab_strip_signature:  # type: ignore[attr-defined]
            return
        self._agent_tab_strip_signature = signature  # type: ignore[attr-defined]
        try:
            from ...widgets.panel_tab_strip import PanelTab

            strip.set_tabs(
                [
                    PanelTab(
                        id=_strip_id_for_key(entry.key),
                        label=entry.label,
                        accent_color="",
                    )
                    for entry in entries
                ],
                active_tab=_strip_id_for_key(active),
            )
        except Exception:
            log.exception("Tab strip refresh failed")


__all__ = [
    "AgentTabsSwitchMixin",
]
