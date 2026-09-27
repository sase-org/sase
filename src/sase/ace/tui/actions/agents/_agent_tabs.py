"""Tab switching, persistence, keys, minimal strip, and perf (tab-state-keys).

With the ``agent_tabs`` flag off every entry point is a no-op: the scope
stays the default key, no strip appears, and ``[``/``]`` do nothing on the
Agents tab. With the flag on, :meth:`AgentTabsMixin._switch_agents_tab`
synchronously re-scopes the cached query result with per-tab selection
memory, :meth:`AgentTabsMixin._reconcile_active_agent_tab` maintains the
startup selection, the emptied-tab latch, and the machine-disappearance
fallback after every index rebuild, and the active key persists off-thread.
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
from ...models.agent_tab_persistence import (
    load_active_agent_tab,
    save_active_agent_tab,
)

if TYPE_CHECKING:
    from textual.worker import Worker

    from ...models import Agent
    from ...models.agent import AgentType
    from ...models.agent_tab_index import AgentTabIndex

log = logging.getLogger(__name__)

_TAB_SWITCH_PERF_ACTION = "agents_tab_switch"
_FLUSH_TIMEOUT_SECONDS = 2.0


def catalog_view_for_owner(owner: Any) -> tuple[AgentTabCatalogEntry, ...]:
    """Return the strip's catalog view: index entries plus a latched key.

    The latch keeps an emptied active tab selected with an empty roster, so
    the strip shows the latched key with count 0 until the user navigates
    away or roots return.
    """
    index = getattr(owner, "_agent_tab_index", None)
    entries = tuple(getattr(index, "catalog", ()) or ())
    latched = getattr(owner, "_agent_tab_latched_key", None)
    if (
        isinstance(latched, AgentTabKey)
        and latched.kind != "unresolved_machine"
        and not any(entry.key == latched for entry in entries)
    ):
        label = getattr(owner, "_agent_tab_known_labels", {}).get(latched)
        if not isinstance(label, str) or not label:
            label = _fallback_label(latched)
        entries = (*entries, AgentTabCatalogEntry(latched, latched.kind, label, 0))
    return entries


def _fallback_label(key: AgentTabKey) -> str:
    """Return a last-resort strip label for *key*."""
    if key.kind == "named":
        return key.value or "tab"
    if key.kind == "machine":
        return f"\u2328 {key.value}"
    return "main"


def strip_visible_for_owner(owner: Any) -> bool:
    """Return True when the minimal tab strip should render.

    Visible iff the flag is on and the catalog view holds two or more tabs,
    or while the emptied-tab latch holds.
    """
    if not agent_tabs_enabled():
        return False
    if getattr(owner, "_agent_tab_latched_key", None) is not None:
        return True
    return len(catalog_view_for_owner(owner)) >= 2


def _active_tab_label_for_owner(owner: Any) -> str:
    """Return the active tab's strip label, falling back to a default."""
    active = getattr(owner, "_active_agent_tab", None)
    for entry in catalog_view_for_owner(owner):
        if entry.key == active and isinstance(entry.label, str) and entry.label:
            return entry.label
    known = getattr(owner, "_agent_tab_known_labels", None)
    if isinstance(known, dict):
        label = known.get(active)
        if isinstance(label, str) and label:
            return label
    if isinstance(active, AgentTabKey):
        return _fallback_label(active)
    return "main"


def bulk_scope_label_for_owner(owner: Any) -> str | None:
    """Return the bulk-confirmation scope wording, or None for today's text.

    Returns ``on <tab label>`` (for example ``on sase``) when the flag is on
    and the strip is visible, ``across all tabs`` at the ``ALL_AGENT_TABS``
    scope, and None otherwise. None keeps every confirmation byte-identical.
    """
    if not agent_tabs_enabled():
        return None
    from ...models.agent_tab_index import ALL_AGENT_TABS

    if getattr(owner, "_active_agent_tab", None) is ALL_AGENT_TABS:
        return "across all tabs"
    if not strip_visible_for_owner(owner):
        return None
    return f"on {_active_tab_label_for_owner(owner)}"


