"""Tab reconcile, startup selection, machine fallback, and persistence.

``_reconcile_active_agent_tab`` maintains the startup selection, the
emptied-tab latch, and the machine-disappearance fallback after every
index rebuild, and the active key persists off-thread.
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

_FLUSH_TIMEOUT_SECONDS = 2.0


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


class AgentTabsLifecycleMixin:
    """Tab reconcile, startup selection, fallback, and persistence."""

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

    def _reconcile_active_agent_tab(self) -> bool:
        """Maintain the active key after an index rebuild.

        Applies the startup selection on the first catalog, keeps the
        emptied-tab latch, and falls back to the default tab when the
        active machine key disappears. Returns True when the active scope
        changed and the caller must re-scope.
        """
        self._ensure_agent_tabs_state()
        index = getattr(self, "_agent_tab_index", None)
        if index is None:
            return False
        entries = tuple(getattr(index, "catalog", ()) or ())
        keys = tuple(entry.key for entry in entries)
        for entry in entries:
            if isinstance(entry.label, str) and entry.label:
                self._agent_tab_known_labels[entry.key] = entry.label  # type: ignore[attr-defined]
        try:
            self._track_tab_arrivals()  # type: ignore[attr-defined]
        except Exception:
            log.exception("Agent tab arrival tracking failed")
        prev_keys = tuple(getattr(self, "_agent_tab_prev_catalog_keys", ()) or ())
        active = self._active_agent_tab  # type: ignore[attr-defined]
        changed = False

        if not getattr(self, "_agent_tabs_reconciled_once", False):
            # The initial loader can publish an empty catalog before the
            # first real roster arrives. Keep startup selection pending until
            # there is something to select, and never override an early user
            # switch.
            if keys:
                self._agent_tabs_reconciled_once = True  # type: ignore[attr-defined]
                if not getattr(self, "_agent_tabs_user_switched", False):
                    chosen = self._startup_tab_selection(keys)
                    if chosen is not None and chosen != active:
                        self._active_agent_tab = chosen  # type: ignore[attr-defined]
                        active = chosen
                        changed = True
        else:
            latched = getattr(self, "_agent_tab_latched_key", None)
            if isinstance(latched, AgentTabKey) and latched in keys:
                self._agent_tab_latched_key = None  # type: ignore[attr-defined]
            elif active not in keys:
                fallback = self._machine_fallback(active)
                if fallback is not None:
                    self._active_agent_tab = fallback  # type: ignore[attr-defined]
                    self._agent_tab_latched_key = None  # type: ignore[attr-defined]
                    active = fallback
                    changed = True
                    self._agent_tab_state_changed()
                elif active in prev_keys or (
                    isinstance(active, AgentTabKey) and active.kind == "machine"
                ):
                    self._agent_tab_latched_key = active  # type: ignore[attr-defined]
        self._agent_tab_prev_catalog_keys = keys  # type: ignore[attr-defined]
        if changed:
            self._refresh_agent_tab_strip()  # type: ignore[attr-defined]
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
        """Return the key of the newest root needing attention."""
        index = getattr(self, "_agent_tab_index", None)
        if index is None:
            return None
        from ...models._agent_tree_anchor import presentation_anchor_lookup

        roster = list(getattr(self, "_agents_with_children", ()) or ())
        anchors = presentation_anchor_lookup(roster)
        wanted = set(keys)
        seen_roots: set[int] = set()
        newest_key: AgentTabKey | None = None
        newest_at = float("-inf")
        for row in roster:
            root = anchors.get(id(row), row)
            if root is not row or id(root) in seen_roots:
                continue
            seen_roots.add(id(root))
            try:
                key = index.key_for(root)
            except Exception:
                continue
            if key not in wanted:
                continue
            try:
                status = root.status
            except Exception:
                continue
            if not _attention_status(status):
                continue
            try:
                started_at = (
                    root.start_time.timestamp() if root.start_time else float("-inf")
                )
            except Exception:
                started_at = float("-inf")
            if newest_key is None or started_at > newest_at:
                newest_key = key
                newest_at = started_at
        return newest_key

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
        machine_alias = next(
            (
                alias
                for installation_id, alias in (view.machine_order or ())
                if installation_id == active.value
            ),
            None,
        )
        order_ids = {pinned for pinned, _alias in (view.machine_order or ())}
        if view.machine_mode and active.value in order_ids:
            return None
        label = self._agent_tab_known_labels.get(active)  # type: ignore[attr-defined]
        if not label and machine_alias:
            label = (
                "\u2328 local\u00b7remote"
                if machine_alias.casefold() == "local"
                else f"\u2328 {machine_alias}"
            )
        if not label:
            label = "\u2328 machine"
        default_label = next(
            (
                entry.label
                for entry in getattr(
                    getattr(self, "_agent_tab_index", None), "catalog", ()
                )
                if entry.key == DEFAULT_AGENT_TAB_KEY
            ),
            "\u2328 local" if view.machine_mode else "main",
        )
        notify = getattr(self, "notify", None)
        if callable(notify):
            try:
                notify(f"agent tab {label} is gone; showing {default_label}")
            except Exception:
                pass
        return DEFAULT_AGENT_TAB_KEY

    def _agent_tab_state_changed(self) -> None:
        """Schedule a coalesced off-thread persist of the active key."""
        self._ensure_agent_tabs_state()
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
        if key is not None and not getattr(self, "_agent_tabs_user_switched", False):
            index = getattr(self, "_agent_tab_index", None)
            try:
                known = list(getattr(index, "catalog", ())) if index is not None else []
            except Exception:
                known = []
            if any(entry.key == key for entry in known):
                try:
                    self._switch_agents_tab(key, reason="persisted")  # type: ignore[attr-defined]
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
    "AgentTabsLifecycleMixin",
]
