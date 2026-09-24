"""Shared gear-chip rendering for proc and monitor counts.

The blue/orange gear chip is the canonical proc-vs-monitor lane marker for
the Procs tab header and the top bar's single ``procs:`` group
(``ProcIndicator``), which share this chip by construction so a count reads
as the same lane in both places.
"""

from __future__ import annotations

from rich.text import Text

from sase.ace.tui.widgets.top_bar_group import icon_count_chip
from sase.monitor_state import MONITOR_GLYPH, MONITOR_GLYPH_COLOR

PROC_GEAR_HUE = "#48CAE4"
MONITOR_GEAR_HUE = MONITOR_GLYPH_COLOR

_GEAR = MONITOR_GLYPH


def gear_chip(count: int, hue: str, *, hide_at_zero: bool = True) -> Text:
    """Build a gear chip for *count* in *hue*.

    A nonzero count always renders as a filled chip. A zero count either
    disappears (``hide_at_zero=True``, the top-bar ambient-badge behavior)
    or renders as a dim, unfilled chip (``hide_at_zero=False``, used by the
    Procs tab header so a lane always reads "none" rather than "unknown").
    """
    if count <= 0:
        if hide_at_zero:
            return Text("")
        return Text(f" {_GEAR} {count} ", style=f"dim {hue}")
    return icon_count_chip(_GEAR, count, hue)


__all__ = ["MONITOR_GEAR_HUE", "PROC_GEAR_HUE", "gear_chip"]
