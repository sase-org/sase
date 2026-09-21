"""AXE status collection, cache application, and chop-offset reconciliation."""

from __future__ import annotations

from typing import TypedDict

from ...bgcmd import BackgroundCommandInfo, bgcmd_identity
from ._data import AxeCollectedData, ChopSnapshot, collect_axe_status_data
from ._loader_items import AxeDisplayItemsMixin
from ._read_cache import AxeStatusReadCache


class _AxeCollectorKwargs(TypedDict):
    cache: AxeStatusReadCache
    include_full_snapshots: bool
    tail_chop_keys: frozenset[tuple[str, str]] | None
    tail_service_name: str | None


class AxeRefreshCollectMixin(AxeDisplayItemsMixin):
    """Mixin collecting AXE status and applying it to app state."""

    def _axe_collector_kwargs(
        self,
        *,
        include_full_snapshots: bool | None = None,
        tail_all_chop_logs: bool = False,
    ) -> _AxeCollectorKwargs:
        """Return keyword arguments for :func:`collect_axe_status_data`.

        Default is header-only unless the AXE tab is visible. The first
        startup load used to force a full snapshot so the cache was warm;
        that walked every chop run even when Agents was showing (sase-132.1
        live traces: 452 ``file_opens``, ~400 run JSON parses).
        """
        if include_full_snapshots is None:
            include_full_snapshots = (
                getattr(self, "current_tab", "services") == "services"
            )
        cache = getattr(self, "_axe_status_read_cache", None)
        if cache is None:
            cache = AxeStatusReadCache()
            self._axe_status_read_cache = cache
        tail_chop_keys: frozenset[tuple[str, str]] | None
        if not include_full_snapshots:
            tail_chop_keys = frozenset()
        elif tail_all_chop_logs:
            tail_chop_keys = None
        elif getattr(self, "current_tab", "services") == "services":
            derive = getattr(self, "_derive_axe_view_from_selection", None)
            if callable(derive):
                derive()
            chop_sel = getattr(self, "_axe_chop_selection", None)
            tail_chop_keys = (
                frozenset({chop_sel}) if chop_sel is not None else frozenset()
            )
        else:
            tail_chop_keys = frozenset()
        tail_service_name = (
            getattr(self, "_axe_service_selection", None)
            if include_full_snapshots
            else None
        )
        return {
            "cache": cache,
            "include_full_snapshots": include_full_snapshots,
            "tail_chop_keys": tail_chop_keys,
            "tail_service_name": tail_service_name,
        }

    def _load_axe_status(self) -> None:
        """Load axe status from disk and update display."""
        kwargs = self._axe_collector_kwargs(include_full_snapshots=True)
        data = collect_axe_status_data(
            cache=kwargs["cache"],
            include_full_snapshots=kwargs["include_full_snapshots"],
            tail_chop_keys=kwargs["tail_chop_keys"],
            tail_service_name=kwargs["tail_service_name"],
        )
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
            self._mark_startup_axe_ready()  # type: ignore[attr-defined]
            self._maybe_end_startup_stopwatch()  # type: ignore[attr-defined]

        self.axe_running = data.axe_running

        # Clear starting/restarting state once confirmed running
        if self.axe_running:
            self._set_axe_starting(False)  # type: ignore[attr-defined]
            self._set_axe_restarting(False)  # type: ignore[attr-defined]

        # Clear stopping state once confirmed stopped
        if not self.axe_running:
            self._set_axe_stopping(False)  # type: ignore[attr-defined]

        self._axe_degraded_status = data.degraded_status
        self._service_status = data.service_status

        # Apply lumberjack names
        self._axe_lumberjack_names = data.lumberjack_names
        if self._axe_lumberjack_idx is not None and self._axe_lumberjack_idx >= len(
            self._axe_lumberjack_names
        ):
            self._axe_lumberjack_idx = None

        # Apply bgcmd state, hiding dismissals whose persistence is still in
        # flight and releasing launches whose oneshot row has now landed.
        self._bgcmd_slots = self._settle_bgcmd_slots(data.bgcmd_slots)
        visible_bgcmd_slots = {slot for slot, _ in self._bgcmd_slots}

        # Apply per-lumberjack and bgcmd caches populated by the async collector
        # so that navigation renders from memory rather than from disk.
        self._axe_lumberjack_statuses = data.lumberjack_statuses
        self._axe_lumberjack_metrics = data.lumberjack_metrics
        # Apply chop-history caches. The sidebar (Phase 3) and the
        # chop-run dashboard (Phase 4) read from these without disk I/O.
        self._axe_lumberjack_chop_names = data.lumberjack_chop_names
        if data.include_full_snapshots:
            self._axe_output = data.axe_output
            self._axe_lumberjack_log_tails = data.lumberjack_log_tails
            self._axe_bgcmd_details = {
                slot: snap
                for slot, snap in data.bgcmd_details.items()
                if slot in visible_bgcmd_slots
            }
            if data.service_log_tails:
                merged_service_tails = dict(getattr(self, "_service_log_tails", {}))
                merged_service_tails.update(data.service_log_tails)
                self._service_log_tails = merged_service_tails
            tailed_service = getattr(self, "_service_tailed_names", None)
            if tailed_service is None:
                self._service_tailed_names = set()
                tailed_service = self._service_tailed_names
            tailed_service.update(data.tailed_service_names)
            # Translate any pinned run-history offsets to keep the user looking
            # at the same run_id when new runs arrive at the head of history.
            self._reconcile_chop_run_offsets(data.chop_snapshots)
            self._axe_chop_snapshots = data.chop_snapshots
            self._axe_lumberjack_snapshots = data.lumberjack_snapshots
            tailed = getattr(self, "_axe_tailed_chops", None)
            if tailed is None:
                self._axe_tailed_chops = set()
                tailed = self._axe_tailed_chops
            tailed.update(data.tailed_chop_keys)
        else:
            merged_bgcmd = dict(getattr(self, "_axe_bgcmd_details", {}))
            for slot, snap in data.bgcmd_details.items():
                if slot not in visible_bgcmd_slots:
                    continue
                existing = merged_bgcmd.get(slot)
                if existing is not None and not snap.output_tail:
                    snap.output_tail = existing.output_tail
                    if snap.info is None:
                        snap.info = existing.info
                merged_bgcmd[slot] = snap
            self._axe_bgcmd_details = {
                slot: snap
                for slot, snap in merged_bgcmd.items()
                if slot in visible_bgcmd_slots
            }
            for name, jack in getattr(self, "_axe_lumberjack_snapshots", {}).items():
                if name in data.lumberjack_statuses:
                    jack.status = data.lumberjack_statuses[name]
                if name in data.lumberjack_metrics:
                    jack.metrics = data.lumberjack_metrics[name]
            if data.service_log_tails:
                merged_service_tails = dict(getattr(self, "_service_log_tails", {}))
                merged_service_tails.update(data.service_log_tails)
                self._service_log_tails = merged_service_tails
            if data.tailed_service_names:
                tailed_service = getattr(self, "_service_tailed_names", None)
                if tailed_service is None:
                    self._service_tailed_names = set()
                    tailed_service = self._service_tailed_names
                tailed_service.update(data.tailed_service_names)

        self._update_bgcmd_count()
        self._build_axe_items()

        # A launch just landed: home the Services view on its new oneshot.
        focus_slot = self._bgcmd_focus_slot
        if focus_slot is not None and focus_slot in visible_bgcmd_slots:
            self._bgcmd_focus_slot = None
            self._switch_to_axe_view(focus_slot)  # type: ignore[attr-defined]

        # Update display if on axe tab
        if self.current_tab == "services":
            self._refresh_axe_display()  # type: ignore[attr-defined]

        # Update keybinding footer for all tabs (X binding changes label)
        self._update_axe_keybinding()  # type: ignore[attr-defined]

    def _bgcmd_slot_visible(self, slot: int, info: BackgroundCommandInfo) -> bool:
        """Whether a read command is still shown (not mid-dismissal)."""
        return bgcmd_identity(slot, info) not in self._bgcmd_dismissed

    def _settle_bgcmd_slots(
        self, slots: list[tuple[int, BackgroundCommandInfo]]
    ) -> list[tuple[int, BackgroundCommandInfo]]:
        """Filter freshly-read slots against in-flight UI-side bookkeeping.

        Drops commands whose dismissal is still being persisted, forgets
        dismissals that persistence has since removed from disk, and releases
        the ``#n`` reservation of every launch whose oneshot row has landed.
        """
        seen = {bgcmd_identity(slot, info) for slot, info in slots}
        self._bgcmd_dismissed &= seen
        visible: list[tuple[int, BackgroundCommandInfo]] = []
        for slot, info in slots:
            if not self._bgcmd_slot_visible(slot, info):
                continue
            visible.append((slot, info))
            if info.running:
                self._bgcmd_pending_slots.pop(slot, None)
        return visible

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


__all__ = ["AxeRefreshCollectMixin"]
