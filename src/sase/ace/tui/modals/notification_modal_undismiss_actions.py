"""Undismiss actions for the notification modal."""

from __future__ import annotations

from typing import Any

from .notification_modal_action_types import NotificationMutationResult

# Title suffix shown while the modal lists dismissed rows instead of the
# normal inbox.
_DISMISSED_VIEW_TITLE_SUFFIX = " (dismissed)"


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

    def action_toggle_dismissed_view(self: Any) -> None:
        """Switch between the unread inbox and the dismissed-rows view.

        Bound to ``T``. ``T`` has no twin in use today (``t`` is unbound),
        unlike ``d``/``D`` or ``x``/``X`` where the lowercase twin already
        means something else. The dismissed view reloads the page with
        ``include_dismissed=True`` and keeps the modal's unread scope: rows
        that are both read and dismissed stay out of both views.
        """
        self._showing_dismissed = not self._showing_dismissed
        self._reload_notifications_for_current_view()
        self._clear_tab_scoped_state()
        self._update_dismissed_view_title()
        self._rebuild_list(highlight_index=self._first_visible_notification_index())
        if self._showing_dismissed:
            self.notify("Showing dismissed notifications (T to return)")
        else:
            self.notify("Showing unread notifications")

    def _reload_notifications_for_current_view(self: Any) -> None:
        """Reload modal rows for the active inbox/dismissed view.

        The mounted app reloads authoritatively through the notification
        provider, exactly like the initial modal load. Without an app (or
        when the provider is unreachable) the modal reads the store
        directly with the same unread filter, so the toggle still works.
        """
        include_dismissed = bool(getattr(self, "_showing_dismissed", False))
        try:
            reader = getattr(
                self.app, "_read_unread_notification_page_from_provider", None
            )
            if callable(reader):
                page = reader(include_dismissed=include_dismissed)
                self._notifications = list(page.notifications)
                return
        except Exception:
            pass
        try:
            from sase.notifications import load_notifications

            rows = load_notifications(include_dismissed=True)
            self._notifications = [
                notification
                for notification in rows
                if not notification.read
                and not notification.silent
                and (include_dismissed or not notification.dismissed)
                and (not include_dismissed or notification.dismissed)
            ]
        except Exception:
            pass

    def _update_dismissed_view_title(self: Any) -> None:
        """Mark the dismissed view visibly in the modal title."""
        try:
            from textual.widgets import Label

            title = self.query_one("#notification-title", Label)
        except Exception:
            return
        if getattr(self, "_showing_dismissed", False):
            title.update(f"Notifications{_DISMISSED_VIEW_TITLE_SUFFIX}")
        else:
            title.update("Notifications")

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
