"""Data-loading mixin for the ace axe display.

Handles reading axe/lumberjack/bgcmd state from disk, applying it to the
in-memory caches, and maintaining the derived lists (axe items, bgcmd counts)
that the render layer paints from.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from sase.axe.state import (
    AxeMetrics,
    AxeStatus,
    LumberjackMetrics,
    LumberjackStatus,
    read_lumberjack_log_tail,
    read_lumberjack_metrics,
    read_lumberjack_status,
)

from ...bgcmd import (
    BackgroundCommandInfo,
    get_active_slots,
    get_slot_info,
    is_slot_running,
    mark_slot_finished,
    read_slot_output_tail,
)
from ...widgets.bgcmd_list import (
    AxeItem,
    BgCmdItem,
    ChopItem,
    LumberjackItem,
)
from ._data import (
    AxeCollectedData,
    AxeViewType,
    BgCmdSnapshot,
    ChopSnapshot,
    LumberjackSnapshot,
    TabName,
    collect_axe_status_data,
    collect_chop_snapshot,
)

if TYPE_CHECKING:
    from ...models.fold_state import FoldStateManager
    from ...util.debounce import DetailPanelDebouncer


type AxeItemKey = (
    tuple[Literal["lumberjack"], str]
    | tuple[Literal["chop"], str, str]
    | tuple[Literal["bgcmd"], int]
)


def _axe_item_key(item: AxeItem) -> AxeItemKey:
    """Return the stable identity key for an AXE side-panel item."""
    match item:
        case LumberjackItem(name=name):
            return ("lumberjack", name)
        case ChopItem(lumberjack_name=lj_name, chop_name=chop_name):
            return ("chop", lj_name, chop_name)
        case BgCmdItem(slot=slot):
            return ("bgcmd", slot)


def find_axe_item_idx(items: list[AxeItem], key: AxeItemKey | None) -> int | None:
    """Find the row index for an AXE item identity key."""
    if key is None:
        return None
    for idx, item in enumerate(items):
        if _axe_item_key(item) == key:
            return idx
    return None


def selected_axe_item_key(items: list[AxeItem], current_idx: int) -> AxeItemKey | None:
    """Return the selected AXE item identity key, if the row is valid."""
    if 0 <= current_idx < len(items):
        return _axe_item_key(items[current_idx])
    return None


class AxeDisplayLoadersMixin:
    """Mixin providing axe data loading and item-list building."""

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
    _axe_last_idx: int
    _axe_last_item_key: AxeItemKey | None
    _axe_fold_manager: FoldStateManager
    # Caches populated by the async collector so navigation paints without I/O.
    _axe_lumberjack_statuses: dict[str, LumberjackStatus | None]
    _axe_lumberjack_metrics: dict[str, LumberjackMetrics | None]
    _axe_lumberjack_log_tails: dict[str, str]
    _axe_bgcmd_details: dict[int, BgCmdSnapshot]
    # Configured chops per lumberjack, in axe-config order, so the
    # sidebar can paint chop child rows without re-parsing the config.
    _axe_lumberjack_chop_names: dict[str, list[str]]
    # Per-chop snapshot (config metadata + bounded run history with
    # output tails). Keyed by (lumberjack_name, chop_name).
    _axe_chop_snapshots: dict[tuple[str, str], ChopSnapshot]
    # Composite per-lumberjack snapshot (status + metrics + log tail +
    # configured chops). Mirrors the per-attribute caches above for
    # callers that prefer a single object.
    _axe_lumberjack_snapshots: dict[str, LumberjackSnapshot]
    # Debouncer for axe detail-panel refresh on j/k navigation.
    _axe_detail_debouncer: DetailPanelDebouncer
    _axe_loading_placeholder_shown: bool
    _bang_mode_active: bool
    _entry_jump_mode_active: bool
    _entry_jump_index_to_hint: dict[int, str]
    # Startup loading indicator flag: flipped to True once the first async
    # axe-status load completes; remains True forever afterward.
    _axe_first_load_done: bool

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
                return collect_chop_snapshot(lj_name, chop_name, description)

            snap = await asyncio.to_thread(_read_chop)
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
            self._axe_bgcmd_details[slot] = BgCmdSnapshot(
                info=info, running=running, output_tail=tail
            )
            if self.current_tab == "axe":
                self._refresh_axe_display()  # type: ignore[attr-defined]

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
        from ...widgets import KeybindingFooter

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

    def _build_axe_items(self) -> None:
        """Build the flat list of AXE side-panel items based on fold and hidden state."""
        from ...models.fold_state import FoldLevel
        from ...util.selection import restore_selection_by_identity

        on_axe_tab = self.current_tab == "axe"

        # Capture identity *before* mutating ``_axe_items`` so off-tab
        # rebuilds (e.g. axe daemon push while the user is on Agents)
        # still preserve the saved-key for when the user returns. When
        # on-tab, the live cursor wins; when off-tab, fall back to the
        # last-saved key so we don't lose it across tab switches.
        if on_axe_tab:
            selected_key = selected_axe_item_key(self._axe_items, self.current_idx)
            prior_visual_row: int | None = self.current_idx
        else:
            selected_key = self._axe_last_item_key
            prior_visual_row = self._axe_last_idx

        items: list[AxeItem] = []

        # Top-level lumberjacks, each followed by its configured chops
        # when its per-lumberjack fold is expanded. First-time sightings
        # default to expanded so chops are visible without an extra keystroke.
        for lumberjack_name in self._axe_lumberjack_names:
            items.append(LumberjackItem(name=lumberjack_name))
            fold_key = f"lumberjack:{lumberjack_name}"
            if not self._axe_fold_manager.has(fold_key):
                self._axe_fold_manager.expand(fold_key)
            if self._axe_fold_manager.get(fold_key) != FoldLevel.COLLAPSED:
                for chop_name in self._axe_lumberjack_chop_names.get(
                    lumberjack_name, []
                ):
                    items.append(
                        ChopItem(lumberjack_name=lumberjack_name, chop_name=chop_name)
                    )

        # Add bgcmd entries when not hidden, visually separated below the
        # lumberjack tree.
        if not self._axe_cmds_hidden:
            for slot, _ in sorted(self._bgcmd_slots, key=lambda x: x[0]):
                items.append(BgCmdItem(slot=slot))

        self._axe_items = items

        restored_idx = restore_selection_by_identity(
            items,
            prior_identity=selected_key,
            prior_visual_row=prior_visual_row,
            identity_fn=_axe_item_key,
        )

        if on_axe_tab:
            self.current_idx = restored_idx

        # Always update the tab-saved position/key so a later tab switch
        # back to AXE lands on the same logical entry. Off-tab rebuilds
        # never touch ``current_idx`` (it belongs to whatever tab is active).
        self._axe_last_idx = restored_idx
        self._axe_last_item_key = selected_axe_item_key(items, restored_idx)

    def _derive_axe_view_from_selection(self) -> None:
        """Derive _axe_current_view and _axe_lumberjack_idx from selected item."""
        if not self._axe_items or self.current_idx >= len(self._axe_items):
            self._axe_current_view = "axe"
            self._axe_lumberjack_idx = None
            return

        item = self._axe_items[self.current_idx]
        match item:
            case LumberjackItem(name=name):
                self._axe_current_view = "axe"
                try:
                    self._axe_lumberjack_idx = self._axe_lumberjack_names.index(name)
                except ValueError:
                    self._axe_lumberjack_idx = None
            case ChopItem(lumberjack_name=lj_name):
                # Phase 4 will introduce a dedicated chop-detail view. For
                # Phase 2/3 the chop's parent lumberjack supplies the
                # cached context that the dashboard needs to render.
                self._axe_current_view = "axe"
                try:
                    self._axe_lumberjack_idx = self._axe_lumberjack_names.index(lj_name)
                except ValueError:
                    self._axe_lumberjack_idx = None
            case BgCmdItem(slot=slot):
                self._axe_current_view = slot
                self._axe_lumberjack_idx = None
