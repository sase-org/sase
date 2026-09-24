"""Proc indicator widget for sase's TUI."""

from typing import Any

from rich.text import Text

from ..proc_gear_chips import MONITOR_GEAR_HUE, PROC_GEAR_HUE, gear_chip
from .top_bar_group import TopBarGroup


class ProcIndicator(TopBarGroup):
    """Shows running procs and monitor shells in the top-bar.

    Renders as ``procs: ⚙ N`` with the blue chip for ACE-owned procs and
    appends the orange chip for running monitor shells
    (``sase monitor start``), the same pair the Procs tab header shows.
    Hidden only when both counts are zero; clicking opens the Procs tab.
    """

    GROUP_LABEL = "procs"
    CLICK_ACTION = "open_tasks_panel"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._count = 0
        self._monitor_count = 0
        self._set_body(self._build_content(0, 0))
        self.tooltip = self._build_tooltip(0, 0)

    def set_counts(self, proc_count: int, monitor_count: int) -> None:
        """Update the displayed running proc and monitor counts.

        Args:
            proc_count: Number of currently running background procs.
            monitor_count: Number of currently running monitor shells.
        """
        if self._count == proc_count and self._monitor_count == monitor_count:
            return
        self._count = proc_count
        self._monitor_count = monitor_count
        self._set_body(self._build_content(proc_count, monitor_count))
        tooltip = self._build_tooltip(proc_count, monitor_count)
        if self.tooltip != tooltip:
            self.tooltip = tooltip

    @staticmethod
    def _build_content(proc_count: int, monitor_count: int) -> Text:
        """Build the indicator body."""
        text = gear_chip(proc_count, PROC_GEAR_HUE)
        text.append_text(gear_chip(monitor_count, MONITOR_GEAR_HUE))
        return text

    @staticmethod
    def _build_tooltip(proc_count: int, monitor_count: int) -> str:
        """Build the hover tooltip describing the proc and monitor counts."""
        parts: list[str] = []
        if proc_count > 0:
            noun = "proc" if proc_count == 1 else "procs"
            parts.append(f"{proc_count} running {noun}")
        if monitor_count > 0:
            noun = "monitor" if monitor_count == 1 else "monitors"
            parts.append(f"{monitor_count} running {noun}")
        if not parts:
            return "No running procs\nClick to open the Procs tab"
        return f"{', '.join(parts)}\nClick to open the Procs tab"
