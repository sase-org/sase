"""Shared gear-chip rendering for proc and monitor counts.

The gear chip now has three lanes. Blue is the session proc lane, orange
is monitors, and green (the update identity accent) is procs that are
updating SASE. The updates badge inset renders one of three gears
(``updating`` lime, ``restart_pending`` yellow, ``failed`` red) in the
same slot with the same width and dark ink.
"""

from __future__ import annotations

from rich.text import Text

from sase.ace.tui.update_gear import UpdateGearState
from sase.ace.tui.widgets.top_bar_group import icon_count_chip
from sase.ace.tui.widgets.update_accents import (
    UPDATES_ACCENT,
    UPDATE_FAILED_ACCENT,
    UPDATE_RESTART_ACCENT,
)
from sase.monitor_state import MONITOR_GLYPH, MONITOR_GLYPH_COLOR

PROC_GEAR_HUE = "#48CAE4"
MONITOR_GEAR_HUE = MONITOR_GLYPH_COLOR
UPDATE_GEAR_HUE = UPDATES_ACCENT

UPDATE_GEAR_HUES: dict[UpdateGearState, str] = {
    "updating": UPDATES_ACCENT,
    "restart_pending": UPDATE_RESTART_ACCENT,
    "failed": UPDATE_FAILED_ACCENT,
}

_GEAR = MONITOR_GLYPH
_DARK_INK = "#1a1a1a"


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


def update_gear_chip(state: UpdateGearState | None) -> Text:
    """Build the updates-badge gear inset for *state*."""
    if state is None:
        return Text("")
    return Text(f" {_GEAR} ", style=f"bold {_DARK_INK} on {UPDATE_GEAR_HUES[state]}")


__all__ = [
    "MONITOR_GEAR_HUE",
    "PROC_GEAR_HUE",
    "UPDATE_GEAR_HUE",
    "UPDATE_GEAR_HUES",
    "gear_chip",
    "update_gear_chip",
]
