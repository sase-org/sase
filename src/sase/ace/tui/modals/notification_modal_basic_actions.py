"""Dismiss, mark, and read actions for the notification modal."""

from __future__ import annotations

from typing import Any

from sase.notification_gates.registry import PRIVILEGED_GATE_ACTIONS

from .confirm_action_modal import ConfirmActionModal
from .confirm_dialog import ConfirmKind
from .notification_modal_action_types import NotificationMutationResult
from .notification_modal_tags import modal_tag_to_core_key


class NotificationBasicActionsMixin:
    """Dismiss, mark, and read notification rows."""

    _pending_confirm_notification_ids: list[str] | None

    def action_dismiss_notification(self: Any) -> None:
        """Dismiss the highlighted notification, or every marked row if any."""
        if self._marked_notification_ids:
            self._dispatch_marked_dismiss()
            return

        idx = self._get_selected_index()
        if idx is None or idx >= len(self._notifications):
            return

        notification = self._notifications[idx]

        if notification.action in PRIVILEGED_GATE_ACTIONS:
            self._pending_confirm_notification_id = notification.id
            self.notify("Dismiss pending action notification? (y/n)")
            return

        self._pending_confirm_notification_id = None
        self._dismiss_notification_by_index(idx)

    def _dispatch_marked_dismiss(self: Any) -> None:
        """Bulk-dismiss every marked row, prompting once if any need confirm."""
        marked_ids = [
            n.id for n in self._notifications if n.id in self._marked_notification_ids
        ]
        if not marked_ids:
            self._marked_notification_ids.clear()
            return

        needs_confirm = any(
            n.action in PRIVILEGED_GATE_ACTIONS
            for n in self._notifications
            if n.id in self._marked_notification_ids
        )
        if needs_confirm:
            self._pending_confirm_notification_ids = marked_ids
            self.notify(
                f"Dismiss {len(marked_ids)} notification(s)"
                " including pending actions? (y/n)"
            )
            return

        self._pending_confirm_notification_ids = None
        self._bulk_dismiss_marked_ids(marked_ids)

    def action_confirm_dismiss_notification(self: Any) -> None:
        """Confirm dismissal of a pending single or bulk dismiss."""
        pending_ids = self._pending_confirm_notification_ids
        if pending_ids is not None:
            self._pending_confirm_notification_ids = None
            live_ids = [n.id for n in self._notifications if n.id in set(pending_ids)]
            if live_ids:
                self._bulk_dismiss_marked_ids(live_ids)
            return

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
        if (
            self._pending_confirm_notification_id is None
            and self._pending_confirm_notification_ids is None
        ):
            return
        self._pending_confirm_notification_id = None
        self._pending_confirm_notification_ids = None
        self.notify("Dismiss canceled")

    def _bulk_dismiss_marked_ids(self: Any, notification_ids: list[str]) -> None:
        """Persist a bulk dismiss for the given ids and rebuild the modal."""
        previous_tabs = self._tag_tabs()
        id_set = set(notification_ids)
        marked_indices = [
            i for i, n in enumerate(self._notifications) if n.id in id_set
        ]
        if not marked_indices:
            self._marked_notification_ids.clear()
            return

        replacement_id = self._replacement_notification_id_after_bulk_dismiss(
            marked_indices
        )
        self._mark_many_dismissed(notification_ids)
        self._request_authoritative_notification_refresh()
        self._notifications = [n for n in self._notifications if n.id not in id_set]
        self._marked_notification_ids.clear()
        self._coerce_active_notification_tag(previous_tabs=previous_tabs)

        highlight = next(
            (i for i, n in enumerate(self._notifications) if n.id == replacement_id),
            None,
        )
        if highlight is None:
            highlight = self._first_visible_notification_index()
        self._rebuild_list(highlight_index=highlight)

    def action_toggle_mark(self: Any) -> None:
        """Toggle the mark on the highlighted notification and advance."""
        idx = self._get_selected_index()
        if idx is None or idx >= len(self._notifications):
            return

        notification = self._notifications[idx]
        if notification.id in self._marked_notification_ids:
            self._marked_notification_ids.discard(notification.id)
        else:
            self._marked_notification_ids.add(notification.id)

        next_idx = self._next_visible_notification_index(idx)
        self._rebuild_list(highlight_index=next_idx if next_idx is not None else idx)

    def _next_visible_notification_index(self: Any, current_idx: int) -> int | None:
        """Return the next visible notification index, wrapping around."""
        visible = self._visual_notification_index_order()
        if not visible:
            return None
        try:
            position = visible.index(current_idx)
        except ValueError:
            return visible[0]
        return visible[(position + 1) % len(visible)]

    def _dismiss_notification_by_index(self: Any, idx: int) -> None:
        """Dismiss notification at index and rebuild the list UI."""
        previous_tabs = self._tag_tabs()
        notification = self._notifications[idx]
        replacement_id = self._replacement_notification_id_after_dismiss(idx)
        self._mark_dismissed(notification.id)
        self._request_authoritative_notification_refresh()

        self._notifications.pop(idx)
        self._coerce_active_notification_tag(previous_tabs=previous_tabs)
        highlight = next(
            (
                i
                for i, notification in enumerate(self._notifications)
                if notification.id == replacement_id
            ),
            None,
        )
        if highlight is None:
            highlight = self._first_visible_notification_index()
        self._rebuild_list(highlight_index=highlight)

    def _bulk_dismiss_notifications_by_index(self: Any, count: int) -> int:
        """Dismiss a burst of notifications from the current modal list."""
        if count <= 0 or not self._notifications:
            return 0
        previous_tabs = self._tag_tabs()

        start_idx = self._get_selected_index()
        if start_idx is None:
            start_idx = 0
        if start_idx >= len(self._notifications):
            return 0

        end_idx = min(len(self._notifications), start_idx + count)
        notification_ids = [
            notification.id for notification in self._notifications[start_idx:end_idx]
        ]
        if not notification_ids:
            return 0

        self._mark_many_dismissed(notification_ids)
        self._request_authoritative_notification_refresh()
        del self._notifications[start_idx:end_idx]
        self._coerce_active_notification_tag(previous_tabs=previous_tabs)
        highlight = min(start_idx, len(self._notifications) - 1)
        self._rebuild_list(highlight_index=highlight if highlight >= 0 else None)
        return len(notification_ids)

    def action_read_tab(self: Any) -> None:
        """Mark every unread notification in the active tab as read."""
        active_tag = self._active_notification_tag
        tabs = self._tag_tabs()
        active_tab = next((tab for tab in tabs if tab.tag == active_tag), None)
        if active_tab is None:
            return

        core_tab_key = modal_tag_to_core_key(active_tag)
        tab_keys = self._notification_tab_keys
        captured_ids = tuple(
            n.id for n in self._notifications if tab_keys.get(n.id) == active_tag
        )
        if not captured_ids:
            return

        def _on_confirm(confirmed: bool | None) -> None:
            if confirmed is not True:
                return
            if not self._notification_modal_still_active():
                return
            self._dispatch_read_tab(core_tab_key, captured_ids)

        self.app.push_screen(
            ConfirmActionModal(
                "Mark Notification Tab Read?",
                (
                    "Every unread notification in this tab will be marked read. "
                    "This includes rows not currently loaded in ACE and cannot "
                    "be undone from ACE."
                ),
                subject=f"Tab: {active_tab.label}",
                kind=ConfirmKind.DANGER,
                confirm_label="Mark read",
                cancel_label="Cancel",
                default="cancel",
            ),
            _on_confirm,
        )

    def _dispatch_read_tab(
        self: Any, core_tab_key: str, captured_ids: tuple[str, ...]
    ) -> None:
        """Submit a tab-scoped read mutation for a previously captured target."""
        if not captured_ids:
            return

        def _task() -> NotificationMutationResult:
            try:
                self._mark_tab_read(core_tab_key)
            except Exception as exc:
                return NotificationMutationResult(
                    action="read",
                    ids=captured_ids,
                    success=False,
                    message=str(exc),
                )
            return NotificationMutationResult(
                action="read",
                ids=captured_ids,
                success=True,
                message="Tab marked read",
            )

        self._submit_notification_state_task(
            label="Read tab",
            task=_task,
            on_complete=self._complete_read_tab,
        )

    def _complete_read_tab(self: Any, result: NotificationMutationResult) -> None:
        """Apply a completed tab-scoped read mutation on the UI thread."""
        self._request_authoritative_notification_refresh()
        if not result.success:
            self.notify(f"Could not mark tab read: {result.message}", severity="error")
            return
        if not self._notification_modal_still_active():
            return

        acted_ids = set(result.ids)
        current = self._get_highlighted_notification()
        preferred_id = current.id if current is not None else None
        for notification in self._notifications:
            if notification.id in acted_ids:
                notification.read = True

        highlight = self._visible_notification_index_for_id(preferred_id)
        if highlight is None:
            highlight = self._first_visible_notification_index()
        self._rebuild_list(highlight_index=highlight)
