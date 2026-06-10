"""Persistent notification indicator widget for the ace TUI."""

from typing import Any

from rich.text import Text
from textual.widgets import Static


class NotificationIndicator(Static):
    """Always-visible unread notification badge in the top bar.

    The badge shows a single count of the notifications that need
    attention (priority + non-priority unmuted), and the badge color
    signals urgency:
      * orange — at least one unmuted priority-type notification
      * gold — unmuted non-priority notifications, no priority
      * dim cyan — only muted notifications remain (the count shows the
        size of that acknowledged backlog instead)
      * dim — nothing unread

    A trailing dim ``·`` marks a muted backlog coexisting with actionable
    notifications. Hovering reveals the exact priority/other/muted
    breakdown via tooltip, and clicking opens the notification modal.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(self._build_content(0, 0, 0), **kwargs)
        self._priority = 0
        self._rest = 0
        self._muted = 0
        self.tooltip = self._build_tooltip(0, 0, 0)

    def set_count(self, count: int) -> None:
        """Backward-compatible single-int wrapper.

        Treats the value as non-priority unmuted unread.
        """
        self.set_counts(0, count, 0)

    def set_counts(self, priority: int, rest: int, muted: int) -> None:
        """Update the three count buckets driving the indicator.

        Args:
            priority: Unmuted, unread, priority-type notifications. Drives
                the orange badge color when greater than zero.
            rest: Unmuted, unread, non-priority notifications. Drives the
                gold badge color when ``priority == 0``. The badge count is
                always ``priority + rest`` while either is nonzero.
            muted: Muted, unread notifications of any type. Renders as the
                trailing dim ``·`` marker when actionable notifications
                exist, and drives the dim-cyan badge (with ``muted`` as the
                count) when both ``priority`` and ``rest`` are zero.
        """
        if self._priority == priority and self._rest == rest and self._muted == muted:
            return
        self._priority = priority
        self._rest = rest
        self._muted = muted
        self.tooltip = self._build_tooltip(priority, rest, muted)
        if self.is_mounted:
            self.update(self._build_content(priority, rest, muted))

    async def on_click(self) -> None:
        """Open the notification modal, same as the ``show_notifications`` key."""
        await self.app.run_action("show_notifications")

    @staticmethod
    def _build_content(priority: int, rest: int, muted: int) -> Text:
        """Build the badge text: one count, plus the muted-backlog dot."""
        if priority == 0 and rest == 0 and muted == 0:
            return Text(" ✉ 0 ", style="dim")

        actionable = priority + rest
        if priority > 0:
            text = Text(f" ✉ {actionable} ", style="bold #1a1a1a on #FF8700")
        elif rest > 0:
            text = Text(f" ✉ {actionable} ", style="bold #1a1a1a on #FFD700")
        else:
            # Muted-only collapse: the backlog size becomes the badge count.
            return Text(f" ✉ {muted} ", style="bold #1a1a1a on #5FAFAF")
        if muted > 0:
            text.append("· ", style="dim")
        return text

    @staticmethod
    def _build_tooltip(priority: int, rest: int, muted: int) -> str:
        """Build the hover tooltip with the exact per-bucket breakdown."""
        if priority == 0 and rest == 0 and muted == 0:
            return "No unread notifications"
        segments = []
        if priority > 0:
            segments.append(f"{priority} priority")
        if rest > 0:
            segments.append(f"{rest} other")
        if muted > 0:
            segments.append(f"{muted} muted")
        return " · ".join(segments)
