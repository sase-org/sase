"""Row formatters for the background command list widget.

Pure ``Text`` builders for lumberjack, service proc, chop, and oneshot
rows. The oneshot clock resolves through the ``bgcmd_list`` namespace
(see ``_bgcmd_list_oneshot``) so the ``get_timezone`` / ``local_now``
patch targets keep working after the split.
"""

from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual.widgets.option_list import Option

from ..bgcmd import BackgroundCommandInfo
from ._axe_dashboard_render import overrun_chip as _overrun_chip
from ._bgcmd_list_chips import (
    lumberjack_status_chip,
    service_proc_chip,
    service_proc_label,
    service_proc_marker,
)
from ._bgcmd_list_oneshot import oneshot_chip, oneshot_glyph
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
    _ONESHOT_NAME_DONE_SELECTED_STYLE,
    _ONESHOT_NAME_DONE_STYLE,
    _ONESHOT_NAME_RUN_SELECTED_STYLE,
    _ONESHOT_NAME_RUN_STYLE,
    _SERVICE_ACCENT_STYLE,
    _SERVICE_DISABLED_STYLE,
    _SERVICE_NAME_SELECTED_STYLE,
    _SERVICE_NAME_STYLE,
)

if TYPE_CHECKING:
    from ..actions.axe_display._data import ChopSnapshot
    from sase.service.status import ServiceStatusProc


def format_lumberjack_option(
    name: str,
    status: Any,
    is_selected: bool,
    hint_char: str | None = None,
    overrun_count: int = 0,
    health_count: int = 0,
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

    # Health roll-up: failed / timed-out / missing-script jobs under this
    # routine, counted from the same cached snapshots as the panel title.
    # Rendered even when the routine's children are folded so a collapsed
    # builtin still reports trouble at the parent row. Zero (or no
    # snapshots yet) renders no badge.
    if health_count > 0:
        text.append("  ")
        text.append(f"!{health_count}", style="bold red")

    # Optional compact status chip: cycles run / errors when known.
    # Keeps the row a single line — the chip is appended at the end
    # so long names still get the ellipsis treatment before the chip
    # would be reached.
    chip = lumberjack_status_chip(status)
    if chip is not None:
        text.append("  ")
        chip_label, chip_style = chip
        text.append(chip_label, style=chip_style)

    return Option(text, id=f"lumberjack-{name}")


def format_service_proc_option(
    name: str,
    proc: "ServiceStatusProc | None",
    is_selected: bool,
    hint_char: str | None = None,
) -> Option:
    """Format a service-host proc row for display."""
    text = Text(no_wrap=True, overflow="ellipsis")
    if hint_char is not None:
        text.append(f"[{hint_char}] ", style="bold #FFFF00")

    text.append("▌ ", style=_SERVICE_ACCENT_STYLE)
    text.append("[", style="dim")
    marker, marker_style = service_proc_marker(proc)
    text.append(marker, style=marker_style)
    text.append("] ", style="dim")

    label = service_proc_label(name)
    if proc is not None and not proc.enablement.enabled:
        label_style = _SERVICE_DISABLED_STYLE
    else:
        label_style = (
            _SERVICE_NAME_SELECTED_STYLE if is_selected else _SERVICE_NAME_STYLE
        )
    text.append(label, style=label_style)

    if proc is not None:
        chip = service_proc_chip(proc)
        if chip is not None:
            chip_label, chip_style = chip
            text.append("  ")
            text.append(chip_label, style=chip_style)

    return Option(text, id=f"service-{name}")


def format_chop_option(
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


def format_bgcmd_option(
    slot: int,
    info: BackgroundCommandInfo | None,
    is_selected: bool,
    is_running: bool,
    hint_char: str | None = None,
    show_divider: bool = False,
) -> Option:
    """Format a oneshot row: ``▷ #1 command  running · 1m``.

    The glyph carries the state (``▷`` running, ``✓`` exit 0, ``✗``
    failed or killed) and a trailing chip carries the recorded exit code
    and age. When ``show_divider`` is True a one-line dim separator label
    is prepended above the row so the oneshots section is visually
    separated from the service/scheduler tree above. The divider line
    participates in the option's height but does not contribute to the
    requested sidebar width.
    """
    text = Text(no_wrap=True, overflow="ellipsis")
    if show_divider:
        text.append(_DIVIDER_LABEL, style=_DIVIDER_STYLE)
        text.append("\n")
    if hint_char is not None:
        text.append(f"[{hint_char}] ", style="bold #FFFF00")

    glyph, glyph_style = oneshot_glyph(info, is_running)
    text.append(f"{glyph} ", style=glyph_style)
    text.append(f"#{slot} ", style=_ONESHOT_BADGE_STYLE)

    cmd_display = info.command if info else f"slot {slot}"
    if is_running:
        label_style = (
            _ONESHOT_NAME_RUN_SELECTED_STYLE if is_selected else _ONESHOT_NAME_RUN_STYLE
        )
    else:
        label_style = (
            _ONESHOT_NAME_DONE_SELECTED_STYLE
            if is_selected
            else _ONESHOT_NAME_DONE_STYLE
        )
    text.append(cmd_display, style=label_style)

    chip = oneshot_chip(info, is_running)
    if chip is not None:
        chip_label, chip_style = chip
        text.append("  ")
        text.append(chip_label, style=chip_style)

    return Option(text, id=str(slot))


def last_line_cell_len(text: Text) -> int:
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


__all__ = [
    "last_line_cell_len",
    "format_bgcmd_option",
    "format_chop_option",
    "format_lumberjack_option",
    "format_service_proc_option",
]
