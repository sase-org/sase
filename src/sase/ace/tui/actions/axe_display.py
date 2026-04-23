"""Axe display and state management mixin for the ace TUI app."""

from __future__ import annotations

import dataclasses
import types
from typing import TYPE_CHECKING, Any, Literal

from sase.axe.state import (
    AxeMetrics,
    AxeStatus,
    LumberjackMetrics,
    LumberjackStatus,
    read_lumberjack_log_tail,
    read_lumberjack_metrics,
    read_lumberjack_status,
    read_metrics,
    read_output_log_tail,
)

from ..bgcmd import (
    BackgroundCommandInfo,
    get_active_slots,
    get_slot_info,
    is_slot_running,
    mark_slot_finished,
    read_slot_output_tail,
)
from ..widgets.bgcmd_list import AxeItem, AxeParentItem, BgCmdItem, LumberjackItem

if TYPE_CHECKING:
    from ..models.fold_state import FoldStateManager

# Type alias for tab names
TabName = Literal["changespecs", "agents", "axe"]

# Type alias for axe view: "axe" for daemon view, int for bgcmd slot (1-9)
AxeViewType = Literal["axe"] | int


def get_axe_process_module() -> types.ModuleType:
    """Return the axe process module."""
    import importlib

    return importlib.import_module("sase.axe.process")


@dataclasses.dataclass
class BgCmdSnapshot:
    """Snapshot of a single background command slot."""

    info: BackgroundCommandInfo | None
    running: bool
    output_tail: str


@dataclasses.dataclass
class _AxeCollectedData:
    """Data collected from disk I/O for axe status."""

    axe_running: bool
    axe_status: AxeStatus | None
    axe_metrics: AxeMetrics | None
    axe_output: str
    lumberjack_names: list[str]
    bgcmd_slots: list[tuple[int, BackgroundCommandInfo]]
    lumberjack_statuses: dict[str, LumberjackStatus | None]
    lumberjack_metrics: dict[str, LumberjackMetrics | None]
    lumberjack_log_tails: dict[str, str]
    bgcmd_details: dict[int, BgCmdSnapshot]


def _collect_axe_status_data() -> _AxeCollectedData:
    """Collect axe status data via disk I/O (thread-safe, no app state mutation).

    Returns:
        Collected axe status data ready to be applied to the app.
    """
    proc = get_axe_process_module()
    axe_running = proc.is_axe_running()

    axe_status: AxeStatus | None = None
    axe_metrics: AxeMetrics | None = None
    if axe_running:
        status_dict = proc.get_axe_status()
        if status_dict:
            try:
                axe_fields = {f.name for f in dataclasses.fields(AxeStatus)}
                filtered = {k: v for k, v in status_dict.items() if k in axe_fields}
                axe_status = AxeStatus(**filtered)
            except TypeError:
                pass
        axe_metrics = read_metrics()

    axe_output = read_output_log_tail(500)

    # Load lumberjack names from config
    from sase.axe.config import load_axe_config as load_new_axe_config

    config = load_new_axe_config()
    lumberjack_names = sorted(config.lumberjacks.keys())

    # Load per-lumberjack status/metrics/log-tail off the event loop so
    # navigation can paint from the cache instead of hitting disk per keypress.
    lumberjack_statuses: dict[str, LumberjackStatus | None] = {}
    lumberjack_metrics: dict[str, LumberjackMetrics | None] = {}
    lumberjack_log_tails: dict[str, str] = {}
    for name in lumberjack_names:
        lumberjack_statuses[name] = read_lumberjack_status(name)
        lumberjack_metrics[name] = read_lumberjack_metrics(name)
        lumberjack_log_tails[name] = read_lumberjack_log_tail(name, 500)

    # Load bgcmd state
    active_slots = get_active_slots()
    bgcmd_slots: list[tuple[int, BackgroundCommandInfo]] = []
    bgcmd_details: dict[int, BgCmdSnapshot] = {}
    for slot in active_slots:
        info = get_slot_info(slot)
        if info is not None:
            running = is_slot_running(slot)
            if not running and info.finished_at is None:
                mark_slot_finished(slot)
                info = get_slot_info(slot)
            if info is not None:
                bgcmd_slots.append((slot, info))
                bgcmd_details[slot] = BgCmdSnapshot(
                    info=info,
                    running=running,
                    output_tail=read_slot_output_tail(slot, 500),
                )

    return _AxeCollectedData(
        axe_running=axe_running,
        axe_status=axe_status,
        axe_metrics=axe_metrics,
        axe_output=axe_output,
        lumberjack_names=lumberjack_names,
        bgcmd_slots=bgcmd_slots,
        lumberjack_statuses=lumberjack_statuses,
        lumberjack_metrics=lumberjack_metrics,
        lumberjack_log_tails=lumberjack_log_tails,
        bgcmd_details=bgcmd_details,
    )


