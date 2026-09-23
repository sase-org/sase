"""Shared gear-chip rendering for proc and monitor counts.

The blue/orange gear chip is the canonical proc-vs-monitor lane marker for
the Procs tab header, which builds the same chip from the same two hues.
The top bar (``ProcIndicator`` / ``MonitorIndicator``) now renders labeled
``procs: N`` / ``monitors: N`` groups with filled count chips in those hues
(see ``widgets/top_bar_group.filled_count_chip``), so a count reads as the
same lane in both places without the gear glyph.
"""

from __future__ import annotations

from rich.text import Text

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
    return Text(f" {_GEAR} {count} ", style=f"bold #1a1a1a on {hue}")


__all__ = ["MONITOR_GEAR_HUE", "PROC_GEAR_HUE", "gear_chip"]
