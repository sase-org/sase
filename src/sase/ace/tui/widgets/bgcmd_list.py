"""Background command list widget for sase's TUI.

Renders the AXE-tab left sidebar as an operational tree of lumberjacks
and their chops, with user/background commands grouped visually below.
Row taxonomy helpers live in ``_bgcmd_list_*``; this module keeps the
widget plus backward-compatible re-exports.
"""

from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual.message import Message
from textual.widgets import OptionList
from textual.widgets.option_list import Option

from sase.core.time import get_timezone, local_now

from ..bgcmd import BackgroundCommandInfo
from ._bgcmd_list_chips import (
    _SERVICE_CHIP_MAX_WIDTH,
    lumberjack_status_chip,
    service_enablement_chip,
    service_proc_chip,
    service_proc_label,
    service_proc_marker,
)
from ._bgcmd_list_items import (
    AxeItem,
    BgCmdItem,
    ChopItem,
    ItemType,
    LumberjackItem,
    ServiceProcItem,
)
from ._bgcmd_list_oneshot import (
    oneshot_age,
    oneshot_chip,
    oneshot_failed,
    oneshot_glyph,
)
from ._bgcmd_list_rows import (
    format_bgcmd_option,
    format_chop_option,
    format_lumberjack_option,
    format_service_proc_option,
    last_line_cell_len,
)
from ._bgcmd_list_styles import (
    _CHOP_NAME_SELECTED_STYLE,
    _CHOP_NAME_STYLE,
    _CHOP_TREE_STYLE,
    _DIVIDER_LABEL,
    _DIVIDER_STYLE,
    _LJ_ACCENT_STYLE,
    _LJ_NAME_SELECTED_STYLE,
    _LJ_NAME_STYLE,
    _ONESHOT_BADGE_STYLE,
    _ONESHOT_DONE_CHIP_STYLE,
    _ONESHOT_FAIL_CHIP_STYLE,
    _ONESHOT_FAIL_GLYPH,
    _ONESHOT_NAME_DONE_SELECTED_STYLE,
    _ONESHOT_NAME_DONE_STYLE,
    _ONESHOT_NAME_RUN_SELECTED_STYLE,
    _ONESHOT_NAME_RUN_STYLE,
    _ONESHOT_OK_CHIP_STYLE,
    _ONESHOT_OK_GLYPH,
    _ONESHOT_RUN_CHIP_STYLE,
    _ONESHOT_RUN_GLYPH,
    _SERVICE_ACCENT_STYLE,
    _SERVICE_DISABLED_STYLE,
    _SERVICE_NAME_SELECTED_STYLE,
    _SERVICE_NAME_STYLE,
    _SERVICE_WARN_STYLE,
)

if TYPE_CHECKING:
    from ..actions.axe_display._data import ChopSnapshot
    from sase.axe.state import LumberjackStatus
    from sase.service.status import ServiceStatusProc

# Private aliases kept for backward compatibility with callers that
# imported these helpers from this module before the split.
_last_line_cell_len = last_line_cell_len
_lumberjack_status_chip = lumberjack_status_chip
_oneshot_age = oneshot_age
_oneshot_chip = oneshot_chip
_oneshot_failed = oneshot_failed
_oneshot_glyph = oneshot_glyph
_service_enablement_chip = service_enablement_chip
_service_proc_chip = service_proc_chip
_service_proc_label = service_proc_label
_service_proc_marker = service_proc_marker

