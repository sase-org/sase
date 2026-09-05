"""Shared state contract for the AXE display loader mixins."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from sase.axe.state import (
        AxeMetrics,
        AxeStatus,
        LumberjackMetrics,
        LumberjackStatus,
    )

    from ...bgcmd import BackgroundCommandInfo
    from ...models.fold_state import FoldStateManager
    from ...util.debounce import DetailPanelDebouncer
    from ...widgets.bgcmd_list import AxeItem
    from ._data import (
        AxeStatusDegradation,
        AxeViewType,
        BgCmdSnapshot,
        ChopSnapshot,
        LumberjackSnapshot,
        TabName,
    )


type AxeItemKey = (
    tuple[Literal["lumberjack"], str]
    | tuple[Literal["chop"], str, str]
    | tuple[Literal["bgcmd"], int]
)


class AxeLoaderState:
    """Attributes shared by the AXE refresh and item-list loaders."""

    current_tab: TabName
    current_idx: int
    refresh_interval: int
    axe_running: bool
    _countdown_remaining: int
    _axe_status: AxeStatus | None
    _axe_metrics: AxeMetrics | None
    _axe_output: str
    _axe_degraded_status: AxeStatusDegradation | None
    _axe_pinned_to_bottom: bool
    _axe_cmds_hidden: bool
    _axe_current_view: AxeViewType
    # When a chop child row is selected, ``_axe_current_view`` stays at
    # ``"axe"`` (since chops are not bgcmd slots) and this sidecar field
    # carries the (lumberjack_name, chop_name) identity that the render
    # layer uses to pick the chop-detail view instead of the lumberjack
    # overview. ``None`` means a lumberjack row (or no row) is selected.
    _axe_chop_selection: tuple[str, str] | None
    _bgcmd_slots: list[tuple[int, BackgroundCommandInfo]]
    _axe_lumberjack_names: list[str]
    _axe_lumberjack_idx: int | None
    _axe_items: list[AxeItem]
    _axe_last_idx: int
    _axe_last_item_key: AxeItemKey | None
    _axe_pending_selection: Any
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
    _axe_status_read_cache: Any
    _axe_tailed_chops: set[tuple[str, str]]
    _axe_status_refresh_want_full: bool
    _axe_status_refresh_want_all_tails: bool
    # Per-chop view offset for Ctrl+N / Ctrl+P run-history navigation.
    _axe_chop_run_offsets: dict[tuple[str, str], int]
    # Debouncer for axe detail-panel refresh on j/k navigation.
    _axe_detail_debouncer: DetailPanelDebouncer
    _axe_loading_placeholder_shown: bool
    _bang_mode_active: bool
    _entry_jump_mode_active: bool
    _entry_jump_index_to_hint: dict[int, str]
    # Startup loading indicator flag: flipped to True once the first async
    # axe-status load completes; remains True forever afterward.
    _axe_first_load_done: bool
    _axe_status_refresh_scheduled: bool
    _axe_status_refresh_running: bool
    _axe_status_refresh_pending: bool
    _axe_targeted_refresh_scheduled: bool
    _axe_targeted_refresh_running: bool
    _axe_targeted_refresh_pending: bool
