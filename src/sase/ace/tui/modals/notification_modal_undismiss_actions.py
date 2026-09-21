"""Undismiss actions for the notification modal."""

from __future__ import annotations

from typing import Any

from .notification_modal_action_types import NotificationMutationResult


class NotificationUndismissActionsMixin:
    """Restore dismissed notification rows to the visible inbox."""

    def action_undismiss_notification(self: Any) -> None:
        """Undismiss the highlighted notification, or every marked row."""
        target = self._resolve_notification_state_targets()
        if not target.ids:
            return
        self._submit_notification_state_task(
            label="Undismiss notifications",
            action="undismiss",
            ids=target.ids,
            on_complete=self._complete_undismiss_notifications,
        )

    def _complete_undismiss_notifications(
        self: Any, result: NotificationMutationResult
    ) -> None:
        """Apply a completed undismiss mutation on the UI thread."""
        self._request_authoritative_notification_refresh()
        if not result.success:
            self.notify(
                f"Could not undismiss notifications: {result.message}",
                severity="error",
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
            if notification.id in acted_ids:
                notification.dismissed = False
        self._marked_notification_ids.difference_update(acted_ids)
        self._rebuild_after_bulk_notification_reclassification(
            previous_tabs=previous_tabs,
            replacement_notification_id=replacement_id,
            preferred_notification_id=preferred_id,
        )
        count = len(indices) if indices else result.matched_count
        self.notify(f"Undismissed {count} notification{'s' if count != 1 else ''}")
