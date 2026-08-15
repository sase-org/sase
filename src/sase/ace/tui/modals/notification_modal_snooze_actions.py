"""Snooze actions for the notification modal."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from .notification_modal_action_types import (
    NotificationMutationResult,
    resolve_snooze_deadline,
)
from .snooze_duration_modal import SnoozeDurationModal


class NotificationSnoozeActionsMixin:
    """Snooze one or more notification rows."""

    def action_snooze(self: Any) -> None:
        """Snooze the highlighted notification via the duration picker."""
        target = self._resolve_notification_state_targets()
        if not target.ids:
            return

        if target.from_marks:
            self._push_bulk_snooze_picker(target.ids)
            return

        idx = next(
            (
                i
                for i, notification in enumerate(self._notifications)
                if notification.id == target.ids[0]
            ),
            None,
        )
        if idx is None:
            return
        notification_id = self._notifications[idx].id

        def _on_picked(result: timedelta | datetime | None) -> None:
            if result is None:
                self.notify("Snooze cancelled")
                return
            description = (
                "until tomorrow morning"
                if isinstance(result, datetime)
                else f"for {self._format_delta(result)}"
            )
            self._dispatch_single_snooze(
                notification_id,
                snooze_until=resolve_snooze_deadline(result),
                description=description,
            )

        self.app.push_screen(SnoozeDurationModal(), callback=_on_picked)

    def _push_bulk_snooze_picker(self: Any, notification_ids: tuple[str, ...]) -> None:
        """Open one picker for a mark-targeted snooze operation."""

        def _on_picked(result: timedelta | datetime | None) -> None:
            if result is None:
                self.notify("Snooze cancelled")
                return
            description = (
                "until tomorrow morning"
                if isinstance(result, datetime)
                else f"for {self._format_delta(result)}"
            )
            self._dispatch_bulk_snooze(
                notification_ids,
                snooze_until=resolve_snooze_deadline(result),
                description=description,
            )

        self.app.push_screen(SnoozeDurationModal(), callback=_on_picked)

    def _dispatch_single_snooze(
        self: Any,
        notification_id: str,
        *,
        snooze_until: datetime,
        description: str,
    ) -> None:
        """Persist one snooze off the message pump and apply only on a match."""
        self._submit_notification_state_task(
            label="Snooze notification",
            action="snooze",
            ids=(notification_id,),
            description=description,
            muted=True,
            snooze_until=snooze_until.isoformat(),
            on_complete=self._complete_single_snooze,
        )

    def _complete_single_snooze(self: Any, result: NotificationMutationResult) -> None:
        """Apply a successful single-row snooze on the UI thread."""
        self._request_authoritative_notification_refresh()
        if not result.success:
            self.notify(
                f"Could not snooze notification: {result.message}",
                severity="error",
            )
            return
        if not self._notification_modal_still_active():
            return
        idx = next(
            (
                i
                for i, notification in enumerate(self._notifications)
                if notification.id == result.ids[0]
            ),
            None,
        )
        if idx is None:
            return
        previous_tabs = self._tag_tabs()
        replacement_id = self._replacement_notification_id_after_reclassification(idx)
        notification = self._notifications[idx]
        notification.muted = True
        notification.snooze_until = result.snooze_until
        self._rebuild_after_notification_reclassification(
            previous_tabs=previous_tabs,
            changed_notification_id=notification.id,
            replacement_notification_id=replacement_id,
        )
        self.notify(f"Snoozed {result.description}")

    def _dispatch_bulk_snooze(
        self: Any,
        notification_ids: tuple[str, ...],
        *,
        snooze_until: datetime,
        description: str,
    ) -> None:
        """Persist and apply a mark-targeted snooze."""
        targets = self._live_notifications_for_ids(notification_ids)
        if not targets:
            self._marked_notification_ids.difference_update(notification_ids)
            return
        ids = tuple(n.id for n in targets)

        self._submit_notification_state_task(
            label="Snooze notifications",
            action="snooze",
            ids=ids,
            description=description,
            muted=True,
            snooze_until=snooze_until.isoformat(),
            on_complete=self._complete_bulk_snooze,
        )

    def _complete_bulk_snooze(self: Any, result: NotificationMutationResult) -> None:
        """Apply a completed bulk snooze mutation on the UI thread."""
        self._request_authoritative_notification_refresh()
        if not result.success:
            self.notify(
                f"Notification update failed: {result.message}", severity="error"
            )
            return
        if not self._notification_modal_still_active():
            return

        acted_ids = set(result.ids)
        previous_tabs = self._tag_tabs()
        current = self._get_highlighted_notification()
        preferred_id = current.id if current is not None else None
        indices = [i for i, n in enumerate(self._notifications) if n.id in acted_ids]
        replacement_id = self._replacement_notification_id_after_bulk_dismiss(indices)
        for notification in self._notifications:
            if notification.id not in acted_ids:
                continue
            notification.muted = True
            notification.snooze_until = result.snooze_until
        self._marked_notification_ids.difference_update(acted_ids)
        self._rebuild_after_bulk_notification_reclassification(
            previous_tabs=previous_tabs,
            replacement_notification_id=replacement_id,
            preferred_notification_id=preferred_id,
        )
        count = len(indices) if indices else result.matched_count
        self.notify(f"Snoozed {count} notifications {result.description}")

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