def marked_off_tab_count_for_owner(owner: Any, agents: list[Any]) -> int:
    """Return how many of *agents* sit off the owner's active tab.

    Returns 0 with the flag off (or without an index), so flag-off
    confirmations stay byte-identical.
    """
    if not agent_tabs_enabled():
        return 0
    index = getattr(owner, "_agent_tab_index", None)
    active = getattr(owner, "_active_agent_tab", None)
    key_for = getattr(index, "key_for", None)
    if index is None or active is None or not callable(key_for):
        return 0
    count = 0
    for agent in agents:
        try:
            if key_for(agent) != active:
                count += 1
        except Exception:
            continue
    return count


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


def _focused_panel_key_for_owner(owner: Any) -> str | None:
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
            key = getattr(focus, "panel_key", None)
            return key if isinstance(key, str) else None
    return None


def _scroll_anchor_for_owner(owner: Any) -> Any | None:
    """Return the Agents list scroll offset, if queryable."""
    try:
        node = owner.query_one("#agent-list-panel")  # type: ignore[attr-defined]
        return node.scroll_y
    except Exception:
        return None


def _attention_status(status: object) -> bool:
    """Return True when *status* marks a root needing attention."""
    if not isinstance(status, str):
        return False
    try:
        from ...models.agent_status import (
            is_stopped_agent_status,
            is_unread_completed_status,
        )

        return bool(
            is_stopped_agent_status(status)
            or status == "FAILED"
            or is_unread_completed_status(status)
        )
    except Exception:
        return status in ("STOPPED", "FAILED")


