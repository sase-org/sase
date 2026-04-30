"""State-changing actions for the notification modal."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sase.core.time import get_timezone

from .snooze_duration_modal import SnoozeDurationModal


class NotificationStateActionsMixin:
    """Dismiss, mute, snooze, and read notification rows."""

    def action_dismiss_notification(self: Any) -> None:
        """Dismiss the currently highlighted notification."""
        idx = self._get_selected_index()
        if idx is None or idx >= len(self._notifications):
            return

        notification = self._notifications[idx]

        if notification.action in ("PlanApproval", "UserQuestion"):
            self._pending_confirm_notification_id = notification.id
            self.notify("Dismiss plan/question notification? (y/n)")
            return

        self._pending_confirm_notification_id = None
        self._dismiss_notification_by_index(idx)

    def action_confirm_dismiss_notification(self: Any) -> None:
        """Confirm dismissal of a plan/question notification."""
        pending_id = self._pending_confirm_notification_id
        if pending_id is None:
            return

        idx = next(
            (
                i
                for i, notification in enumerate(self._notifications)
                if notification.id == pending_id
            ),
            None,
        )
        self._pending_confirm_notification_id = None
        if idx is None:
            return

        self._dismiss_notification_by_index(idx)

    def action_cancel_dismiss_notification(self: Any) -> None:
        """Cancel a pending plan/question dismiss confirmation."""
        if self._pending_confirm_notification_id is None:
            return
        self._pending_confirm_notification_id = None
        self.notify("Dismiss canceled")

    def _dismiss_notification_by_index(self: Any, idx: int) -> None:
        """Dismiss notification at index and rebuild the list UI."""
        notification = self._notifications[idx]
        replacement_id = self._replacement_notification_id_after_dismiss(idx)
        self._mark_dismissed(notification.id)

        self._notifications.pop(idx)
        highlight = next(
            (
                i
                for i, notification in enumerate(self._notifications)
                if notification.id == replacement_id
            ),
            None,
        )
        self._rebuild_list(highlight_index=highlight)

    def action_toggle_mute(self: Any) -> None:
        """Toggle mute on the highlighted notification."""
        idx = self._get_selected_index()
        if idx is None or idx >= len(self._notifications):
            return

        notification = self._notifications[idx]
        new_muted = not notification.muted
        was_snoozed = notification.snooze_until is not None
        self._mark_muted(notification.id, new_muted)
        notification.muted = new_muted
        if not new_muted:
            notification.snooze_until = None

        self._rebuild_list(highlight_index=idx)
        if new_muted:
            self.notify("Muted")
        elif was_snoozed:
            self.notify("Unmuted (snooze cancelled)")
        else:
            self.notify("Unmuted")

    def action_snooze(self: Any) -> None:
        """Snooze the highlighted notification via the duration picker."""
        idx = self._get_selected_index()
        if idx is None or idx >= len(self._notifications):
            return

        notification = self._notifications[idx]

        def _on_picked(result: timedelta | datetime | None) -> None:
            if result is None:
                self.notify("Snooze cancelled")
                return
            if isinstance(result, datetime):
                snooze_until = result
                description = "until tomorrow morning"
            else:
                snooze_until = datetime.now(get_timezone()) + result
                description = f"for {self._format_delta(result)}"

            self._mark_snoozed(notification.id, snooze_until)
            notification.muted = True
            notification.snooze_until = snooze_until.isoformat()

            self._rebuild_list(highlight_index=idx)
            self.notify(f"Snoozed {description}")

        self.app.push_screen(SnoozeDurationModal(), callback=_on_picked)

    @staticmethod
    def _format_delta(delta: timedelta) -> str:
        """Format a timedelta for the snooze toast (e.g. '15m', '1h30m')."""
        total = int(delta.total_seconds())
        hours, remainder = divmod(total, 3600)
        minutes, seconds = divmod(remainder, 60)
        parts: list[str] = []
        if hours:
            parts.append(f"{hours}h")
        if minutes:
            parts.append(f"{minutes}m")
        if seconds and not hours and not minutes:
            parts.append(f"{seconds}s")
        return "".join(parts) or "0s"

    def action_read_all(self: Any) -> None:
        """Mark all notifications as read and rebuild the display."""
        self._mark_all_read()

        for n in self._notifications:
            n.read = True

        self._rebuild_list()
