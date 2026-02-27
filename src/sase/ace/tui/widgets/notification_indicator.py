"""Persistent notification indicator widget for the ace TUI."""

from typing import Any

from rich.text import Text
from textual.widgets import Static


class NotificationIndicator(Static):
    """Always-visible notification count in the top-right."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(self._build_content(0, 0), **kwargs)
        self._read_count = 0
        self._unread_count = 0

    def set_counts(self, read_count: int, unread_count: int) -> None:
        """Update the displayed read/unread counts.

        Args:
            read_count: Number of read notifications.
            unread_count: Number of unread notifications.
        """
        if self._read_count != read_count or self._unread_count != unread_count:
            self._read_count = read_count
            self._unread_count = unread_count
            if self.is_mounted:
                self.update(self._build_content(read_count, unread_count))

    @staticmethod
    def _build_content(read_count: int, unread_count: int) -> Text:
        """Build the indicator text."""
        total = read_count + unread_count
        if total == 0:
            return Text(" \u2709 0 ", style="dim")
        if read_count == 0:
            # Only unread
            return Text(f" \u2709 {unread_count} ", style="bold #1a1a1a on #FFD700")
        if unread_count == 0:
            # Only read
            return Text(f" \u2709 {read_count} ", style="bold #1a1a1a on #4488CC")
        # Both read and unread
        return Text(
            f" \u2709 {read_count}/{unread_count} ", style="bold #1a1a1a on #FFD700"
        )