class AxeDisplayMixin:
    """Mixin providing axe display refresh and state loading."""

    # Type hints for attributes accessed from AceApp
    current_tab: TabName
    current_idx: int
    refresh_interval: int
    axe_running: bool
    _countdown_remaining: int
    _axe_status: AxeStatus | None
    _axe_metrics: AxeMetrics | None
    _axe_output: str
    _axe_pinned_to_bottom: bool
    _axe_cmds_hidden: bool
    _axe_current_view: AxeViewType
    _bgcmd_slots: list[tuple[int, BackgroundCommandInfo]]
    _axe_lumberjack_names: list[str]
    _axe_lumberjack_idx: int | None
    _axe_items: list[AxeItem]
    _axe_fold_manager: FoldStateManager
    # Caches populated by the async collector so navigation paints without I/O.
    _axe_lumberjack_statuses: dict[str, LumberjackStatus | None]
    _axe_lumberjack_metrics: dict[str, LumberjackMetrics | None]
    _axe_lumberjack_log_tails: dict[str, str]
    _axe_bgcmd_details: dict[int, BgCmdSnapshot]
    # Timer for debounced axe detail-panel refresh on j/k navigation.
    _axe_detail_update_timer: Any  # Timer | None
    _axe_loading_placeholder_shown: bool
    _bang_mode_active: bool
    _entry_jump_mode_active: bool
    _entry_jump_index_to_hint: dict[int, str]
    # Startup loading indicator flag: flipped to True once the first async
    # axe-status load completes; remains True forever afterward.
    _axe_first_load_done: bool

    def _load_axe_status(self) -> None:
        """Load axe status from disk and update display."""
        data = _collect_axe_status_data()
        self._apply_axe_status_data(data)

    def _apply_axe_status_data(self, data: _AxeCollectedData) -> None:
        """Apply collected axe status data to app state and refresh widgets."""
        # Clear startup loading indicators on the first completed axe load.
        if not self._axe_first_load_done:
            self._axe_first_load_done = True
            from ..widgets import AxeDashboard, AxeInfoPanel

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
            # Notify the startup splash (if still visible).
            notify = getattr(self, "_notify_splash", None)
            if notify is not None:
                notify("axe")

        self.axe_running = data.axe_running

        # Clear starting/restarting state once confirmed running
        if self.axe_running:
            self._set_axe_starting(False)
            self._set_axe_restarting(False)

        # Clear stopping state once confirmed stopped
        if not self.axe_running:
            self._set_axe_stopping(False)

        self._axe_status = data.axe_status
        self._axe_metrics = data.axe_metrics
        self._axe_output = data.axe_output

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

        self._update_bgcmd_count()
        self._build_axe_items()

        # Update AXE tab bar count
        self._update_axe_tab_count()

        # Update display if on axe tab
        if self.current_tab == "axe":
            self._refresh_axe_display()

        # Update keybinding footer for all tabs (X binding changes label)
        self._update_axe_keybinding()

    async def _load_axe_status_async(self) -> None:
        """Load axe status with disk I/O in a background thread."""
        import asyncio

        data = await asyncio.to_thread(_collect_axe_status_data)
        self._apply_axe_status_data(data)

    def _schedule_axe_async_refresh(self) -> None:
        """Schedule an async axe status reload without blocking."""
        self.call_later(self._load_axe_status_async)  # type: ignore[attr-defined]

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
            self._axe_lumberjack_statuses[name] = status
            self._axe_lumberjack_metrics[name] = metrics
            self._axe_lumberjack_log_tails[name] = log_tail
            if self.current_tab == "axe":
                self._refresh_axe_display()
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
            self._axe_bgcmd_details[slot] = BgCmdSnapshot(
                info=info, running=running, output_tail=tail
            )
            if self.current_tab == "axe":
                self._refresh_axe_display()

    def _schedule_targeted_axe_refresh(self) -> None:
        """Schedule a targeted refresh of the selected item's on-disk state."""
        self.call_later(self._refresh_selected_axe_item_async)  # type: ignore[attr-defined]

    async def _run_axe_startup_init(self) -> None:
        """Load axe status and trigger startup auto-start/restart off the critical path."""
        await self._load_axe_status_async()
        if self._restart_axe and self.axe_running:  # type: ignore[attr-defined]
            self._restart_axe_daemon()  # type: ignore[attr-defined]
        elif self._auto_start_axe and not self.axe_running:  # type: ignore[attr-defined]
            self._start_axe()  # type: ignore[attr-defined]

    def _load_lumberjack_names(self) -> None:
        """Load lumberjack names from axe config."""
        from sase.axe.config import load_axe_config as load_new_axe_config

        config = load_new_axe_config()
        self._axe_lumberjack_names = sorted(config.lumberjacks.keys())

        # Reset index if it's now out of bounds
        if self._axe_lumberjack_idx is not None and self._axe_lumberjack_idx >= len(
            self._axe_lumberjack_names
        ):
            self._axe_lumberjack_idx = None

    def _load_bgcmd_state(self) -> None:
        """Load background command state from disk (running + done commands)."""
        active_slots = get_active_slots()
        self._bgcmd_slots = []

        for slot in active_slots:
            info = get_slot_info(slot)
            if info is not None:
                # Check if command just finished and mark it
                if not is_slot_running(slot) and info.finished_at is None:
                    mark_slot_finished(slot)
                    info = get_slot_info(slot)  # Reload to get updated info
                if info is not None:
                    self._bgcmd_slots.append((slot, info))

        # Update footer with bgcmd count
        self._update_bgcmd_count()

        # Rebuild axe items list
        self._build_axe_items()

    def _update_bgcmd_count(self) -> None:
        """Update the keybinding footer with bgcmd running/done counts."""
        from ..widgets import KeybindingFooter

        running_count, done_count = self._get_bgcmd_counts()
        try:
            footer = self.query_one("#keybinding-footer", KeybindingFooter)  # type: ignore[attr-defined]
            footer.set_bgcmd_count(running_count, done_count)
        except Exception:
            pass

    def _get_bgcmd_counts(self) -> tuple[int, int]:
        """Get running and done counts for background commands.

        Returns:
            Tuple of (running_count, done_count).
        """
        running_count = 0
        done_count = 0
        for slot, _ in self._bgcmd_slots:
            if is_slot_running(slot):
                running_count += 1
            else:
                done_count += 1
        return running_count, done_count

    def _update_axe_tab_count(self) -> None:
        """Update the AXE tab bar label with lumberjack and bgcmd counts."""
        from ..widgets import TabBar

        # Count running lumberjacks from the cache populated by the async
        # collector — avoids an extra N round-trip of disk reads on every
        # apply.
        running_lumberjacks = 0
        if self.axe_running:
            for lumberjack_name in self._axe_lumberjack_names:
                lumberjack_status = self._axe_lumberjack_statuses.get(lumberjack_name)
                if lumberjack_status and lumberjack_status.status == "running":
                    running_lumberjacks += 1

        bgcmd_count = len(self._bgcmd_slots)
        _, done_bgcmds = self._get_bgcmd_counts()

        try:
            tab_bar = self.query_one("#tab-bar", TabBar)  # type: ignore[attr-defined]
            tab_bar.update_axe_count(
                running_lumberjacks,
                bgcmd_count,
                show_hidden=not self._axe_cmds_hidden,
                done_count=done_bgcmds,
            )
        except Exception:
            pass

    def _build_axe_items(self) -> None:
        """Build the flat list of AXE side-panel items based on fold and hidden state."""
        from ..models.fold_state import FoldLevel

        items: list[AxeItem] = [AxeParentItem()]

        # Add lumberjack children when expanded
        if self._axe_fold_manager.get("axe") != FoldLevel.COLLAPSED:
            for lumberjack_name in self._axe_lumberjack_names:
                items.append(LumberjackItem(name=lumberjack_name))

        # Add bgcmd entries when not hidden
        if not self._axe_cmds_hidden:
            for slot, _ in sorted(self._bgcmd_slots, key=lambda x: x[0]):
                items.append(BgCmdItem(slot=slot))

        self._axe_items = items

        # Clamp current_idx if it's out of bounds for the new items list
        if self.current_tab == "axe" and self.current_idx >= len(items):
            self.current_idx = 0

    def _derive_axe_view_from_selection(self) -> None:
        """Derive _axe_current_view and _axe_lumberjack_idx from selected item."""
        if not self._axe_items or self.current_idx >= len(self._axe_items):
            self._axe_current_view = "axe"
            self._axe_lumberjack_idx = None
            return

        item = self._axe_items[self.current_idx]
        match item:
            case AxeParentItem():
                self._axe_current_view = "axe"
                self._axe_lumberjack_idx = None
            case LumberjackItem(name=name):
                self._axe_current_view = "axe"
                try:
                    self._axe_lumberjack_idx = self._axe_lumberjack_names.index(name)
                except ValueError:
                    self._axe_lumberjack_idx = None
            case BgCmdItem(slot=slot):
                self._axe_current_view = slot
                self._axe_lumberjack_idx = None

    def _refresh_axe_display_debounced(self) -> None:
        """Debounced refresh for j/k navigation on the axe tab.

        Updates the side-panel highlight and info-panel position counter
        immediately, then schedules the full dashboard/info-panel redraw on
        a 150 ms timer. Rapid bursts of navigation collapse to a single
        final render.
        """
        from ..widgets import BgCmdList

        # Derive the selection so the info panel counter is accurate even
        # before the debounce fires.
        self._derive_axe_view_from_selection()

        try:
            bgcmd_list = self.query_one("#bgcmd-list-panel", BgCmdList)  # type: ignore[attr-defined]
            bgcmd_list.update_highlight(self.current_idx)
        except Exception:
            pass

        # Update position counter on the info panel immediately so the
        # "N/M" indicator keeps up with j/k even if the panel redraw is
        # debounced.
        self._update_axe_info_panel()

        # Cancel any pending debounce timer before scheduling a new one.
        if self._axe_detail_update_timer is not None:
            self._axe_detail_update_timer.stop()

        self._axe_detail_update_timer = self.set_timer(  # type: ignore[attr-defined]
            0.15, self._fire_debounced_axe_refresh
        )

    def _fire_debounced_axe_refresh(self) -> None:
        """Timer callback for the debounced axe refresh."""
        self._axe_detail_update_timer = None
        self._refresh_axe_display()

    def _refresh_axe_display(self) -> None:
        """Refresh the axe dashboard display."""
        from textual.containers import VerticalScroll

        from ..widgets import AxeDashboard, AxeInfoPanel, BgCmdList, KeybindingFooter

        # Derive current view from selected item
        self._derive_axe_view_from_selection()

        try:
            axe_info = self.query_one("#axe-info-panel", AxeInfoPanel)  # type: ignore[attr-defined]
            axe_dashboard = self.query_one("#axe-dashboard", AxeDashboard)  # type: ignore[attr-defined]
            footer = self.query_one("#keybinding-footer", KeybindingFooter)  # type: ignore[attr-defined]

            # Update countdown
            axe_info.update_countdown(self._countdown_remaining, self.refresh_interval)

            # Update info panel based on current view. All reads are from the
            # in-memory cache populated by the async collector; navigation must
            # never hit disk.
            if self._axe_current_view == "axe":
                if self._axe_lumberjack_idx is not None and self._axe_lumberjack_names:
                    # Show lumberjack-specific view
                    lumberjack_name = self._axe_lumberjack_names[
                        self._axe_lumberjack_idx
                    ]
                    lumberjack_output = self._axe_lumberjack_log_tails.get(
                        lumberjack_name, ""
                    )
                    lumberjack_status = self._axe_lumberjack_statuses.get(
                        lumberjack_name
                    )
                    lumberjack_idx = self._axe_lumberjack_idx
                    lumberjack_total = len(self._axe_lumberjack_names)

                    axe_info.update_lumberjack_status(
                        lumberjack_name, lumberjack_idx, lumberjack_total
                    )
                    axe_dashboard.update_lumberjack_display(
                        name=lumberjack_name,
                        idx=lumberjack_idx,
                        total=lumberjack_total,
                        status=lumberjack_status,
                        output=lumberjack_output,
                        countdown=self._countdown_remaining,
                    )
                else:
                    # Show main axe page with lumberjack activity summary
                    axe_info.update_status(self.axe_running)

                    # Get full cycles from metrics if available
                    full_cycles = 0
                    if self._axe_metrics:
                        full_cycles = self._axe_metrics.full_cycles_run

                    # Gather lumberjack summaries from the cache
                    lumberjack_summaries: list[
                        tuple[str, LumberjackStatus | None, int]
                    ] = []
                    for lumberjack_name in self._axe_lumberjack_names:
                        lumberjack_status = self._axe_lumberjack_statuses.get(
                            lumberjack_name
                        )
                        lumberjack_metrics_entry = self._axe_lumberjack_metrics.get(
                            lumberjack_name
                        )
                        chops_executed = (
                            lumberjack_metrics_entry.chops_executed
                            if lumberjack_metrics_entry
                            else 0
                        )
                        lumberjack_summaries.append(
                            (lumberjack_name, lumberjack_status, chops_executed)
                        )

                    axe_dashboard.update_display(
                        is_running=self.axe_running,
                        status=self._axe_status,
                        output=self._axe_output,
                        full_cycles=full_cycles,
                        countdown=self._countdown_remaining,
                        lumberjack_summaries=lumberjack_summaries,
                    )
            else:
                # Showing a bgcmd view — paint from cache when available. On a
                # cold miss we fall back to the quick non-I/O reads (info +
                # running) so the header still renders; the log panel shows an
                # empty string until the async collector lands.
                slot = self._axe_current_view
                snapshot = self._axe_bgcmd_details.get(slot)
                if snapshot is not None:
                    info = snapshot.info
                    running = snapshot.running
                    output = snapshot.output_tail
                else:
                    info = get_slot_info(slot)
                    running = is_slot_running(slot)
                    output = ""

                axe_info.update_bgcmd_status(slot, info, running)
                axe_dashboard.update_bgcmd_display(
                    info, output, running, self._countdown_remaining
                )

            from ..modals import get_runner_count

            footer.set_axe_running(self.axe_running)
            running_count, done_count = self._get_bgcmd_counts()
            footer.set_bgcmd_count(running_count, done_count)
            footer.set_runner_count(get_runner_count())
            if getattr(self, "_fold_mode_active", False):
                footer.update_fold_bindings()
            elif getattr(self, "_leader_mode_active", False):
                footer.update_leader_bindings(current_tab="axe")
            elif getattr(self, "_bang_mode_active", False):
                footer.update_bang_bindings()
            elif getattr(self, "_copy_mode_active", False):
                footer.update_copy_bindings(self.current_tab)
            elif (cm := getattr(self, "_custom_mode_active", None)) is not None:
                footer.update_custom_mode_bindings(cm)
            else:
                footer.update_axe_bindings(
                    axe_current_view=self._axe_current_view,
                )

            # Always update the side-panel list. Pass cached statuses and
            # running flags so the side-panel render path does no disk I/O.
            try:
                bgcmd_list = self.query_one("#bgcmd-list-panel", BgCmdList)  # type: ignore[attr-defined]
                bgcmd_running_cache = {
                    slot: snap.running for slot, snap in self._axe_bgcmd_details.items()
                }
                bgcmd_list.update_list(
                    items=self._axe_items,
                    current_idx=self.current_idx,
                    axe_running=self.axe_running,
                    lumberjack_names=self._axe_lumberjack_names,
                    bgcmd_infos=dict(self._bgcmd_slots),
                    jump_hints=(
                        self._entry_jump_index_to_hint
                        if self._entry_jump_mode_active
                        else None
                    ),
                    lumberjack_statuses=self._axe_lumberjack_statuses,
                    bgcmd_running=bgcmd_running_cache,
                )
            except Exception:
                pass

            # Auto-scroll to bottom if pinned and on axe view
            if self._axe_pinned_to_bottom and self._axe_current_view == "axe":
                scroll_container = self.query_one("#axe-output-scroll", VerticalScroll)  # type: ignore[attr-defined]
                scroll_container.scroll_end(animate=False)
        except Exception:
            # Widget not found, possibly not on axe tab
            pass

    def _update_axe_info_panel(self) -> None:
        """Update the axe info panel and dashboard status bar with countdown."""
        from ..widgets import AxeDashboard, AxeInfoPanel

        try:
            axe_info = self.query_one("#axe-info-panel", AxeInfoPanel)  # type: ignore[attr-defined]
            if self._axe_current_view == "axe":
                axe_info.update_status(self.axe_running)
            else:
                slot = self._axe_current_view
                snapshot = self._axe_bgcmd_details.get(slot)
                if snapshot is not None:
                    info = snapshot.info
                    running = snapshot.running
                else:
                    info = get_slot_info(slot)
                    running = is_slot_running(slot)
                axe_info.update_bgcmd_status(slot, info, running)
            axe_info.update_countdown(self._countdown_remaining, self.refresh_interval)

            # Also update dashboard status bar countdown
            axe_dashboard = self.query_one("#axe-dashboard", AxeDashboard)  # type: ignore[attr-defined]
            axe_dashboard.update_countdown(self._countdown_remaining)
        except Exception:
            pass

    def _update_axe_keybinding(self) -> None:
        """Update the keybinding footer with current axe state."""
        from ..widgets import KeybindingFooter

        running_count, done_count = self._get_bgcmd_counts()
        try:
            footer = self.query_one("#keybinding-footer", KeybindingFooter)  # type: ignore[attr-defined]
            footer.set_axe_running(self.axe_running)
            footer.set_bgcmd_count(running_count, done_count)
        except Exception:
            pass

    def _set_axe_starting(self, starting: bool) -> None:
        """Set axe starting state and update footer.

        Args:
            starting: Whether axe is currently starting up.
        """
        from ..widgets import KeybindingFooter

        try:
            footer = self.query_one("#keybinding-footer", KeybindingFooter)  # type: ignore[attr-defined]
            footer.set_axe_starting(starting)
        except Exception:
            pass

    def _set_axe_stopping(self, stopping: bool) -> None:
        """Set axe stopping state and update footer.

        Args:
            stopping: Whether axe is currently stopping.
        """
        from ..widgets import KeybindingFooter

        try:
            footer = self.query_one("#keybinding-footer", KeybindingFooter)  # type: ignore[attr-defined]
            footer.set_axe_stopping(stopping)
        except Exception:
            pass

    def _set_axe_restarting(self, restarting: bool) -> None:
        """Set axe restarting state and update footer.

        Args:
            restarting: Whether axe is currently restarting.
        """
        from ..widgets import KeybindingFooter

        try:
            footer = self.query_one("#keybinding-footer", KeybindingFooter)  # type: ignore[attr-defined]
            footer.set_axe_restarting(restarting)
        except Exception:
            pass