class AgentTabsMixin:
    """Synchronous tab switching with per-tab memory and persistence."""

    _active_agent_tab: AgentTabKey
    _agent_tab_index: AgentTabIndex | None
    _agent_tab_memory: dict[AgentTabKey, tuple[Any | None, str | None, Any | None]]
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
            _focused_panel_key_for_owner(self),
            _scroll_anchor_for_owner(self),
        )

    def _restore_tab_memory(self, key: AgentTabKey) -> None:
        """Restore *key*'s remembered selection with nearest-row fallback."""
        self._ensure_agent_tabs_state()
        memory = self._agent_tab_memory.get(key, (None, None, None))  # type: ignore[attr-defined]
        identity, _panel_key, scroll_anchor = memory
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

                prior_visual = getattr(self, "_agents_last_idx", 0)
                prior_row = restore_selection_by_identity(
                    agents,
                    prior_identity=identity,
                    prior_visual_row=int(prior_visual or 0),
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
        self._agent_tab_state_changed()
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

    def _reconcile_active_agent_tab(self) -> bool:
        """Maintain the active key after an index rebuild.

        Applies the startup selection on the first catalog, keeps the
        emptied-tab latch, and falls back to the default tab when the
        active machine key disappears. Returns True when the active scope
        changed and the caller must re-scope.
        """
        self._ensure_agent_tabs_state()
        if not agent_tabs_enabled():
            return False
        index = getattr(self, "_agent_tab_index", None)
        if index is None:
            return False
        entries = tuple(getattr(index, "catalog", ()) or ())
        keys = tuple(entry.key for entry in entries)
        for entry in entries:
            if isinstance(entry.label, str) and entry.label:
                self._agent_tab_known_labels[entry.key] = entry.label  # type: ignore[attr-defined]
        prev_keys = tuple(getattr(self, "_agent_tab_prev_catalog_keys", ()) or ())
        active = self._active_agent_tab  # type: ignore[attr-defined]
        changed = False

        if not getattr(self, "_agent_tabs_reconciled_once", False):
            self._agent_tabs_reconciled_once = True  # type: ignore[attr-defined]
            chosen = self._startup_tab_selection(keys)
            if chosen is not None and chosen != active:
                self._active_agent_tab = chosen  # type: ignore[attr-defined]
                active = chosen
                changed = True
        else:
            latched = getattr(self, "_agent_tab_latched_key", None)
            if isinstance(latched, AgentTabKey) and latched in keys:
                self._agent_tab_latched_key = None  # type: ignore[attr-defined]
            if active not in keys and active in prev_keys and active.kind != "machine":
                self._agent_tab_latched_key = active  # type: ignore[attr-defined]
            elif active not in keys:
                fallback = self._machine_fallback(active)
                if fallback is not None:
                    self._active_agent_tab = fallback  # type: ignore[attr-defined]
                    self._agent_tab_latched_key = None  # type: ignore[attr-defined]
                    active = fallback
                    changed = True
                    self._agent_tab_state_changed()
        self._agent_tab_prev_catalog_keys = keys  # type: ignore[attr-defined]
        if changed:
            self._refresh_agent_tab_strip()
        return changed

    def _startup_tab_selection(
        self, keys: tuple[AgentTabKey, ...]
    ) -> AgentTabKey | None:
        """Return the startup tab: persisted, default, attention, first."""
        if not keys:
            return None
        persisted = getattr(self, "_agent_tab_loaded_key", None)
        if isinstance(persisted, AgentTabKey) and persisted in keys:
            return persisted
        if DEFAULT_AGENT_TAB_KEY in keys:
            index = getattr(self, "_agent_tab_index", None)
            try:
                if index is None or index.root_count(DEFAULT_AGENT_TAB_KEY) > 0:
                    return DEFAULT_AGENT_TAB_KEY
            except Exception:
                return DEFAULT_AGENT_TAB_KEY
        attention = self._attention_tab(keys)
        if attention is not None:
            return attention
        return keys[0]

    def _attention_tab(self, keys: tuple[AgentTabKey, ...]) -> AgentTabKey | None:
        """Return the first catalog key holding a root needing attention."""
        index = getattr(self, "_agent_tab_index", None)
        if index is None:
            return None
        roster = list(getattr(self, "_agents_with_children", ()) or ())
        wanted = set(keys)
        for row in roster:
            try:
                key = index.key_for(row)
            except Exception:
                continue
            if key not in wanted:
                continue
            try:
                status = row.status
            except Exception:
                continue
            if _attention_status(status):
                return key
        return None

    def _machine_fallback(self, active: AgentTabKey) -> AgentTabKey | None:
        """Return the default key when a machine tab disappeared, else None.

        A machine key is gone when machine mode is off or its installation
        id left the machine order; the switch toasts which tab vanished.
        """
        if not isinstance(active, AgentTabKey) or active.kind != "machine":
            return None
        try:
            from ...agent_tabs_settings import agent_tabs_view_config

            view = agent_tabs_view_config()
        except Exception:
            return None
        order_ids = {pinned for pinned, _alias in (view.machine_order or ())}
        if view.machine_mode and active.value in order_ids:
            return None
        label = self._agent_tab_known_labels.get(active, active.value)  # type: ignore[attr-defined]
        notify = getattr(self, "notify", None)
        if callable(notify):
            try:
                notify(f"agent tab \u2328 {label} is gone; showing main")
            except Exception:
                pass
        return DEFAULT_AGENT_TAB_KEY

    def _agent_tab_state_changed(self) -> None:
        """Schedule a coalesced off-thread persist of the active key."""
        self._ensure_agent_tabs_state()
        if not agent_tabs_enabled():
            return
        active = self._active_agent_tab  # type: ignore[attr-defined]
        if agent_tab_key_token(active) is None:
            return
        self._agent_tab_save_pending = active  # type: ignore[attr-defined]
        self._agent_tab_save_generation += 1  # type: ignore[attr-defined]
        self._start_agent_tab_save_writer()

    def _save_agent_tab_state_now(self, key: AgentTabKey) -> None:
        save_active_agent_tab(key)

    def _start_agent_tab_save_writer(self) -> None:
        """Start the single writer for a pending generation when possible."""
        task: asyncio.Task[None] | None = self._agent_tab_save_task  # type: ignore[attr-defined]
        if task is not None and not task.done():
            return
        if self._agent_tab_save_pending is None:  # type: ignore[attr-defined]
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._agent_tab_save_task = loop.create_task(  # type: ignore[attr-defined]
            self._run_agent_tab_save_loop()
        )

    async def _run_agent_tab_save_loop(self) -> None:
        """Persist the newest pending key; the switch path never blocks."""
        try:
            while True:
                pending = self._agent_tab_save_pending  # type: ignore[attr-defined]
                self._agent_tab_save_pending = None  # type: ignore[attr-defined]
                if pending is None:
                    break
                try:
                    await asyncio.to_thread(self._save_agent_tab_state_now, pending)
                except Exception:
                    log.exception("Active agent tab save failed")
        finally:
            self._agent_tab_save_task = None  # type: ignore[attr-defined]
            if self._agent_tab_save_pending is not None:  # type: ignore[attr-defined]
                self._start_agent_tab_save_writer()

    def _schedule_agent_tab_state_load(self) -> None:
        """Launch the post-first-paint persisted-key load."""
        self._ensure_agent_tabs_state()
        if (
            self._agent_tab_load_started  # type: ignore[attr-defined]
            or self._agent_tab_load_resolved  # type: ignore[attr-defined]
        ):
            return
        self._agent_tab_load_started = True  # type: ignore[attr-defined]
        try:
            worker = self.run_worker(  # type: ignore[attr-defined]
                self._run_agent_tab_state_load,
                thread=False,
                exclusive=False,
                group="startup-tab-state",
            )
            self._agent_tab_load_worker = worker  # type: ignore[attr-defined]
        except Exception:
            log.exception("Failed to schedule agent tab state load")
            self._resolve_agent_tab_state_load(None)

    async def _run_agent_tab_state_load(self) -> None:
        """Read/decode the persisted key entirely off the event loop."""
        try:
            key = await asyncio.to_thread(load_active_agent_tab)
        except Exception:
            log.exception("Active agent tab load failed")
            key = None
        self._resolve_agent_tab_state_load(key)

    def _resolve_agent_tab_state_load(self, key: AgentTabKey | None) -> None:
        """Install the loaded key; apply it when the user has not switched."""
        self._ensure_agent_tabs_state()
        self._agent_tab_loaded_key = key  # type: ignore[attr-defined]
        self._agent_tab_load_resolved = True  # type: ignore[attr-defined]
        if (
            key is not None
            and agent_tabs_enabled()
            and not getattr(self, "_agent_tabs_user_switched", False)
        ):
            index = getattr(self, "_agent_tab_index", None)
            try:
                known = list(getattr(index, "catalog", ())) if index is not None else []
            except Exception:
                known = []
            if any(entry.key == key for entry in known):
                try:
                    self._switch_agents_tab(key, reason="persisted")
                except Exception:
                    log.exception("Persisted tab switch failed")

    async def _flush_agent_tab_state(self) -> None:
        """Await the queued latest generation with a bounded timeout."""

        async def _flush() -> None:
            target = self._agent_tab_save_generation  # type: ignore[attr-defined]
            while self._agent_tab_save_completed_generation < target:  # type: ignore[attr-defined]
                task = self._agent_tab_save_task  # type: ignore[attr-defined]
                if task is None:
                    pending = self._agent_tab_save_pending  # type: ignore[attr-defined]
                    if pending is None:
                        break
                    self._start_agent_tab_save_writer()
                    task = self._agent_tab_save_task  # type: ignore[attr-defined]
                    if task is None:
                        try:
                            await asyncio.to_thread(
                                self._save_agent_tab_state_now, pending
                            )
                        except Exception:
                            log.exception("Active agent tab save failed")
                        self._agent_tab_save_pending = None  # type: ignore[attr-defined]
                        self._agent_tab_save_completed_generation = target  # type: ignore[attr-defined]
                        break
                try:
                    await task
                except Exception:
                    pass
                self._agent_tab_save_completed_generation = max(  # type: ignore[attr-defined]
                    self._agent_tab_save_completed_generation,  # type: ignore[attr-defined]
                    target,
                )

        try:
            await asyncio.wait_for(_flush(), timeout=_FLUSH_TIMEOUT_SECONDS)
        except TimeoutError:
            log.warning("Timed out flushing active agent tab during controlled exit")
        except Exception:
            log.exception("Active agent tab flush failed during controlled exit")


__all__ = [
    "AgentTabsMixin",
    "_attention_status",
    "_fallback_label",
    "_key_for_strip_id",
    "_strip_id_for_key",
    "catalog_view_for_owner",
    "strip_visible_for_owner",
]
