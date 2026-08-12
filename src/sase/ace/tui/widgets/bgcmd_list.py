"""Background command list widget for the ace TUI.

Renders the AXE-tab left sidebar as an operational tree of lumberjacks
and their chops, with user/background commands grouped visually below.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from rich.text import Text
from textual.message import Message
from textual.widgets import OptionList
from textual.widgets.option_list import Option

from ..bgcmd import BackgroundCommandInfo, is_slot_running
from ._axe_dashboard_render import overrun_chip as _overrun_chip

if TYPE_CHECKING:
    from ..actions.axe_display._data import ChopSnapshot
    from sase.axe.state import LumberjackStatus

# Item type: "axe" or slot number (1-9)
ItemType = Literal["axe"] | int


# --- AXE side-panel item types ---


@dataclass(frozen=True)
class LumberjackItem:
    """A top-level lumberjack entry."""

    name: str


@dataclass(frozen=True)
class ChopItem:
    """A chop child entry under a lumberjack."""

    lumberjack_name: str
    chop_name: str


@dataclass(frozen=True)
class BgCmdItem:
    """A background command entry."""

    slot: int


AxeItem = LumberjackItem | ChopItem | BgCmdItem


# --- Row taxonomy palette ----------------------------------------------
#
# Each row family gets its own dominant hue so the three categories are
# distinguishable at a glance even before reading the label text.
#
# - Lumberjacks: gold accent + bold name (top-level).
# - Chops:      dimmer copper/amber, subordinate to the parent lumberjack.
# - Bgcmds:     teal/cyan badge, clearly distinct from the AXE palette.

_LJ_ACCENT_STYLE = "bold #FFD700"
_LJ_NAME_STYLE = "#FFD700"
_LJ_NAME_SELECTED_STYLE = "bold #FFD700"

_CHOP_TREE_STYLE = "dim #FFD700"
_CHOP_NAME_STYLE = "#D7AF87"
_CHOP_NAME_SELECTED_STYLE = "bold #FFD700"

_BGCMD_BADGE_STYLE = "bold #5FD7FF"
_BGCMD_NAME_RUN_STYLE = "#5FD7FF"
_BGCMD_NAME_RUN_SELECTED_STYLE = "bold #5FD7FF"
_BGCMD_NAME_DONE_STYLE = "#87AFAF"
_BGCMD_NAME_DONE_SELECTED_STYLE = "bold #87AFAF"

_DIVIDER_STYLE = "dim #5FD7FF"
_DIVIDER_LABEL = "── commands ──"


class BgCmdList(OptionList):
    """Left sidebar showing list of AXE tab items (axe parent, lumberjacks, bgcmds)."""

    # Cells reserved for border (2), inner padding (2), scrollbar gutter (1),
    # selected-row thick border-left (2), and a small visual comfort margin
    # so the longest formatted row never butts up against the right edge.
    _WIDTH_PADDING: int = 8

    class SelectionChanged(Message):
        """Message sent when selection changes."""

        def __init__(self, index: int) -> None:
            self.index = index
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

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the background command list."""
        super().__init__(**kwargs)
        self._item_count: int = 0
        self._programmatic_update: bool = False
        self._target_width: int = 0
        self._requested_width: int = 0

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
    ) -> None:
        """Update the list with current AXE items.

        Args:
            items: Flat list of AxeItem entries to display.
            current_idx: Index of currently selected item.
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
        """
        del axe_running, lumberjack_names  # accepted for callers; not rendered
        self._programmatic_update = True
        self._item_count = len(items)

        self.clear_options()

        has_axe_rows = any(isinstance(i, (LumberjackItem, ChopItem)) for i in items)
        has_bgcmds = any(isinstance(i, BgCmdItem) for i in items)
        # Spacer divider gets rendered on the first bgcmd row when the
        # sidebar contains both lumberjack/chop rows and bgcmd rows, so
        # the user/background commands group is visually separated from
        # the AXE-managed tree above.
        show_bgcmd_divider = has_axe_rows and has_bgcmds
        bgcmd_seen = False

        max_cell_len = 0
        for idx, item in enumerate(items):
            is_selected = idx == current_idx
            hint_char = (jump_hints or {}).get(idx)
            match item:
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
                    option = self._format_lumberjack_option(
                        name=name,
                        status=lumberjack_status,
                        is_selected=is_selected,
                        hint_char=hint_char,
                        overrun_count=overrun_count,
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
                        running = is_slot_running(slot)
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
        optimal_width = max_cell_len + self._WIDTH_PADDING
        self._requested_width = optimal_width
        self.post_message(self.WidthChanged(optimal_width))

        # Highlight the current item
        try:
            if 0 <= current_idx < len(items):
                self.highlighted = current_idx
            else:
                self.highlighted = 0
        finally:
            self._programmatic_update = False

    def _format_lumberjack_option(
        self,
        name: str,
        status: Any,
        is_selected: bool,
        hint_char: str | None = None,
        overrun_count: int = 0,
    ) -> Option:
        """Format a top-level lumberjack option for display."""
        text = Text(no_wrap=True, overflow="ellipsis")
        if hint_char is not None:
            text.append(f"[{hint_char}] ", style="bold #FFFF00")

        # Strong top-level marker: a solid left accent bar in the
        # lumberjack hue, immediately followed by the status/cycle
        # affordance. The bar character is the visual cue that this row
        # is a top-level section (chops indent under it).
        text.append("▌ ", style=_LJ_ACCENT_STYLE)

        # Status indicator
        if status and status.status == "running":
            text.append("[", style="dim")
            text.append("*", style="bold green")
            text.append("] ", style="dim")
        elif status and status.status == "error":
            text.append("[", style="dim")
            text.append("!", style="bold red")
            text.append("] ", style="dim")
        else:
            text.append("[", style="dim")
            text.append("·", style="dim")
            text.append("] ", style="dim")

        # Name
        label_style = _LJ_NAME_SELECTED_STYLE if is_selected else _LJ_NAME_STYLE
        text.append(name, style=label_style)

        # Overrun roll-up chip: counts only chops at level "over" so a
        # collapsed fold still tells the operator something under this
        # lumberjack needs attention. Placed before the cycles/errors chip
        # per the design's ordering.
        if overrun_count > 0:
            text.append("  ")
            text.append(f"⚠{overrun_count}", style="bold #FFAF5F")

        # Optional compact status chip: cycles run / errors when known.
        # Keeps the row a single line — the chip is appended at the end
        # so long names still get the ellipsis treatment before the chip
        # would be reached.
        chip = _lumberjack_status_chip(status)
        if chip is not None:
            text.append("  ")
            chip_label, chip_style = chip
            text.append(chip_label, style=chip_style)

        return Option(text, id=f"lumberjack-{name}")

    def _format_chop_option(
        self,
        lumberjack_name: str,
        chop_name: str,
        snapshot: "ChopSnapshot | None",
        is_selected: bool,
        hint_char: str | None = None,
    ) -> Option:
        """Format a chop child option for display."""
        text = Text(no_wrap=True, overflow="ellipsis")
        if hint_char is not None:
            text.append(f"[{hint_char}] ", style="bold #FFFF00")

        # Tree connector — visually subordinates the chop to its parent
        # lumberjack. The connector and indentation use the dim-gold
        # taxonomy hue so the relationship reads at a glance.
        text.append("  └─ ", style=_CHOP_TREE_STYLE)

        runs = snapshot.runs if snapshot is not None else []
        if runs:
            latest = runs[0].entry.status
            if latest == "running":
                marker = ("[", "●", "] ", "bold green")
            elif latest == "success":
                marker = ("[", "✓", "] ", "bold green")
            elif latest in ("failure", "timeout"):
                marker = ("[", "!", "] ", "bold red")
            elif latest == "missing_script":
                marker = ("[", "?", "] ", "bold yellow")
            else:
                marker = ("[", "*", "] ", "bold #00D7AF")
        else:
            marker = ("[", "·", "] ", "dim")
        text.append(marker[0], style="dim")
        text.append(marker[1], style=marker[3])
        text.append(marker[2], style="dim")

        label_style = _CHOP_NAME_SELECTED_STYLE if is_selected else _CHOP_NAME_STYLE
        text.append(chop_name, style=label_style)
        if snapshot is not None and not snapshot.enabled:
            text.append("  disabled", style="dim #AFAF87")
        elif snapshot is not None and snapshot.generated:
            text.append("  instance", style="dim #B87333")

        # Overrun chip — the chop's worst sampled ratio in the cached
        # window, so a collapsed-then-expanded tree tells the same story
        # every time. Disabled chops never run, so they never get one.
        if snapshot is not None and snapshot.enabled:
            chip = _overrun_chip(snapshot.overrun)
            if chip is not None:
                chip_label, chip_style = chip
                text.append("  ")
                text.append(chip_label, style=chip_style)

        return Option(text, id=f"chop-{lumberjack_name}-{chop_name}")

    def _format_bgcmd_option(
        self,
        slot: int,
        info: BackgroundCommandInfo | None,
        is_selected: bool,
        is_running: bool,
        hint_char: str | None = None,
        show_divider: bool = False,
    ) -> Option:
        """Format a background command option for display.

        When ``show_divider`` is True a one-line dim separator label is
        prepended above the row so the user/background commands group is
        visually separated from the lumberjack tree above. The divider
        line participates in the option's height but does not contribute
        to the requested sidebar width.
        """
        text = Text(no_wrap=True, overflow="ellipsis")
        if show_divider:
            text.append(_DIVIDER_LABEL, style=_DIVIDER_STYLE)
            text.append("\n")
        if hint_char is not None:
            text.append(f"[{hint_char}] ", style="bold #FFFF00")

        # Slot badge: a clearly-labelled "#N" prefix in the bgcmd hue so
        # user/background commands cannot be mistaken for AXE-managed
        # lumberjack or chop rows.
        text.append(f"#{slot} ", style=_BGCMD_BADGE_STYLE)

        # Status indicator: running (*) vs done (✓)
        text.append("[", style="dim")
        if is_running:
            text.append("*", style="bold #00D7AF")
        else:
            text.append("✓", style="bold #FFD700")
        text.append("] ", style="dim")

        cmd_display = info.command if info else f"slot {slot}"
        if is_running:
            label_style = (
                _BGCMD_NAME_RUN_SELECTED_STYLE if is_selected else _BGCMD_NAME_RUN_STYLE
            )
        else:
            label_style = (
                _BGCMD_NAME_DONE_SELECTED_STYLE
                if is_selected
                else _BGCMD_NAME_DONE_STYLE
            )
        text.append(cmd_display, style=label_style)

        return Option(text, id=str(slot))

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
        if self._programmatic_update:
            return
        if (
            event.option_index is not None
            and 0 <= event.option_index < self._item_count
        ):
            self.post_message(self.SelectionChanged(event.option_index))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle option selection (mouse click or Enter)."""
        if (
            event.option_index is not None
            and 0 <= event.option_index < self._item_count
        ):
            self.post_message(self.SelectionChanged(event.option_index))


def _lumberjack_status_chip(status: Any) -> tuple[str, str] | None:
    """Return a compact (label, style) chip for a lumberjack status, or None."""
    if status is None:
        return None
    errors = getattr(status, "errors_encountered", 0) or 0
    cycles = getattr(status, "cycles_run", 0) or 0
    if errors > 0:
        return (f"{errors}e", "bold red")
    if cycles > 0:
        return (f"{cycles}c", "dim")
    return None


def _last_line_cell_len(text: Text) -> int:
    """Return the cell length of the last line of ``text``.

    Rich's ``Text.cell_len`` totals all lines, which makes it the wrong
    metric for width sizing of options whose prompts contain a leading
    decorative divider line. We size on the data line only so the
    divider can never inflate the requested panel width.
    """
    plain = text.plain
    if "\n" not in plain:
        return text.cell_len
    last = plain.rsplit("\n", 1)[1]
    return Text(last).cell_len
