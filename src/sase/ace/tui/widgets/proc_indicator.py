"""Background proc and monitor indicator widgets for sase's TUI."""

from typing import Any

from rich.text import Text

from ..proc_gear_chips import MONITOR_GEAR_HUE, PROC_GEAR_HUE, gear_chip
from .top_bar_group import TopBarGroup


class ProcIndicator(TopBarGroup):
    """Shows the count of running ACE-owned background procs in the top-bar.

    Renders as ``procs: ⚙ N`` with the blue gear chip shared with the Procs
    tab header. Excludes ``sase monitor start`` proc shells — see
    :class:`MonitorIndicator`. Visible only when at least one proc is
    running; hides itself otherwise to avoid clutter. Clicking opens the
    Admin Center Procs tab.
    """

    GROUP_LABEL = "procs"
    CLICK_ACTION = "open_tasks_panel"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._count = 0
        self._set_body(self._build_content(0))
        self.tooltip = self._build_tooltip(0)

    def set_count(self, count: int) -> None:
        """Update the displayed running proc count.

        Args:
            count: Number of currently running background procs.
        """
        if self._count != count:
            self._count = count
            self._set_body(self._build_content(count))
            tooltip = self._build_tooltip(count)
            if self.tooltip != tooltip:
                self.tooltip = tooltip

    @staticmethod
    def _build_content(count: int) -> Text:
        """Build the indicator body."""
        return gear_chip(count, PROC_GEAR_HUE)

    @staticmethod
    def _build_tooltip(count: int) -> str:
        """Build the hover tooltip describing the proc count."""
        if count <= 0:
            return "No running procs\nClick to open the Procs tab"
        noun = "proc" if count == 1 else "procs"
        return f"{count} running {noun}\nClick to open the Procs tab"


class MonitorIndicator(TopBarGroup):
    """Shows the count of running monitor shells in the top-bar.

    Renders as ``monitors: ⚙ N`` with the amber gear chip shared with the
    Procs tab header. A monitor shell (``sase monitor start``) is a detached
    supervisor that outlives ACE, so it is counted separately from
    :class:`ProcIndicator`'s ACE-owned procs. Visible only when at least one
    monitor is running; hides itself otherwise to avoid clutter. Clicking
    opens the Admin Center Procs tab.
    """

    GROUP_LABEL = "monitors"
    CLICK_ACTION = "open_tasks_panel"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._count = 0
        self._set_body(self._build_content(0))
        self.tooltip = self._build_tooltip(0)

    def set_count(self, count: int) -> None:
        """Update the displayed running monitor count.

        Args:
            count: Number of currently running monitor shells.
        """
        if self._count != count:
            self._count = count
            self._set_body(self._build_content(count))
            tooltip = self._build_tooltip(count)
            if self.tooltip != tooltip:
                self.tooltip = tooltip

    @staticmethod
    def _build_content(count: int) -> Text:
        """Build the indicator body."""
        return gear_chip(count, MONITOR_GEAR_HUE)

    @staticmethod
    def _build_tooltip(count: int) -> str:
        """Build the hover tooltip describing the monitor count."""
        if count <= 0:
            return "No running monitors\nClick to open the Procs tab"
        noun = "monitor" if count == 1 else "monitors"
        return f"{count} running {noun}\nClick to open the Procs tab"
