"""Mute actions for the notification modal."""

from __future__ import annotations

from typing import Any

from .notification_modal_action_types import NotificationMutationResult


class NotificationMuteActionsMixin:
    """Toggle mute state for one or more notification rows."""

    def action_toggle_mute(self: Any) -> None:
        """Toggle mute on the highlighted notification."""
        target = self._resolve_notification_state_targets()
        if not target.ids:
            return
        if target.from_marks:
            self._dispatch_bulk_toggle_mute(target.ids)
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

        previous_tabs = self._tag_tabs()
        replacement_id = self._replacement_notification_id_after_reclassification(idx)
        notification = self._notifications[idx]
        new_muted = not notification.muted
        was_snoozed = notification.snooze_until is not None
        self._mark_muted(notification.id, new_muted)
        self._request_authoritative_notification_refresh()
        notification.muted = new_muted
        if not new_muted:
            notification.snooze_until = None

        self._rebuild_after_notification_reclassification(
            previous_tabs=previous_tabs,
            changed_notification_id=notification.id,
            replacement_notification_id=replacement_id,
        )
        if new_muted:
            self.notify("Muted")
        elif was_snoozed:
            self.notify("Unmuted (snooze cancelled)")
        else:
            self.notify("Unmuted")

    def _dispatch_bulk_toggle_mute(
        self: Any, notification_ids: tuple[str, ...]
    ) -> None:
        """Persist and apply a mark-targeted mute toggle."""
        targets = self._live_notifications_for_ids(notification_ids)
        if not targets:
            self._marked_notification_ids.difference_update(notification_ids)
            return
        ids = tuple(n.id for n in targets)
        new_muted = any(not n.muted for n in targets)
        cancelled_snoozes = not new_muted and any(n.snooze_until for n in targets)

        self._submit_notification_state_task(
            label="Update notifications",
            action="mute" if new_muted else "unmute",
            ids=ids,
            cancelled_snoozes=cancelled_snoozes,
            muted=new_muted,
            on_complete=self._complete_bulk_toggle_mute,
        )

    def _complete_bulk_toggle_mute(
        self: Any, result: NotificationMutationResult
    ) -> None:
        """Apply a completed bulk mute/unmute mutation on the UI thread."""
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
            notification.muted = bool(result.muted)
            if not result.muted:
                notification.snooze_until = None
        self._marked_notification_ids.difference_update(acted_ids)
        self._rebuild_after_bulk_notification_reclassification(
            previous_tabs=previous_tabs,
            replacement_notification_id=replacement_id,
            preferred_notification_id=preferred_id,
        )
        count = len(indices) if indices else result.matched_count
        if result.muted:
            self.notify(f"Muted {count} notifications")
        elif result.cancelled_snoozes:
            self.notify(f"Unmuted {count} notifications (snoozes cancelled)")
        else:
            self.notify(f"Unmuted {count} notifications")
