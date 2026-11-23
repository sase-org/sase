"""AXE surface work for TUI auto-refresh."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ._helpers import callable_accepts_kwarg


class EventAutoRefreshAxeSurfaceMixin:
    """Refresh AXE status as one step of an auto-refresh pass."""

    async def _refresh_auto_refresh_axe_surface(
        self: Any,
        current_tokens: Any,
        *,
        sanity_due: bool,
        refresh_counters: dict[str, Any] | None,
        reloaded: list[str],
        refresh_reason: Callable[..., str],
    ) -> int:
        """Refresh AXE status when its consumed token or watcher is dirty."""
        # Always poll axe status regardless of tab (for STARTING/STOPPING
        # transitions) -- but skip the disk poll on idle ticks when the
        # consumed token parts (service/pid/membership, plus dashboard
        # files only on the Services tab) are unchanged. Heartbeat
        # rewrites of lumberjack status/metrics/logs do not count while
        # those surfaces are hidden. Watcher dirty flags for those files
        # are ignored for the same reason. Also skip while the startup
        # axe init has started but not finished, so a tick cannot set
        # ``_axe_first_load_done`` and skip auto-start.
        startup_axe_busy = getattr(
            self, "_startup_axe_surface_started", False
        ) and not getattr(self, "_axe_first_load_done", False)
        axe_due = (
            refresh_reason(
                "axe",
                use_watcher_dirty=False,
            )
            != "unchanged"
        )
        if refresh_counters is not None:
            refresh_counters["surface_outcomes"]["axe"] = "skipped"
        if (not startup_axe_busy) and not axe_due:
            self._dirty_axe = False
        if (not startup_axe_busy) and axe_due:
            run_axe_refresh = getattr(self, "_run_axe_status_refresh", None)
            should_full = getattr(self, "_axe_should_collect_full", None)
            if callable(should_full):
                axe_full = bool(should_full(sanity_due=sanity_due))
            else:
                axe_full = bool(getattr(self, "_axe_services_visited", False)) and (
                    sanity_due or self.current_tab == "services"
                )
            tail_all_chop_logs = axe_full and sanity_due
            if callable(run_axe_refresh):
                if not getattr(
                    self, "_axe_status_refresh_running", False
                ) and not getattr(
                    self,
                    "_axe_status_refresh_scheduled",
                    False,
                ):
                    if callable_accepts_kwarg(
                        run_axe_refresh, "include_full_snapshots"
                    ):
                        if callable_accepts_kwarg(
                            run_axe_refresh, "tail_all_chop_logs"
                        ):
                            refreshed = await run_axe_refresh(
                                include_full_snapshots=axe_full,
                                tail_all_chop_logs=tail_all_chop_logs,
                            )
                        else:
                            refreshed = await run_axe_refresh(
                                include_full_snapshots=axe_full,
                            )
                    else:
                        refreshed = await run_axe_refresh()
                    if refreshed:
                        self._dirty_axe = False
                        self._accept_surface_token("axe", current_tokens)
                        if getattr(self, "_axe_last_apply_skipped", False):
                            if refresh_counters is not None:
                                refresh_counters["surface_outcomes"]["axe"] = (
                                    "read_unchanged"
                                )
                        else:
                            if refresh_counters is not None:
                                refresh_counters["surface_outcomes"]["axe"] = (
                                    "applied_changed"
                                )
                            reloaded.append("axe")
                            axe_file_opens = self._axe_collector_file_opens()
                elif refresh_counters is not None:
                    refresh_counters["surface_reasons"]["axe"] = "refresh_in_flight"
            else:
                # Narrow EventAutoRefreshMixin test doubles do not include the
                # AXE loader mixin; production always takes the guarded path.
                load_axe = self._load_axe_status_async  # type: ignore[attr-defined]
                if callable_accepts_kwarg(load_axe, "include_full_snapshots"):
                    if callable_accepts_kwarg(load_axe, "tail_all_chop_logs"):
                        await load_axe(
                            include_full_snapshots=axe_full,
                            tail_all_chop_logs=tail_all_chop_logs,
                        )
                    else:
                        await load_axe(include_full_snapshots=axe_full)
                else:
                    await load_axe()
                self._dirty_axe = False
                self._accept_surface_token("axe", current_tokens)
                if refresh_counters is not None:
                    refresh_counters["surface_outcomes"]["axe"] = "applied_changed"
                if not getattr(self, "_axe_last_apply_skipped", False):
                    reloaded.append("axe")
                    axe_file_opens = self._axe_collector_file_opens()

        return axe_file_opens
