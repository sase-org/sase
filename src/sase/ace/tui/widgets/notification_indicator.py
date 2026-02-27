"""Persistent notification indicator widget for the ace TUI."""

from typing import Any

from rich.text import Text
from textual.widgets import Static


class NotificationIndicator(Static):
    """Always-visible unread notification count in the top-right."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(self._build_content(0), **kwargs)
        self._count = 0

    def set_count(self, count: int) -> None:
        """Update the displayed unread count.

        Args:
            count: Number of unread notifications.
        """
        if self._count != count:
            self._count = count
            if self.is_mounted:
                self.update(self._build_content(count))

    @staticmethod
    def _build_content(count: int) -> Text:
        """Build the indicator text."""
        label = f" \u2709 {count} "
        if count > 0:
            return Text(label, style="bold #1a1a1a on #FFD700")
        return Text(label, style="dim")
