"""Targeted per-item AXE refresh, tail backfill, and live-tick routing."""

from __future__ import annotations

from typing import Any

from sase.axe.state import (
    LumberjackMetrics,
    LumberjackStatus,
    read_lumberjack_log_tail,
    read_lumberjack_metrics,
    read_lumberjack_status,
)

from ...bgcmd import (
    BackgroundCommandInfo,
    get_slot_info,
    read_info_output_tail,
)
from ...util.pump_tasks import spawn_pump_free_task
from ...widgets.bgcmd_list import AxeItem, ChopItem, ServiceProcItem
from ._data import BgCmdSnapshot, ChopSnapshot, collect_chop_snapshot
from ._refresh_full import AxeRefreshFullMixin


class AxeRefreshTargetedMixin(AxeRefreshFullMixin):
    """Mixin refreshing only the selected AXE item's on-disk state."""

    async def _refresh_selected_axe_item_async(self) -> None:
        """Re-read on-disk state for the currently selected axe item only.

        This is the fast path for the `y` keymap: it repaints the focused
        panel in well under the full-fleet refresh time, so the user sees
        fresh data for what they are actually looking at without waiting.

        Falls through silently if nothing is selected or the view is the
        parent axe entry (the full-fleet refresh handles that case).
        """
        import asyncio

        # Snapshot the selection at call time; the user may have moved by the
        # time the background read completes, but we still want to write the
        # cache entry for the originally-selected item.
        self._derive_axe_view_from_selection()
        view = self._axe_current_view
        lumberjack_idx = self._axe_lumberjack_idx
        names = list(self._axe_lumberjack_names)

        # Chop row selected: refresh only that chop's bounded run-history
        # cache. This is the Phase 2 fast path for ``y`` on a chop.
        selected_item: AxeItem | None = None
        if 0 <= self.current_idx < len(self._axe_items):
            selected_item = self._axe_items[self.current_idx]
        if isinstance(selected_item, ChopItem):
            lj_name = selected_item.lumberjack_name
            chop_name = selected_item.chop_name
            existing = self._axe_chop_snapshots.get((lj_name, chop_name))
            description = existing.description if existing is not None else ""
            description_summary = (
                existing.description_summary if existing is not None else ""
            )
            description_body = existing.description_body if existing is not None else ""

            def _read_chop() -> ChopSnapshot:
                cache = getattr(self, "_axe_status_read_cache", None)
                if existing is None:
                    return collect_chop_snapshot(
                        lj_name,
                        chop_name,
                        description,
                        description_summary=description_summary,
                        description_body=description_body,
                        cache=cache,
                        tail_run_logs=True,
                    )
                return collect_chop_snapshot(
                    lj_name,
                    chop_name,
                    description,
                    description_summary=description_summary,
                    description_body=description_body,
                    enabled=existing.enabled,
                    script=existing.script,
                    resolved_path=existing.resolved_path,
                    config_status=existing.config_status,
                    generated=existing.generated,
                    base_chop_name=existing.base_chop_name,
                    target_key=existing.target_key,
                    interval_seconds=existing.interval_seconds,
                    interval_source=existing.interval_source,
                    cache=cache,
                    tail_run_logs=True,
                )

            snap = await asyncio.to_thread(_read_chop)
            # Re-read current caches/tab after the await. Selection may have
            # moved, but the originally selected chop's keyed cache remains a
            # valid update and the display refresh uses the current selection.
            # Keep the user's pinned offset (if any) on the same run_id
            # across the targeted refresh.
            self._reconcile_chop_run_offsets({(lj_name, chop_name): snap})
            self._axe_chop_snapshots[(lj_name, chop_name)] = snap
            tailed = getattr(self, "_axe_tailed_chops", None)
            if tailed is None:
                self._axe_tailed_chops = set()
                tailed = self._axe_tailed_chops
            tailed.add((lj_name, chop_name))
            jack_snap = self._axe_lumberjack_snapshots.get(lj_name)
            if jack_snap is not None:
                jack_snap.chops = [
                    snap if c.chop_name == chop_name else c for c in jack_snap.chops
                ]
                jack_snap.overrun_chop_count = sum(
                    1
                    for c in jack_snap.chops
                    if c.overrun is not None and c.overrun.level == "over"
                )
                jack_snap.intermittent_chop_count = sum(
                    1
                    for c in jack_snap.chops
                    if c.overrun is not None and c.overrun.level == "intermittent"
                )
            if self.current_tab == "services":
                self._refresh_axe_display()  # type: ignore[attr-defined]
            return

        if isinstance(selected_item, ServiceProcItem):
            name = selected_item.name

            def _read_service() -> tuple[Any, str]:
                from pathlib import Path

                from sase.service.control import (
                    latest_service_log_lines,
                    persisted_or_current_status,
                )
                from sase.service.paths import service_proc_output_log_path

                snapshot = persisted_or_current_status()
                proc_status = next(
                    (proc for proc in snapshot.procs if proc.name == name),
                    None,
                )
                log_path = Path(
                    service_proc_output_log_path(name)
                    if proc_status is None or proc_status.log_path is None
                    else proc_status.log_path
                )
                return snapshot, latest_service_log_lines(log_path, lines=500)

            snapshot, tail = await asyncio.to_thread(_read_service)
            self._service_status = snapshot
            self._service_status_error = None
            self._service_log_tails[name] = tail
            tailed = getattr(self, "_service_tailed_names", None)
            if tailed is None:
                self._service_tailed_names = set()
                tailed = self._service_tailed_names
            tailed.add(name)
            if self.current_tab == "services":
                self._refresh_axe_display()  # type: ignore[attr-defined]
            return

        if (
            view == "axe"
            and lumberjack_idx is not None
            and 0 <= lumberjack_idx < len(names)
        ):
            name = names[lumberjack_idx]

            def _read_one() -> tuple[
                LumberjackStatus | None, LumberjackMetrics | None, str
            ]:
                return (
                    read_lumberjack_status(name),
                    read_lumberjack_metrics(name),
                    read_lumberjack_log_tail(name, 500),
                )

            status, metrics, log_tail = await asyncio.to_thread(_read_one)
            # ``name`` identifies the snapshot target; current tab state is
            # intentionally re-read below after the await.
            self._axe_lumberjack_statuses[name] = status
            self._axe_lumberjack_metrics[name] = metrics
            self._axe_lumberjack_log_tails[name] = log_tail
            if self.current_tab == "services":
                self._refresh_axe_display()  # type: ignore[attr-defined]
        elif isinstance(view, int):
            slot = view

            def _read_slot() -> tuple[BackgroundCommandInfo | None, str]:
                info = get_slot_info(slot)
                tail = "" if info is None else read_info_output_tail(slot, info, 500)
                return info, tail

            info, tail = await asyncio.to_thread(_read_slot)
            # ``slot`` identifies the snapshot target; current tab state is
            # intentionally re-read below after the await.
            if info is not None and self._bgcmd_slot_visible(slot, info):
                self._bgcmd_slots = [
                    (s, info if s == slot else i) for s, i in self._bgcmd_slots
                ]
                self._axe_bgcmd_details[slot] = BgCmdSnapshot(
                    info=info, running=info.running, output_tail=tail
                )
            if self.current_tab == "services":
                self._refresh_axe_display()  # type: ignore[attr-defined]

    def _schedule_targeted_axe_refresh(self) -> None:
        """Schedule a targeted refresh of the selected item's on-disk state."""
        if getattr(self, "_axe_targeted_refresh_running", False):
            self._axe_targeted_refresh_pending = True
            return
        if getattr(self, "_axe_targeted_refresh_scheduled", False):
            return
        self._axe_targeted_refresh_scheduled = True
        self._spawn_targeted_axe_refresh_task()

    def _spawn_targeted_axe_refresh_task(self) -> None:
        """Run the selected-item refresh without blocking Textual's pump."""
        task = spawn_pump_free_task(
            self,
            self._run_targeted_axe_refresh(),
            name="sase-axe-targeted-refresh",
            registry_attr="_pump_free_async_tasks",
        )
        if task is None:
            self._axe_targeted_refresh_scheduled = False

    async def _run_targeted_axe_refresh(self) -> None:
        """Run one targeted refresh and collapse overlapping live ticks."""
        self._axe_targeted_refresh_scheduled = False
        if getattr(self, "_axe_targeted_refresh_running", False):
            self._axe_targeted_refresh_pending = True
            return
        self._axe_targeted_refresh_running = True
        try:
            await self._refresh_selected_axe_item_async()
        finally:
            self._axe_targeted_refresh_running = False
            if getattr(self, "_axe_targeted_refresh_pending", False):
                self._axe_targeted_refresh_pending = False
                self._schedule_targeted_axe_refresh()

    def _axe_ensure_selected_chop_tails(self) -> None:
        """Fetch per-run log tails for a newly selected chop.

        Full-fleet ticks only tail the currently rendered chop. Selecting a
        different chop between ticks would otherwise paint empty output until
        the next collect, so the first visit schedules a targeted refresh.
        """
        chop_sel = getattr(self, "_axe_chop_selection", None)
        if chop_sel is None:
            return
        tailed = getattr(self, "_axe_tailed_chops", None)
        if tailed is None:
            self._axe_tailed_chops = set()
            tailed = self._axe_tailed_chops
        if chop_sel in tailed:
            return
        snap = getattr(self, "_axe_chop_snapshots", {}).get(chop_sel)
        if snap is None or not snap.runs:
            tailed.add(chop_sel)
            return
        run_idx = self._axe_resolve_chop_run_offset(chop_sel)
        selected = snap.runs[max(0, min(run_idx, len(snap.runs) - 1))]
        if selected.output_tail:
            tailed.add(chop_sel)
            return
        tailed.add(chop_sel)
        self._schedule_targeted_axe_refresh()

    def _axe_ensure_selected_service_tail(self) -> None:
        """Fetch the bounded log tail for a newly selected service-proc row."""
        service_name = getattr(self, "_axe_service_selection", None)
        if service_name is None:
            return
        tailed = getattr(self, "_service_tailed_names", None)
        if tailed is None:
            self._service_tailed_names = set()
            tailed = self._service_tailed_names
        if service_name in tailed:
            return
        tailed.add(service_name)
        self._schedule_targeted_axe_refresh()

    def _axe_selected_chop_has_running_run(self) -> bool:
        """Return True when the selected chop's newest cached run is active.

        Used to drive the per-second live refresh while a script chop is
        streaming output. Lumberjack and bgcmd selections always return
        False since they don't participate in run-history streaming.
        """
        chop_key = self._axe_chop_selection
        if chop_key is None:
            return False
        snap = self._axe_chop_snapshots.get(chop_key)
        if snap is None or not snap.runs:
            return False
        return snap.runs[0].entry.status in {"running", "launched"}

    def _axe_selected_service_running(self) -> bool:
        """Return True when the selected service-proc row is currently active."""
        service_name = getattr(self, "_axe_service_selection", None)
        snapshot = getattr(self, "_service_status", None)
        if service_name is None or snapshot is None:
            return False
        proc = next(
            (item for item in snapshot.procs if item.name == service_name), None
        )
        return proc is not None and proc.state == "running"

    def _axe_live_tick(self) -> None:
        """Per-second hook that pulls fresh data for an active chop run.

        Called from the AXE-tab branch of the countdown tick. Routes through
        the existing targeted refresh so disk I/O still happens in a worker
        thread and the cache write goes through the same reconciliation as
        ``y``. No-op when the selected row is not a chop with a running run.
        """
        if self.current_tab != "services":
            return
        if self._axe_selected_service_running():
            self._schedule_targeted_axe_refresh()
            return
        if not self._axe_selected_chop_has_running_run():
            return
        self._schedule_targeted_axe_refresh()


__all__ = ["AxeRefreshTargetedMixin"]