__all__ = [
    "AxeItem",
    "BgCmdItem",
    "BgCmdList",
    "ChopItem",
    "ItemType",
    "LumberjackItem",
    "ServiceProcItem",
    "_CHOP_NAME_SELECTED_STYLE",
    "_CHOP_NAME_STYLE",
    "_CHOP_TREE_STYLE",
    "_DIVIDER_LABEL",
    "_DIVIDER_STYLE",
    "_LJ_ACCENT_STYLE",
    "_LJ_NAME_SELECTED_STYLE",
    "_LJ_NAME_STYLE",
    "_ONESHOT_BADGE_STYLE",
    "_ONESHOT_DONE_CHIP_STYLE",
    "_ONESHOT_FAIL_CHIP_STYLE",
    "_ONESHOT_FAIL_GLYPH",
    "_ONESHOT_NAME_DONE_SELECTED_STYLE",
    "_ONESHOT_NAME_DONE_STYLE",
    "_ONESHOT_NAME_RUN_SELECTED_STYLE",
    "_ONESHOT_NAME_RUN_STYLE",
    "_ONESHOT_OK_CHIP_STYLE",
    "_ONESHOT_OK_GLYPH",
    "_ONESHOT_RUN_CHIP_STYLE",
    "_ONESHOT_RUN_GLYPH",
    "_SERVICE_ACCENT_STYLE",
    "_SERVICE_CHIP_MAX_WIDTH",
    "_SERVICE_DISABLED_STYLE",
    "_SERVICE_NAME_SELECTED_STYLE",
    "_SERVICE_NAME_STYLE",
    "_SERVICE_WARN_STYLE",
    "_last_line_cell_len",
    "_lumberjack_status_chip",
    "_oneshot_age",
    "_oneshot_chip",
    "_oneshot_failed",
    "_oneshot_glyph",
    "_service_enablement_chip",
    "_service_proc_chip",
    "_service_proc_label",
    "_service_proc_marker",
    "format_bgcmd_option",
    "format_chop_option",
    "format_lumberjack_option",
    "format_service_proc_option",
    "get_timezone",
    "local_now",
]


