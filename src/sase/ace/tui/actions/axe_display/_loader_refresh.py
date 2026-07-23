"""AXE status collection, cache application, and refresh orchestration."""

from __future__ import annotations

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
    is_slot_running,
    mark_slot_finished,
    read_slot_output_tail,
)
from ...util.pump_tasks import spawn_pump_free_task
from ...widgets.bgcmd_list import AxeItem, ChopItem
from ._data import (
    AxeCollectedData,
    BgCmdSnapshot,
    ChopSnapshot,
    collect_axe_status_data,
    collect_chop_snapshot,
)
from ._loader_items import AxeDisplayItemsMixin


class AxeDisplayRefreshMixin(AxeDisplayItemsMixin):
    """Mixin providing AXE data collection and cache refreshes."""

    def _load_axe_status(self) -> None:
        """Load axe status from disk and update display."""
        data = collect_axe_status_data()
        self._apply_axe_status_data(data)

    def _apply_axe_status_data(self, data: AxeCollectedData) -> None:
        """Apply collected axe status data to app state and refresh widgets."""
        # Clear startup loading indicators on the first completed axe load.
        if not self._axe_first_load_done:
            self._axe_first_load_done = True
            from ...widgets import AxeDashboard, AxeInfoPanel

            try:
                self.query_one(  # type: ignore[attr-defined]
                    "#axe-dashboard", AxeDashboard
                ).loading = False
            except Exception:
                pass
            try:
                info_panel = self.query_one(  # type: ignore[attr-defined]
                    "#axe-info-panel", AxeInfoPanel
                )
                info_panel.set_loading(False)
            except Exception:
                pass
            self._maybe_end_startup_stopwatch()  # type: ignore[attr-defined]

        self.axe_running = data.axe_running

        # Clear starting/restarting state once confirmed running
        if self.axe_running:
            self._set_axe_starting(False)  # type: ignore[attr-defined]
            self._set_axe_restarting(False)  # type: ignore[attr-defined]

        # Clear stopping state once confirmed stopped
        if not self.axe_running:
            self._set_axe_stopping(False)  # type: ignore[attr-defined]

        self._axe_status = data.axe_status
        self._axe_metrics = data.axe_metrics
        self._axe_output = data.axe_output
        self._axe_degraded_status = data.degraded_status

        # Apply lumberjack names
        self._axe_lumberjack_names = data.lumberjack_names
        if self._axe_lumberjack_idx is not None and self._axe_lumberjack_idx >= len(
            self._axe_lumberjack_names
        ):
            self._axe_lumberjack_idx = None

        # Apply bgcmd state
        self._bgcmd_slots = data.bgcmd_slots

        # Apply per-lumberjack and bgcmd caches populated by the async collector
        # so that navigation renders from memory rather than from disk.
        self._axe_lumberjack_statuses = data.lumberjack_statuses
        self._axe_lumberjack_metrics = data.lumberjack_metrics
        self._axe_lumberjack_log_tails = data.lumberjack_log_tails
        self._axe_bgcmd_details = data.bgcmd_details
        # Apply chop-history caches. The sidebar (Phase 3) and the
        # chop-run dashboard (Phase 4) read from these without disk I/O.
        self._axe_lumberjack_chop_names = data.lumberjack_chop_names
        # Translate any pinned run-history offsets to keep the user looking
        # at the same run_id when new runs arrive at the head of history.
        self._reconcile_chop_run_offsets(data.chop_snapshots)
        self._axe_chop_snapshots = data.chop_snapshots
        self._axe_lumberjack_snapshots = data.lumberjack_snapshots

        self._update_bgcmd_count()
        self._build_axe_items()

        # Update display if on axe tab
        if self.current_tab == "axe":
            self._refresh_axe_display()  # type: ignore[attr-defined]

        # Update keybinding footer for all tabs (X binding changes label)
        self._update_axe_keybinding()  # type: ignore[attr-defined]

    async def _load_axe_status_async(self) -> None:
        """Load axe status with disk I/O in a background thread."""
        import asyncio

        data = await asyncio.to_thread(collect_axe_status_data)
        self._apply_axe_status_data(data)

    def _schedule_axe_async_refresh(self) -> None:
        """Schedule an async axe status reload without blocking."""
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

    async def _run_axe_status_refresh(self) -> bool:
        """Run one guarded full AXE refresh and coalesce a trailing request."""
        self._axe_status_refresh_scheduled = False
        if getattr(self, "_axe_status_refresh_running", False):
            self._axe_status_refresh_pending = True
            return False
        self._axe_status_refresh_running = True
        try:
            await self._load_axe_status_async()
            return True
        finally:
            self._axe_status_refresh_running = False
            if getattr(self, "_axe_status_refresh_pending", False):
                self._axe_status_refresh_pending = False
                self._schedule_axe_async_refresh()

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

            def _read_chop() -> ChopSnapshot:
                if existing is None:
                    return collect_chop_snapshot(lj_name, chop_name, description)
                return collect_chop_snapshot(
                    lj_name,
                    chop_name,
                    description,
                    enabled=existing.enabled,
                    script=existing.script,
                    resolved_path=existing.resolved_path,
                    config_status=existing.config_status,
                    generated=existing.generated,
                    base_chop_name=existing.base_chop_name,
                    target_key=existing.target_key,
                )

            snap = await asyncio.to_thread(_read_chop)
            # Re-read current caches/tab after the await. Selection may have
            # moved, but the originally selected chop's keyed cache remains a
            # valid update and the display refresh uses the current selection.
            # Keep the user's pinned offset (if any) on the same run_id
            # across the targeted refresh.
            self._reconcile_chop_run_offsets({(lj_name, chop_name): snap})
            self._axe_chop_snapshots[(lj_name, chop_name)] = snap
            jack_snap = self._axe_lumberjack_snapshots.get(lj_name)
            if jack_snap is not None:
                jack_snap.chops = [
                    snap if c.chop_name == chop_name else c for c in jack_snap.chops
                ]
            if self.current_tab == "axe":
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
            if self.current_tab == "axe":
                self._refresh_axe_display()  # type: ignore[attr-defined]
        elif isinstance(view, int):
            slot = view

            def _read_slot() -> tuple[BackgroundCommandInfo | None, bool, str]:
                info = get_slot_info(slot)
                running = is_slot_running(slot)
                if info is not None and not running and info.finished_at is None:
                    mark_slot_finished(slot)
                    info = get_slot_info(slot)
                return info, running, read_slot_output_tail(slot, 500)

            info, running, tail = await asyncio.to_thread(_read_slot)
            # ``slot`` identifies the snapshot target; current tab state is
            # intentionally re-read below after the await.
            self._axe_bgcmd_details[slot] = BgCmdSnapshot(
                info=info, running=running, output_tail=tail
            )
            if self.current_tab == "axe":
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

    def _axe_live_tick(self) -> None:
        """Per-second hook that pulls fresh data for an active chop run.

        Called from the AXE-tab branch of the countdown tick. Routes through
        the existing targeted refresh so disk I/O still happens in a worker
        thread and the cache write goes through the same reconciliation as
        ``y``. No-op when the selected row is not a chop with a running run.
        """
        if self.current_tab != "axe":
            return
        if not self._axe_selected_chop_has_running_run():
            return
        self._schedule_targeted_axe_refresh()

    def _reconcile_chop_run_offsets(
        self, new_snapshots: dict[tuple[str, str], ChopSnapshot]
    ) -> None:
        """Translate pinned chop run offsets so they follow the same run_id.

        Called before installing a new collector payload (full or targeted).
        For each chop with a non-zero offset, the user is "pinned" to a
        specific older run. When the new snapshot prepends additional runs,
        the offset must shift forward to keep pointing at the same run_id.
        If the pinned run_id is no longer present, the pin is dropped so
        the next render clamps to the newest run.
        """
        offsets = getattr(self, "_axe_chop_run_offsets", None)
        if not offsets:
            return
        for chop_key, offset in list(offsets.items()):
            if offset <= 0:
                continue
            old_snap = self._axe_chop_snapshots.get(chop_key)
            if old_snap is None or offset >= len(old_snap.runs):
                offsets.pop(chop_key, None)
                continue
            pinned_run_id = old_snap.runs[offset].entry.run_id
            new_snap = new_snapshots.get(chop_key)
            if new_snap is None:
                offsets.pop(chop_key, None)
                continue
            new_idx = next(
                (
                    i
                    for i, r in enumerate(new_snap.runs)
                    if r.entry.run_id == pinned_run_id
                ),
                None,
            )
            if new_idx is None or new_idx == 0:
                # Pinned run disappeared or is now newest → drop the pin
                # so resolution falls back to newest-tracking.
                offsets.pop(chop_key, None)
            else:
                offsets[chop_key] = new_idx

    async def _run_axe_startup_init(self) -> None:
        """Load axe status and trigger startup auto-start/restart off the critical path."""
        await self._load_axe_status_async()
        if self._restart_axe and self.axe_running:  # type: ignore[attr-defined]
            self._restart_axe_daemon(source="ace startup restart")  # type: ignore[attr-defined]
        elif self._auto_start_axe and not self.axe_running:  # type: ignore[attr-defined]
            self._start_axe(source="ace startup")  # type: ignore[attr-defined]
