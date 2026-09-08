"""+1 evidence rendering and detail-pane iteration for the notification modal."""

from __future__ import annotations

from typing import Any

from rich.console import Group, RenderableType
from rich.text import Text

from sase.bead.plus_one_presentation import (
    PLUS_ONE_RICH_STYLE,
    PLUS_ONE_SECTION_LABEL,
    plus_one_badge,
)
from sase.notifications import (
    Notification,
    NotificationPlusOne,
    format_absolute_time,
    format_relative_time,
)

from .notification_modal_palette import PANE_MUTED

_PLUS_ONE_PANE_HINT = "+ next  · wraps to the default pane"
_NO_PLUS_ONES_HINT = "No +1 notes on this notification"


def plus_one_evidence_renderables(notification: Notification) -> list[RenderableType]:
    """Return the static ``+1 EVIDENCE`` group, or an empty list."""
    if not notification.plus_ones:
        return []
    parts: list[RenderableType] = [
        Text(""),
        Text(PLUS_ONE_SECTION_LABEL, style="bold"),
    ]
    for entry in notification.plus_ones:
        line = Text()
        line.append(
            f"+1 {entry.sender} · {format_relative_time(entry.timestamp)}",
            style=PLUS_ONE_RICH_STYLE,
        )
        line.append(" — ")
        line.append(entry.note)
        parts.append(line)
    return parts


def plus_one_report_suffix(notification: Notification) -> Text | None:
    """Return the report-pane ``· +N (latest <age>)`` suffix, if any."""
    badge = plus_one_badge(notification.plus_one_count)
    if not badge or not notification.plus_ones:
        return None
    latest = notification.plus_ones[-1]
    age = format_relative_time(latest.timestamp)
    suffix = Text()
    suffix.append(f" · {badge} (latest {age})", style=PLUS_ONE_RICH_STYLE)
    return suffix


def _plus_ones_newest_first(
    notification: Notification,
) -> list[NotificationPlusOne]:
    """Return stored +1 entries newest first for pane iteration."""
    return list(reversed(notification.plus_ones))


class NotificationPlusOneMixin:
    """Cycle the detail pane through a row's +1 notes, newest first."""

    _plus_one_cursor: int | None

    def _reset_plus_one_pane(self: Any) -> None:
        """Return the detail pane to its default (non-+1) view."""
        self._plus_one_cursor = None

    def _render_plus_one_pane(
        self: Any, notification: Notification
    ) -> tuple[str, RenderableType] | None:
        """Return the +1 iteration pane, or ``None`` on the default view."""
        cursor = getattr(self, "_plus_one_cursor", None)
        entries = _plus_ones_newest_first(notification)
        if cursor is None or not entries or cursor < 0 or cursor >= len(entries):
            return None
        entry = entries[cursor]
        header = Text(
            f"+1 {cursor + 1}/{len(entries)} · {entry.sender} · "
            f"{format_absolute_time(entry.timestamp)}",
            style=PLUS_ONE_RICH_STYLE,
        )
        note = Text(entry.note)
        hint = Text(_PLUS_ONE_PANE_HINT, style=PANE_MUTED)
        return "+1", Group(header, Text(""), note, Text(""), hint)

    def action_cycle_plus_ones(self: Any) -> None:
        """Advance through +1 notes, wrapping back to the default pane."""
        notification = self._get_highlighted_notification()
        if notification is None:
            self.notify(_NO_PLUS_ONES_HINT)
            return
        entries = _plus_ones_newest_first(notification)
        if not entries:
            self.notify(_NO_PLUS_ONES_HINT)
            return
        cursor = getattr(self, "_plus_one_cursor", None)
        if cursor is None:
            self._plus_one_cursor = 0
        elif cursor + 1 >= len(entries):
            self._plus_one_cursor = None
        else:
            self._plus_one_cursor = cursor + 1
        self._display_file(notification)
        self._update_hint_footer()


__all__ = [
    "NotificationPlusOneMixin",
    "plus_one_evidence_renderables",
    "plus_one_report_suffix",
]