class BgCmdList(OptionList):
    """Left sidebar showing list of AXE tab items (axe parent, lumberjacks, bgcmds)."""

    # Cells reserved for border (2), inner padding (2), scrollbar gutter (1),
    # selected-row thick border-left (2), and a small visual comfort margin
    # so the longest formatted row never butts up against the right edge.
    _WIDTH_PADDING: int = 8

    class SelectionChanged(Message):
        """Message sent when selection changes."""

        def __init__(self, index: int, panel_key: str = "service_procs") -> None:
            self.index = index
            self.panel_key = panel_key
            super().__init__()

    class WidthChanged(Message):
        """Message sent when the natural sidebar width changes.

        The sidebar emits this after :meth:`update_list` so the AXE-tab
        container can resize to fit the widest formatted row (lumberjack,
        chop, or background command) without wrapping.
        """

        def __init__(self, width: int) -> None:
            self.width = width
            super().__init__()

    def __init__(self, panel_key: str = "service_procs", **kwargs: Any) -> None:
        """Initialize the background command list."""
        super().__init__(**kwargs)
        self.panel_key: str = panel_key
        self._item_count: int = 0
        self._programmatic_update: bool = False
        self._target_width: int = 0
        self._content_requested_width: int = 0
        self._requested_width: int = 0
        # Rendered content rows (options plus divider lines; 1 for a
        # placeholder), used by the shared panel-height allocation.
        self.rendered_line_count: int = 0
        self._placeholder_shown: bool = False

    def update_list(
        self,
        items: list[AxeItem],
        current_idx: int,
        axe_running: bool,
        lumberjack_names: list[str],
        bgcmd_infos: dict[int, BackgroundCommandInfo],
        jump_hints: dict[int, str] | None = None,
        lumberjack_statuses: "dict[str, LumberjackStatus | None] | None" = None,
        bgcmd_running: dict[int, bool] | None = None,
        chop_snapshots: "dict[tuple[str, str], ChopSnapshot] | None" = None,
        lumberjack_overruns: dict[str, int] | None = None,
        lumberjack_health: dict[str, int] | None = None,
        service_procs: "dict[str, ServiceStatusProc] | None" = None,
        empty_placeholder: Text | None = None,
    ) -> None:
        """Update the list with current AXE items.

        Args:
            items: Panel-local slice of AxeItem entries to display.
            current_idx: Panel-local index of the selected item, or ``-1``
                for no highlight (the unfocused panel clears via
                :meth:`clear_highlight`).
            axe_running: Whether axe daemon is running.
            lumberjack_names: Configured lumberjack names (ordered).
            bgcmd_infos: Mapping of slot -> info for bgcmds.
            jump_hints: Optional local row index -> adaptive hint mapping.
            lumberjack_statuses: Cached status per lumberjack. If omitted, the
                widget falls back to a synchronous read from disk (old
                behavior — only used by tests / legacy callers).
            bgcmd_running: Cached running flag per slot. If omitted, falls
                back to a synchronous process check.
            chop_snapshots: Cached per-chop snapshots, keyed by
                ``(lumberjack_name, chop_name)``.
            lumberjack_overruns: Cached count of chops at overrun level
                ``"over"``, keyed by lumberjack name. ``None`` or a missing
                key renders no roll-up chip.
            lumberjack_health: Cached count of failed/timed-out/
                missing-script chops per lumberjack (the ``!N`` badge),
                keyed by lumberjack name. ``None`` or a missing key
                renders no badge.
            service_procs: Cached service-proc statuses keyed by name.
            empty_placeholder: Disabled placeholder row rendered when
                ``items`` is empty. It is not a nav item: never selectable,
                never counted, and never emits ``SelectionChanged``.
        """
        del axe_running, lumberjack_names  # accepted for callers; not rendered
        self._programmatic_update = True
        try:
            self._item_count = len(items)
            self._placeholder_shown = not items and empty_placeholder is not None

            self.clear_options()

            if not items:
                if empty_placeholder is not None:
                    self.add_option(Option(empty_placeholder, disabled=True))
                    self.rendered_line_count = 1
                else:
                    self.rendered_line_count = 0
                self.highlighted = None
                self._target_width = 0
                self._content_requested_width = 0
                self._refresh_requested_width()
                return

            has_axe_rows = any(
                isinstance(i, (ServiceProcItem, LumberjackItem, ChopItem))
                for i in items
            )
            has_bgcmds = any(isinstance(i, BgCmdItem) for i in items)
            # Spacer divider gets rendered on the first bgcmd row when the
            # panel holds both daemon rows and oneshot rows, so the
            # user/background commands group is visually separated from the
            # service-proc tree above.
            show_bgcmd_divider = has_axe_rows and has_bgcmds
            bgcmd_seen = False

            max_cell_len = 0
            for idx, item in enumerate(items):
                is_selected = idx == current_idx
                hint_char = (jump_hints or {}).get(idx)
                match item:
                    case ServiceProcItem(name=name):
                        option = self._format_service_proc_option(
                            name=name,
                            proc=None
                            if service_procs is None
                            else service_procs.get(name),
                            is_selected=is_selected,
                            hint_char=hint_char,
                        )
                    case LumberjackItem(name=name):
                        if lumberjack_statuses is not None:
                            lumberjack_status = lumberjack_statuses.get(name)
                        else:
                            from sase.axe.state import read_lumberjack_status

                            lumberjack_status = read_lumberjack_status(name)
                        overrun_count = (
                            lumberjack_overruns.get(name, 0)
                            if lumberjack_overruns is not None
                            else 0
                        )
                        health_count = (
                            lumberjack_health.get(name, 0)
                            if lumberjack_health is not None
                            else 0
                        )
                        option = self._format_lumberjack_option(
                            name=name,
                            status=lumberjack_status,
                            is_selected=is_selected,
                            hint_char=hint_char,
                            overrun_count=overrun_count,
                            health_count=health_count,
                        )
                    case ChopItem(lumberjack_name=lj_name, chop_name=chop_name):
                        snap = (
                            chop_snapshots.get((lj_name, chop_name))
                            if chop_snapshots is not None
                            else None
                        )
                        option = self._format_chop_option(
                            lumberjack_name=lj_name,
                            chop_name=chop_name,
                            snapshot=snap,
                            is_selected=is_selected,
                            hint_char=hint_char,
                        )
                    case BgCmdItem(slot=slot):
                        info = bgcmd_infos.get(slot)
                        if bgcmd_running is not None:
                            running = bgcmd_running.get(slot, False)
                        else:
                            running = info is not None and info.running
                        is_first_bgcmd = show_bgcmd_divider and not bgcmd_seen
                        bgcmd_seen = True
                        option = self._format_bgcmd_option(
                            slot=slot,
                            info=info,
                            is_selected=is_selected,
                            is_running=running,
                            hint_char=hint_char,
                            show_divider=is_first_bgcmd,
                        )
                prompt = option.prompt
                if isinstance(prompt, Text):
                    content_len = _last_line_cell_len(prompt)
                    if content_len > max_cell_len:
                        max_cell_len = content_len
                self.add_option(option)

            self._target_width = max_cell_len
            self._content_requested_width = max_cell_len + self._WIDTH_PADDING
            self.rendered_line_count = len(items) + (1 if show_bgcmd_divider else 0)
            self._refresh_requested_width()

            # Highlight the panel-local item. A negative index means this
            # panel does not hold the selection, so clear the highlight.
            if 0 <= current_idx < len(items):
                self.highlighted = current_idx
            else:
                self.highlighted = None
        finally:
            self._programmatic_update = False

    def update_border_title(self, title: Text) -> None:
        """Set the panel title and include it in width negotiation."""
        self.border_title = title
        self._refresh_requested_width()

    def _refresh_requested_width(self) -> None:
        """Publish the larger of the content and border-title widths.

        Posts ``WidthChanged`` only when the combined requested width
        actually changed, mirroring ``AgentList``.
        """
        title = self.border_title
        title_width = (
            title.cell_len
            if isinstance(title, Text)
            else Text.from_markup(str(title or "")).cell_len
        )
        requested_width = max(self._content_requested_width, title_width + 4)
        if requested_width == self._requested_width:
            return
        self._requested_width = requested_width
        self.post_message(self.WidthChanged(requested_width))

    def clear_highlight(self) -> None:
        """Clear the row highlight without rebuilding options."""
        self._programmatic_update = True
        try:
            self.highlighted = None
        finally:
            self._programmatic_update = False

    def _format_lumberjack_option(
        self,
        name: str,
        status: Any,
        is_selected: bool,
        hint_char: str | None = None,
        overrun_count: int = 0,
        health_count: int = 0,
    ) -> Option:
        """Format a top-level lumberjack option for display."""
        return format_lumberjack_option(
            name=name,
            status=status,
            is_selected=is_selected,
            hint_char=hint_char,
            overrun_count=overrun_count,
            health_count=health_count,
        )

    def _format_service_proc_option(
        self,
        name: str,
        proc: "ServiceStatusProc | None",
        is_selected: bool,
        hint_char: str | None = None,
    ) -> Option:
        """Format a service-host proc row for display."""
        return format_service_proc_option(
            name=name,
            proc=proc,
            is_selected=is_selected,
            hint_char=hint_char,
        )

    def _format_chop_option(
        self,
        lumberjack_name: str,
        chop_name: str,
        snapshot: "ChopSnapshot | None",
        is_selected: bool,
        hint_char: str | None = None,
    ) -> Option:
        """Format a chop child option for display."""
        return format_chop_option(
            lumberjack_name=lumberjack_name,
            chop_name=chop_name,
            snapshot=snapshot,
            is_selected=is_selected,
            hint_char=hint_char,
        )

    def _format_bgcmd_option(
        self,
        slot: int,
        info: BackgroundCommandInfo | None,
        is_selected: bool,
        is_running: bool,
        hint_char: str | None = None,
        show_divider: bool = False,
    ) -> Option:
        """Format a oneshot row: ``▷ #1 command  running · 1m``."""
        return format_bgcmd_option(
            slot=slot,
            info=info,
            is_selected=is_selected,
            is_running=is_running,
            hint_char=hint_char,
            show_divider=show_divider,
        )

    def update_highlight(self, current_idx: int) -> None:
        """Move the highlight without clearing/rebuilding options.

        Use this for j/k navigation where the item list hasn't changed,
        only the selection index.
        """
        if 0 <= current_idx < self._item_count:
            self._programmatic_update = True
            try:
                self.highlighted = current_idx
            finally:
                self._programmatic_update = False

    def watch_highlighted(self, highlighted: int | None) -> None:
        """Suppress OptionHighlighted messages during programmatic updates."""
        from ..util.trace import trace_event

        if self._programmatic_update:
            trace_event(
                "widget.bgcmd_list.watch_highlighted.suppressed",
                highlighted=highlighted,
            )
            return
        trace_event(
            "widget.bgcmd_list.watch_highlighted",
            highlighted=highlighted,
        )
        super().watch_highlighted(highlighted)

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        """Handle option highlight (keyboard navigation)."""
        if self._programmatic_update or self._placeholder_shown:
            return
        if (
            event.option_index is not None
            and 0 <= event.option_index < self._item_count
        ):
            self.post_message(self.SelectionChanged(event.option_index, self.panel_key))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle option selection (mouse click or Enter)."""
        if self._placeholder_shown:
            return
        if (
            event.option_index is not None
            and 0 <= event.option_index < self._item_count
        ):
            self.post_message(self.SelectionChanged(event.option_index, self.panel_key))


# Oneshot helpers live in ``_bgcmd_list_oneshot`` and are re-exported
# above; the clock resolves through this namespace so the
# ``get_timezone`` / ``local_now`` patch targets keep working.
