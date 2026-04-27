"""Persistent notification indicator widget for the ace TUI."""

from typing import Any

from rich.text import Text
from textual.widgets import Static


class NotificationIndicator(Static):
    """Always-visible unread notification count in the top-right.

    The primary segment color signals urgency:
      * orange — at least one unmuted priority-type notification
      * gold — unmuted non-priority notifications, no priority
      * dim cyan — only muted notifications remain (acknowledged backlog)
      * dim — nothing unread
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(self._build_content(0, 0, 0), **kwargs)
        self._priority = 0
        self._rest = 0
        self._muted = 0

    def set_count(self, count: int) -> None:
        """Backward-compatible single-int wrapper.

        Treats the value as non-priority unmuted unread.
        """
        self.set_counts(0, count, 0)

    def set_counts(self, priority: int, rest: int, muted: int) -> None:
        """Update the three count segments driving the indicator.

        Args:
            priority: Unmuted, unread, priority-type notifications. Drives
                the orange primary segment when greater than zero.
            rest: Unmuted, unread, non-priority notifications. Drives the
                gold primary segment when ``priority == 0``.
            muted: Muted, unread notifications of any type. Renders as the
                ``·N`` secondary segment, and drives the dim-cyan primary
                color when both ``priority`` and ``rest`` are zero.
        """
        if self._priority == priority and self._rest == rest and self._muted == muted:
            return
        self._priority = priority
        self._rest = rest
        self._muted = muted
        if self.is_mounted:
            self.update(self._build_content(priority, rest, muted))

    @staticmethod
    def _build_content(priority: int, rest: int, muted: int) -> Text:
        """Build the indicator text with primary + optional secondary segments."""
        if priority == 0 and rest == 0 and muted == 0:
            return Text(" ✉ 0 ", style="dim")

        if priority > 0:
            text = Text(f" ✉ {priority}+{rest} ", style="bold #1a1a1a on #FF8700")
        elif rest > 0:
            text = Text(f" ✉ {rest} ", style="bold #1a1a1a on #FFD700")
        else:
            # Muted-only collapse: count goes in the primary segment, no secondary.
            return Text(f" ✉ {muted} ", style="bold #1a1a1a on #5FAFAF")
        if muted > 0:
            text.append(f"·{muted} ", style="dim")
        return text
