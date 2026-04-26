"""Persistent notification indicator widget for the ace TUI."""

from typing import Any

from rich.text import Text
from textual.widgets import Static


class NotificationIndicator(Static):
    """Always-visible unread notification count in the top-right."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(self._build_content(0, 0), **kwargs)
        self._unread = 0
        self._muted = 0

    def set_count(self, count: int) -> None:
        """Update the displayed unread count (no muted secondary).

        Backward-compatible wrapper around :meth:`set_counts`.
        """
        self.set_counts(count, 0)

    def set_counts(self, unread: int, muted: int) -> None:
        """Update both the active-unread and muted-unread counts.

        Args:
            unread: Number of non-muted unread notifications (drives the
                primary gold/dim envelope segment).
            muted: Number of muted unread notifications (drives the dim
                secondary segment, only rendered when ``muted > 0``).
        """
        if self._unread == unread and self._muted == muted:
            return
        self._unread = unread
        self._muted = muted
        if self.is_mounted:
            self.update(self._build_content(unread, muted))

    @staticmethod
    def _build_content(unread: int, muted: int) -> Text:
        """Build the indicator text with primary + optional secondary segments."""
        primary_label = f" ✉ {unread} "
        if unread > 0:
            text = Text(primary_label, style="bold #1a1a1a on #FFD700")
        else:
            text = Text(primary_label, style="dim")
        if muted > 0:
            text.append(f"·{muted} ", style="dim")
        return text
