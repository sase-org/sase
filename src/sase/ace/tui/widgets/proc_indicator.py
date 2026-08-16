"""Background proc and monitor indicator widgets for the ace TUI."""

from typing import Any

from rich.text import Text
from textual.widgets import Static

from sase.monitor_state import MONITOR_GLYPH

_GEAR = MONITOR_GLYPH  # same glyph for both lanes; hue is the lane


def _gear_chip(count: int, background: str) -> Text:
    """Build a gear chip, or an empty ``Text`` when *count* is zero."""
    if count <= 0:
        return Text("")
    return Text(f" {_GEAR} {count} ", style=f"bold #1a1a1a on {background}")


class ProcIndicator(Static):
    """Shows the count of running ACE-owned background procs in the top-bar.

    Excludes ``sase monitor start`` proc shells \u2014 see :class:`MonitorIndicator`.
    Visible only when at least one proc is running; hides itself otherwise
    to avoid clutter.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(self._build_content(0), **kwargs)
        self._count = 0

    def set_count(self, count: int) -> None:
        """Update the displayed running proc count.

        Args:
            count: Number of currently running background procs.
        """
        if self._count != count:
            self._count = count
            if self.is_mounted:
                self.update(self._build_content(count))

    @staticmethod
    def _build_content(count: int) -> Text:
        """Build the indicator text."""
        return _gear_chip(count, "#48CAE4")


class MonitorIndicator(Static):
    """Shows the count of running monitor shells in the top-bar.

    A monitor shell (``sase monitor start``) is a detached supervisor that
    outlives ACE, so it is counted separately from :class:`ProcIndicator`'s
    ACE-owned procs. Visible only when at least one monitor is running;
    hides itself otherwise to avoid clutter.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(self._build_content(0), **kwargs)
        self._count = 0

    def set_count(self, count: int) -> None:
        """Update the displayed running monitor count.

        Args:
            count: Number of currently running monitor shells.
        """
        if self._count != count:
            self._count = count
            if self.is_mounted:
                self.update(self._build_content(count))

    @staticmethod
    def _build_content(count: int) -> Text:
        """Build the indicator text."""
        return _gear_chip(count, "#FFAF5F")
