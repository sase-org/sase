"""Async full-fleet AXE refresh orchestration and startup init."""

from __future__ import annotations

from ...util.pump_tasks import spawn_pump_free_task
from ...util.trace import tui_trace
from ._data import collect_axe_status_data
from ._refresh_collect import AxeRefreshCollectMixin


class AxeRefreshFullMixin(AxeRefreshCollectMixin):
    """Mixin running the guarded full AXE refresh and startup load."""

    async def _load_axe_status_async(
        self,
        *,
        include_full_snapshots: bool | None = None,
        tail_all_chop_logs: bool = False,
    ) -> None:
        """Load axe status with disk I/O in a background thread."""
        import asyncio

        with tui_trace("axe.load_status") as extra:
            kwargs = self._axe_collector_kwargs(
                include_full_snapshots=include_full_snapshots,
                tail_all_chop_logs=tail_all_chop_logs,
            )
            data = await asyncio.to_thread(
                collect_axe_status_data,
                cache=kwargs["cache"],
                include_full_snapshots=kwargs["include_full_snapshots"],
                tail_chop_keys=kwargs["tail_chop_keys"],
                tail_service_name=kwargs["tail_service_name"],
            )
            extra["file_opens"] = data.stats.file_opens
            extra["include_full_snapshots"] = data.include_full_snapshots
            self._apply_axe_status_data(data)

    def _schedule_axe_async_refresh(self) -> None:
        """Schedule an async axe status reload without blocking."""
        self._axe_status_refresh_want_full = True
        if getattr(self, "_axe_status_refresh_running", False):
            self._axe_status_refresh_pending = True
            return
        if getattr(self, "_axe_status_refresh_scheduled", False):
            return
        self._axe_status_refresh_scheduled = True
        self._spawn_axe_status_refresh_task()

    def _spawn_axe_status_refresh_task(self) -> None:
        """Run the full AXE refresh without blocking Textual's pump."""
        task = spawn_pump_free_task(
            self,
            self._run_axe_status_refresh(),
            name="sase-axe-status-refresh",
            registry_attr="_pump_free_async_tasks",
        )
        if task is None:
            self._axe_status_refresh_scheduled = False

    async def _run_axe_status_refresh(
        self,
        *,
        include_full_snapshots: bool | None = None,
        tail_all_chop_logs: bool = False,
    ) -> bool:
        """Run one guarded AXE refresh and coalesce a trailing request."""
        self._axe_status_refresh_scheduled = False
        if getattr(self, "_axe_status_refresh_running", False):
            if include_full_snapshots:
                self._axe_status_refresh_want_full = True
            if tail_all_chop_logs:
                self._axe_status_refresh_want_all_tails = True
            self._axe_status_refresh_pending = True
            return False
        want_full = bool(getattr(self, "_axe_status_refresh_want_full", False))
        want_all_tails = bool(
            getattr(self, "_axe_status_refresh_want_all_tails", False)
        )
        self._axe_status_refresh_want_full = False
        self._axe_status_refresh_want_all_tails = False
        if include_full_snapshots:
            want_full = True
        if tail_all_chop_logs:
            want_all_tails = True
        self._axe_status_refresh_running = True
        try:
            await self._load_axe_status_async(
                include_full_snapshots=True if want_full else include_full_snapshots,
                tail_all_chop_logs=want_all_tails,
            )
            return True
        finally:
            self._axe_status_refresh_running = False
            if getattr(self, "_axe_status_refresh_pending", False):
                self._axe_status_refresh_pending = False
                self._schedule_axe_async_refresh()

    async def _run_axe_startup_init(self) -> None:
        """Load axe status and trigger startup auto-start/restart off the critical path."""
        with tui_trace("axe.startup"):
            await self._run_axe_startup_init_body()

    async def _run_axe_startup_init_body(self) -> None:
        """Inner axe startup body; wrapped by :meth:`_run_axe_startup_init`.

        First load is header-only so ``axe_ready`` does not walk chop
        history. When AXE is the initially visible tab, a coalesced full
        refresh completes snapshots in the background after that cheap
        paint. Other tabs warm on tab switch / auto-refresh (tui_perf
        rule 5) instead of contending with the visible surface's load.
        """
        import asyncio

        await self._load_axe_status_async(include_full_snapshots=False)
        initial_tab = getattr(self, "_startup_initial_tab", None)
        current_tab = getattr(self, "current_tab", None)
        if initial_tab == "services" or current_tab == "services":
            schedule = getattr(self, "_schedule_axe_async_refresh", None)
            if callable(schedule):
                schedule()
        if self._restart_axe and self.axe_running:  # type: ignore[attr-defined]
            from sase.service.control import restart_service_host

            await asyncio.to_thread(restart_service_host)
            self._schedule_axe_async_refresh()
        elif self._auto_start_axe and not self.axe_running:  # type: ignore[attr-defined]
            from sase.service.control import start_service_host

            await asyncio.to_thread(start_service_host)
            self._schedule_axe_async_refresh()


__all__ = ["AxeRefreshFullMixin"]
