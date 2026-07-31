"""Sent-at line for the notification modal detail pane."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.widgets import Label

from sase.notifications import (
    Notification,
    format_absolute_time,
    format_relative_time,
)

SENT_AT_ID = "notification-sent-at"


def _build_sent_at_text(notification: Notification) -> Text:
    """Build the styled 'sent <absolute> · <relative>' line."""
    text = Text(no_wrap=True, overflow="ellipsis")
    text.append("sent ")
    text.append(format_absolute_time(notification.timestamp), style="bold")
    text.append(" · ", style="dim")
    text.append(format_relative_time(notification.timestamp), style="dim")
    return text


class NotificationSentAtMixin:
    """Keep the detail pane's send-time line in sync with the selection."""

    def _update_sent_at(self: Any, notification: Notification | None) -> None:
        """Render, or hide, the send-time line for the highlighted row."""
        try:
            label = self.query_one(f"#{SENT_AT_ID}", Label)
        except Exception:
            return
        if notification is None:
            label.update(Text(""))
            label.add_class("hidden")
            return
        label.update(_build_sent_at_text(notification))
        label.remove_class("hidden")
