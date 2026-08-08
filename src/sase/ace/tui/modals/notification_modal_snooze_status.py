"""Selected snooze-status line for the notification modal detail pane."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual.widgets import Label

from sase.core.time import get_timezone, parse_local
from sase.notifications import Notification

if TYPE_CHECKING:
    from textual.timer import Timer


SNOOZE_STATUS_ID = "notification-snooze-status"
SNOOZE_STATUS_TIMER_INTERVAL_SECONDS = 30.0
SNOOZE_STATUS_TIMER_NAME = "notification-snooze-status"

_QUIET_STYLE = "dim"
_REMAINING_STYLE = "bold #D7AF5F"
_UNAVAILABLE_STYLE = "dim italic"


def _snooze_status_now() -> datetime:
    """Return the configured-timezone clock used by the status renderer."""
    return datetime.now(get_timezone())


def _coerce_reference_now(now: datetime | None) -> datetime:
    """Return *now* as an aware datetime in the configured timezone."""
    tz = get_timezone()
    if now is None:
        return _snooze_status_now()
    if now.tzinfo is None:
        return now.replace(tzinfo=tz)
    return now.astimezone(tz)


def _format_snooze_remaining(wake_at: datetime, now: datetime) -> str:
    """Format a future snooze duration with at most two useful units."""
    total_seconds = int((wake_at - now).total_seconds())
    if total_seconds <= 0:
        return ""
    if total_seconds < 60:
        return "<1m"

    minutes = total_seconds // 60
    if minutes < 60:
        return f"{minutes}m"

    hours = minutes // 60
    if hours < 24:
        remainder_minutes = minutes % 60
        if remainder_minutes:
            return f"{hours}h {remainder_minutes}m"
        return f"{hours}h"

    days = hours // 24
    remainder_hours = hours % 24
    if remainder_hours:
        return f"{days}d {remainder_hours}h"
    return f"{days}d"


def _format_snooze_wake_instant(wake_at: datetime, now: datetime) -> str:
    """Format the absolute snooze wake instant for the detail pane."""
    local_wake = wake_at.astimezone(get_timezone())
    local_now = _coerce_reference_now(now)
    time_label = local_wake.strftime("%H:%M")
    timezone_label = local_wake.strftime("%Z")
    suffix = f" {timezone_label}" if timezone_label else ""

    days_until = (local_wake.date() - local_now.date()).days
    if days_until == 0:
        return f"today at {time_label}{suffix}"
    if days_until == 1:
        return f"tomorrow at {time_label}{suffix}"
    if local_wake.year == local_now.year:
        return f"{local_wake.strftime('%a %b %-d')} at {time_label}{suffix}"
    return f"{local_wake.strftime('%a %b %-d, %Y')} at {time_label}{suffix}"


def _build_snooze_status_text(
    notification: Notification,
    *,
    now: datetime | None = None,
) -> Text | None:
    """Build the selected-row snooze status, or ``None`` when not snoozed."""
    snooze_until = notification.snooze_until
    if snooze_until is None:
        return None

    text = Text(no_wrap=True, overflow="ellipsis")
    text.append("☾ Snoozed", style=_QUIET_STYLE)

    wake_at = parse_local(snooze_until)
    if wake_at is None:
        text.append(" · wake time unavailable", style=_UNAVAILABLE_STYLE)
        return text

    reference_now = _coerce_reference_now(now)
    remaining = _format_snooze_remaining(wake_at, reference_now)
    wake_label = _format_snooze_wake_instant(wake_at, reference_now)
    if not remaining:
        text.append(" · waking now…", style=_REMAINING_STYLE)
        text.append(" · ", style=_QUIET_STYLE)
        text.append(wake_label, style=_QUIET_STYLE)
        return text

    text.append(" · wakes in ", style=_QUIET_STYLE)
    text.append(remaining, style=_REMAINING_STYLE)
    text.append(" · ", style=_QUIET_STYLE)
    text.append(wake_label, style=_QUIET_STYLE)
    return text


class NotificationSnoozeStatusMixin:
    """Keep the selected snoozed row's wake status fresh."""

    _snooze_status_timer: Timer | None

    def _start_snooze_status_timer(self: Any) -> None:
        """Start the modal-owned countdown refresh timer once."""
        if getattr(self, "_snooze_status_timer", None) is not None:
            return
        try:
            self._snooze_status_timer = self.set_interval(
                SNOOZE_STATUS_TIMER_INTERVAL_SECONDS,
                self._refresh_snooze_status_from_timer,
                name=SNOOZE_STATUS_TIMER_NAME,
            )
        except Exception:
            self._snooze_status_timer = None

    def _stop_snooze_status_timer(self: Any) -> None:
        """Stop the modal-owned countdown refresh timer."""
        timer = getattr(self, "_snooze_status_timer", None)
        if timer is None:
            return
        timer.stop()
        self._snooze_status_timer = None

    def _update_snooze_status(self: Any, notification: Notification | None) -> None:
        """Render, or hide, the selected-row snooze status line."""
        try:
            label = self.query_one(f"#{SNOOZE_STATUS_ID}", Label)
        except Exception:
            return

        if notification is None:
            label.update(Text(""))
            label.add_class("hidden")
            return

        status = _build_snooze_status_text(notification)
        if status is None:
            label.update(Text(""))
            label.add_class("hidden")
            return

        label.update(status)
        label.remove_class("hidden")

    def _refresh_snooze_status_from_timer(self: Any) -> None:
        """Refresh only the selected-row snooze status from a Textual timer."""
        notification = self._get_highlighted_notification()
        if notification is None or not notification.snooze_until:
            return
        self._update_snooze_status(notification)
