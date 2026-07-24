"""Non-blocking app-owned persistence for Admin Center navigation."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..modals.config_center_catalog import CenterTab

log = logging.getLogger(__name__)

_FLUSH_TIMEOUT_SECONDS = 2.0


class AdminCenterPersistenceMixin:
    """Remember, coalesce, save, and flush the latest activated center tab."""

    _last_admin_center_tab: CenterTab | None
    _admin_center_tab_durable: CenterTab | None
    _admin_center_tab_queued: CenterTab | None
    _admin_center_tab_save_generation: int
    _admin_center_tab_completed_generation: int
    _admin_center_tab_save_pending: tuple[int, CenterTab] | None
    _admin_center_tab_save_task: asyncio.Task[None] | None

    def _ensure_admin_center_persistence_state(self) -> None:
        """Initialize fields for direct-mixin tests that bypass app startup."""
        defaults: tuple[tuple[str, object], ...] = (
            (
                "_admin_center_tab_durable",
                getattr(self, "_last_admin_center_tab", None),
            ),
            ("_admin_center_tab_queued", None),
            ("_admin_center_tab_save_generation", 0),
            ("_admin_center_tab_completed_generation", 0),
            ("_admin_center_tab_save_pending", None),
            ("_admin_center_tab_save_task", None),
        )
        for name, value in defaults:
            if not hasattr(self, name):
                setattr(self, name, value)

    def _remember_admin_center_tab(self, value: object) -> None:
        """Remember a valid tab immediately and enqueue it for persistence."""
        from ..modals.config_center_catalog import validated_center_tab

        self._ensure_admin_center_persistence_state()
        tab = validated_center_tab(value)
        if tab is None:
            return
        self._last_admin_center_tab = tab
        if tab == self._admin_center_tab_queued:
            return
        if (
            tab == self._admin_center_tab_durable
            and self._admin_center_tab_save_pending is None
            and (
                self._admin_center_tab_save_task is None
                or self._admin_center_tab_save_task.done()
            )
        ):
            return

        generation = self._admin_center_tab_save_generation + 1
        self._admin_center_tab_save_generation = generation
        self._admin_center_tab_save_pending = (generation, tab)
        self._admin_center_tab_queued = tab
        self._start_admin_center_tab_writer()

    def _on_admin_center_tab_activated(self, tab: CenterTab) -> None:
        """Receive the modal's successful-navigation callback."""
        self._remember_admin_center_tab(tab)

    def _save_admin_center_tab_now(self, tab: CenterTab) -> None:
        from ..modals.config_center_state import save_admin_center_last_tab

        save_admin_center_last_tab(tab)

    def _start_admin_center_tab_writer(self) -> None:
        """Start the sole writer for an existing pending generation."""
        self._ensure_admin_center_persistence_state()
        task = self._admin_center_tab_save_task
        if task is not None and not task.done():
            return
        if self._admin_center_tab_save_pending is None:
            return

        from ..util.pump_tasks import spawn_pump_free_task

        task = spawn_pump_free_task(
            self,
            self._run_admin_center_tab_save_loop(),
            name="admin-center-tab-save",
            registry_attr="_pump_free_async_tasks",
        )
        if task is not None:
            self._admin_center_tab_save_task = task

    async def _run_admin_center_tab_save_loop(self) -> None:
        """Write one generation at a time, coalescing to the latest pending."""
        restart = True
        try:
            while True:
                pending = self._admin_center_tab_save_pending
                self._admin_center_tab_save_pending = None
                if pending is None:
                    break
                generation, tab = pending
                try:
                    await asyncio.to_thread(self._save_admin_center_tab_now, tab)
                except Exception:
                    log.exception("Admin Center resume-tab save failed")
                    if (
                        generation == self._admin_center_tab_save_generation
                        and self._admin_center_tab_save_pending is None
                    ):
                        # Permit a later successful activation of the same tab
                        # to retry after this latest-generation failure.
                        self._admin_center_tab_queued = None
                else:
                    self._admin_center_tab_durable = tab
                finally:
                    self._admin_center_tab_completed_generation = max(
                        self._admin_center_tab_completed_generation,
                        generation,
                    )
        except asyncio.CancelledError:
            restart = False
            raise
        finally:
            self._admin_center_tab_save_task = None
            if restart and self._admin_center_tab_save_pending is not None:
                self._start_admin_center_tab_writer()

    async def _flush_admin_center_tab_state(self) -> None:
        """Await the newest queued generation with a bounded timeout."""
        self._ensure_admin_center_persistence_state()

        async def _flush() -> None:
            target = self._admin_center_tab_save_generation
            while self._admin_center_tab_completed_generation < target:
                task = self._admin_center_tab_save_task
                if task is None:
                    if self._admin_center_tab_save_pending is None:
                        break
                    self._start_admin_center_tab_writer()
                    await asyncio.sleep(0)
                    continue
                await asyncio.shield(task)

        try:
            await asyncio.wait_for(_flush(), timeout=_FLUSH_TIMEOUT_SECONDS)
        except TimeoutError:
            log.warning(
                "Timed out flushing Admin Center resume tab during controlled exit"
            )
        except Exception:
            log.exception("Admin Center resume-tab flush failed during controlled exit")


__all__ = ["AdminCenterPersistenceMixin"]
