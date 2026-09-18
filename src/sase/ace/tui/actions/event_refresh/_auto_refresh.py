"""Auto-refresh timer handling for sase's TUI event refreshes."""

from __future__ import annotations

from .._debug_leaks import debug_leaks_enabled, log_leak_snapshot
from ...util.pump_tasks import spawn_pump_free_task
from ._auto_refresh_surfaces import EventAutoRefreshSurfacesMixin


class EventAutoRefreshMixin(EventAutoRefreshSurfacesMixin):
    """Mixin for auto-refresh timers and lightweight live-file updates."""

    def _on_auto_refresh(self) -> None:
        """Timer-facing sync callback that launches a pump-free refresh.

        When the user is mid-burst on j/k the refresh defers itself for the
        remainder of the navigation window plus a small overshoot.  A new
        ``set_timer`` call schedules a single retry; if the user is *still*
        navigating when that fires, the same gate will defer it again.

        Phase 7: when the inotify watcher is active each surface's refresh
        is gated on its dirty flag; flags clear after the refresh runs.
        Token probes additionally skip unchanged surfaces when
        ``ace_refresh_tokens`` is enabled. Every sanity interval we ignore
        those gates and run a full reconcile to recover from missed events.
        """
        self._countdown_remaining = self.refresh_interval
        if self._nav_gate.is_navigating():
            if getattr(self, "_auto_refresh_deferred", False):
                return
            self._auto_refresh_deferred = True
            delay = self._nav_gate.time_until_idle() + 0.05
            self.set_timer(delay, self._retry_auto_refresh)  # type: ignore[attr-defined]
            return
        if self._prompt_input_active():
            return
        if getattr(self, "_auto_refresh_running", False):
            self._auto_refresh_pending = True
            return
        if getattr(self, "_auto_refresh_scheduled", False):
            return
        self._auto_refresh_scheduled = True
        self._spawn_auto_refresh_task()

    def _retry_auto_refresh(self) -> None:
        """Navigation-gate timer callback that only invokes the sync spawner."""
        self._auto_refresh_deferred = False
        self._on_auto_refresh()

    def _spawn_auto_refresh_task(self) -> None:
        """Run auto-refresh without making Textual's message pump await it."""
        task = spawn_pump_free_task(
            self,
            self._run_auto_refresh(),
            name="sase-auto-refresh",
            registry_attr="_pump_free_async_tasks",
        )
        if task is None:
            self._auto_refresh_scheduled = False

    async def _run_auto_refresh(self) -> None:
        """Run one guarded refresh and coalesce a trailing timer tick."""
        self._auto_refresh_scheduled = False
        if getattr(self, "_auto_refresh_running", False):
            self._auto_refresh_pending = True
            return
        self._auto_refresh_running = True
        try:
            await self._run_auto_refresh_body()
        finally:
            self._auto_refresh_running = False
            if getattr(self, "_auto_refresh_pending", False):
                self._auto_refresh_pending = False
                self._on_auto_refresh()

    def action_debug_leak_snapshot(self) -> None:
        """One-shot leak snapshot keybind gated by ``SASE_ACE_DEBUG_LEAKS=1``.

        Logs the snapshot and surfaces the headline counts via the
        Textual notification toast so the snapshot is visible without
        digging through the log file.
        """
        if not debug_leaks_enabled():
            return
        snapshot = log_leak_snapshot(self, source="keybind")
        message = (
            f"artifact_cache={snapshot['artifact_page_cache']} "
            f"watches={snapshot['fs_watcher_watches']} "
            f"dismissed={snapshot['dismissed_agent_objects']} "
            f"agents={snapshot['agents_with_children']} "
            f"tasks={snapshot['pending_asyncio_tasks']} "
            f"fds={snapshot['open_fds']}"
        )
        try:
            self.notify(message, title="leak snapshot", timeout=10)  # type: ignore[attr-defined]
        except Exception:
            pass
