"""Non-blocking lifecycle for persisted Agents-tab deck layout state."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from textual.worker import Worker

    from ...models.agent_deck_persistence import AgentsDeckStateSnapshot

log = logging.getLogger(__name__)

_FLUSH_TIMEOUT_SECONDS = 2.0


class AgentDeckPersistenceMixin:
    """Load, apply, coalesce saves, and flush the Agents-tab deck layout."""

    _agents_deck_state_load_started: bool
    _agents_deck_state_load_resolved: bool
    _agents_deck_state_loaded_snapshot: AgentsDeckStateSnapshot | None
    _agents_deck_state_merged: bool
    _agents_deck_state_save_requested: bool
    _agents_deck_state_save_generation: int
    _agents_deck_state_completed_generation: int
    _agents_deck_state_save_pending: tuple[int, AgentsDeckStateSnapshot] | None
    _agents_deck_state_save_task: asyncio.Task[None] | None
    _agents_deck_state_load_worker: Worker[Any] | None
    _agents_deck_state_last_snapshot: AgentsDeckStateSnapshot | None
    _agents_deck_state_pre_merge_snapshot: AgentsDeckStateSnapshot | None

    def _ensure_agents_deck_persistence_state(self) -> None:
        """Initialize fields for direct-mixin tests that bypass app startup."""
        from ...models.agent_deck_persistence import AgentsDeckStateSnapshot

        defaults: tuple[tuple[str, object], ...] = (
            ("_agents_deck_state_load_started", False),
            ("_agents_deck_state_load_resolved", False),
            ("_agents_deck_state_loaded_snapshot", None),
            ("_agents_deck_state_merged", False),
            ("_agents_deck_state_save_requested", False),
            ("_agents_deck_state_save_generation", 0),
            ("_agents_deck_state_completed_generation", 0),
            ("_agents_deck_state_save_pending", None),
            ("_agents_deck_state_save_task", None),
            ("_agents_deck_state_load_worker", None),
            ("_agents_deck_state_last_snapshot", None),
            ("_agents_deck_state_pre_merge_snapshot", None),
        )
        for name, value in defaults:
            if not hasattr(self, name):
                setattr(self, name, value)
        loaded = self._agents_deck_state_loaded_snapshot
        if loaded is not None and not isinstance(loaded, AgentsDeckStateSnapshot):
            self._agents_deck_state_loaded_snapshot = None

    def _decks_persistence_active(self) -> bool:
        """Return whether deck layout persistence applies this session."""
        try:
            if getattr(self, "current_tab", None) != "agents":
                return True
            from ...widgets.decks.flag import agent_decks_active

            return bool(agent_decks_active(self))
        except Exception:
            return True

    def _capture_agents_deck_state(self) -> AgentsDeckStateSnapshot | None:
        """Capture the effective (pre-zoom) deck state, or None when unavailable."""
        try:
            from ...models.agent_deck_persistence import snapshot_from_area_state
            from ...widgets import AgentDetail

            detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
            area = detail.deck_area
        except Exception:
            return None
        try:
            return snapshot_from_area_state(area.state)
        except Exception:
            return None

    def _agents_deck_state_changed(self) -> None:
        """Record the latest deck layout and schedule a coalesced save."""
        self._ensure_agents_deck_persistence_state()
        if not self._decks_persistence_active():
            return
        snapshot = self._capture_agents_deck_state()
        if snapshot is None:
            if not self._agents_deck_state_merged:  # type: ignore[attr-defined]
                self._agents_deck_state_save_requested = True  # type: ignore[attr-defined]
            return
        if snapshot == self._agents_deck_state_last_snapshot:  # type: ignore[attr-defined]
            return
        self._agents_deck_state_last_snapshot = snapshot  # type: ignore[attr-defined]
        if not self._agents_deck_state_merged:  # type: ignore[attr-defined]
            self._agents_deck_state_pre_merge_snapshot = snapshot  # type: ignore[attr-defined]
            self._agents_deck_state_save_requested = True  # type: ignore[attr-defined]
            return
        self._enqueue_agents_deck_save(snapshot)

    def _enqueue_agents_deck_save(self, snapshot: AgentsDeckStateSnapshot) -> None:
        """Queue ``snapshot`` as the newest coalesced save generation."""
        generation = self._agents_deck_state_save_generation + 1  # type: ignore[attr-defined]
        self._agents_deck_state_save_generation = generation  # type: ignore[attr-defined]
        self._agents_deck_state_save_pending = (generation, snapshot)  # type: ignore[attr-defined]
        self._start_agents_deck_state_save_writer()

    def _apply_agents_deck_snapshot(self, snapshot: AgentsDeckStateSnapshot) -> bool:
        """Install ``snapshot`` into the deck area; False when not ready."""
        try:
            from ...models.agent_deck_persistence import area_state_from_snapshot
            from ...widgets import AgentDetail

            detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
            area = detail.deck_area
        except Exception:
            return False
        try:
            state = area_state_from_snapshot(snapshot)
            area.apply_state(state)
            for index, panel_state in enumerate(state.panels):
                try:
                    detail.show_deck(index, panel_state.deck)
                except Exception:
                    pass
                if panel_state.preferred_card is not None:
                    try:
                        detail.set_deck_preferred_card(
                            index, panel_state.preferred_card
                        )
                    except Exception:
                        pass
            try:
                detail._sync_nodes_collapsed_chrome()
            except Exception:
                pass
            try:
                area.focused_panel().refresh_chrome()
            except Exception:
                pass
            return True
        except Exception:
            return False

    def _install_loaded_agents_deck_state(self) -> bool:
        """Apply the disk baseline once; pre-load edits force a re-save."""
        self._ensure_agents_deck_persistence_state()
        if (
            self._agents_deck_state_merged  # type: ignore[attr-defined]
            or not self._agents_deck_state_load_resolved  # type: ignore[attr-defined]
        ):
            return False
        from ...models.agent_deck_persistence import EMPTY_AGENTS_DECK_STATE

        if not self._decks_persistence_active():
            self._agents_deck_state_merged = True  # type: ignore[attr-defined]
            self._agents_deck_state_loaded_snapshot = None  # type: ignore[attr-defined]
            return True
        snapshot = (
            self._agents_deck_state_loaded_snapshot  # type: ignore[attr-defined]
            or EMPTY_AGENTS_DECK_STATE
        )
        if not self._apply_agents_deck_snapshot(snapshot):
            return False
        self._agents_deck_state_loaded_snapshot = None  # type: ignore[attr-defined]
        self._agents_deck_state_merged = True  # type: ignore[attr-defined]
        self._agents_deck_state_last_snapshot = snapshot  # type: ignore[attr-defined]
        pre_merge = self._agents_deck_state_pre_merge_snapshot  # type: ignore[attr-defined]
        self._agents_deck_state_pre_merge_snapshot = None  # type: ignore[attr-defined]
        if pre_merge is not None and pre_merge != snapshot:
            self._apply_agents_deck_snapshot(pre_merge)
            self._agents_deck_state_last_snapshot = pre_merge  # type: ignore[attr-defined]
        if self._agents_deck_state_save_requested:  # type: ignore[attr-defined]
            self._agents_deck_state_save_requested = False  # type: ignore[attr-defined]
            current = self._agents_deck_state_last_snapshot  # type: ignore[attr-defined]
            if current is not None and current != snapshot:
                self._enqueue_agents_deck_save(current)
            else:
                self._agents_deck_state_changed()
        return True

    def _maybe_install_agents_deck_state(self) -> bool:
        """Install hook for callers that run after the deck area is composed."""
        return self._install_loaded_agents_deck_state()

    def _resolve_agents_deck_state_load(
        self, snapshot: AgentsDeckStateSnapshot
    ) -> None:
        self._ensure_agents_deck_persistence_state()
        self._agents_deck_state_loaded_snapshot = snapshot  # type: ignore[attr-defined]
        self._agents_deck_state_load_resolved = True  # type: ignore[attr-defined]
        self._install_loaded_agents_deck_state()

    async def _run_agents_deck_state_load(self) -> None:
        """Read/decode the one-shot baseline entirely off the event loop."""
        from ...models.agent_deck_persistence import (
            EMPTY_AGENTS_DECK_STATE,
            load_agents_deck_state,
        )

        try:
            snapshot = await asyncio.to_thread(load_agents_deck_state)
        except Exception:
            log.exception("Agents deck state load failed")
            snapshot = EMPTY_AGENTS_DECK_STATE
        self._resolve_agents_deck_state_load(snapshot)

    def _schedule_agents_deck_state_load(self) -> None:
        """Launch the post-first-paint load without gating other startup work."""
        self._ensure_agents_deck_persistence_state()
        if (
            self._agents_deck_state_load_started  # type: ignore[attr-defined]
            or self._agents_deck_state_load_resolved  # type: ignore[attr-defined]
        ):
            return
        self._agents_deck_state_load_started = True  # type: ignore[attr-defined]
        try:
            worker = self.run_worker(  # type: ignore[attr-defined]
                cast(Any, self._run_agents_deck_state_load),
                thread=False,
                exclusive=False,
                group="startup-deck-state",
            )
            self._agents_deck_state_load_worker = worker  # type: ignore[attr-defined]
        except Exception:
            log.exception("Failed to schedule Agents deck state load")
            from ...models.agent_deck_persistence import EMPTY_AGENTS_DECK_STATE

            self._resolve_agents_deck_state_load(EMPTY_AGENTS_DECK_STATE)

    def _save_agents_deck_state_now(self, snapshot: AgentsDeckStateSnapshot) -> None:
        from ...models.agent_deck_persistence import save_agents_deck_state

        save_agents_deck_state(snapshot)

    def _start_agents_deck_state_save_writer(self) -> None:
        """Start the writer for an existing pending generation when possible."""
        task: asyncio.Task[None] | None = self._agents_deck_state_save_task  # type: ignore[attr-defined]
        if task is not None and not task.done():
            return
        if self._agents_deck_state_save_pending is None:  # type: ignore[attr-defined]
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._agents_deck_state_save_task = loop.create_task(  # type: ignore[attr-defined]
            self._run_agents_deck_state_save_loop()
        )

    async def _run_agents_deck_state_save_loop(self) -> None:
        """Run one writer at a time until the newest generation is durable."""
        try:
            while True:
                pending = self._agents_deck_state_save_pending  # type: ignore[attr-defined]
                self._agents_deck_state_save_pending = None  # type: ignore[attr-defined]
                if pending is None:
                    break
                generation, snapshot = pending
                try:
                    await asyncio.to_thread(
                        self._save_agents_deck_state_now,
                        snapshot,
                    )
                except Exception:
                    log.exception("Agents deck state save failed")
                finally:
                    self._agents_deck_state_completed_generation = max(  # type: ignore[attr-defined]
                        self._agents_deck_state_completed_generation,  # type: ignore[attr-defined]
                        generation,
                    )
        finally:
            self._agents_deck_state_save_task = None  # type: ignore[attr-defined]
            if self._agents_deck_state_save_pending is not None:  # type: ignore[attr-defined]
                self._start_agents_deck_state_save_writer()

    async def _flush_agents_deck_state(self) -> None:
        """Await the already-queued latest generation with a bounded timeout."""
        self._ensure_agents_deck_persistence_state()
        if (
            self._agents_deck_state_save_requested
            and not self._agents_deck_state_merged
        ):  # type: ignore[attr-defined]
            worker: Worker[Any] | None = self._agents_deck_state_load_worker  # type: ignore[attr-defined]
            if worker is not None:
                try:
                    await worker.wait()
                except Exception:
                    pass
            elif not self._agents_deck_state_load_resolved:  # type: ignore[attr-defined]
                from ...models.agent_deck_persistence import load_agents_deck_state

                try:
                    snapshot = await asyncio.to_thread(load_agents_deck_state)
                except Exception:
                    log.exception("Agents deck state load failed")
                    from ...models.agent_deck_persistence import (
                        EMPTY_AGENTS_DECK_STATE,
                    )

                    snapshot = EMPTY_AGENTS_DECK_STATE
                self._resolve_agents_deck_state_load(snapshot)
            self._install_loaded_agents_deck_state()
            if (
                self._agents_deck_state_merged
                and self._agents_deck_state_save_requested
            ):  # type: ignore[attr-defined]
                self._agents_deck_state_save_requested = False  # type: ignore[attr-defined]
                self._agents_deck_state_changed()

        async def _flush() -> None:
            target = self._agents_deck_state_save_generation  # type: ignore[attr-defined]
            while self._agents_deck_state_completed_generation < target:  # type: ignore[attr-defined]
                task: asyncio.Task[None] | None = self._agents_deck_state_save_task  # type: ignore[attr-defined]
                if task is None:
                    if self._agents_deck_state_save_pending is None:  # type: ignore[attr-defined]
                        break
                    self._start_agents_deck_state_save_writer()
                    await asyncio.sleep(0)
                    continue
                await asyncio.shield(task)

        try:
            await asyncio.wait_for(_flush(), timeout=_FLUSH_TIMEOUT_SECONDS)
        except TimeoutError:
            log.warning("Timed out flushing Agents deck state during controlled exit")
        except Exception:
            log.exception("Agents deck state flush failed during controlled exit")


__all__ = [
    "AgentDeckPersistenceMixin",
]
