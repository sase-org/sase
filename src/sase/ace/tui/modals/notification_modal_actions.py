"""State-changing actions for the notification modal."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from sase.ace.tui.actions.task_actions import (
    TrackedTaskCompletion,
    TrackedTaskResult,
)
from sase.core.time import get_timezone
from sase.notification_gates.registry import PRIVILEGED_GATE_ACTIONS

from .snooze_duration_modal import SnoozeDurationModal


@dataclass(frozen=True)
class _NotificationTargetSelection:
    ids: tuple[str, ...]
    from_marks: bool


@dataclass(frozen=True)
class _NotificationMutationResult:
    action: Literal["mute", "snooze"]
    ids: tuple[str, ...]
    success: bool
    message: str
    matched_count: int = 0
    muted: bool | None = None
    snooze_until: str | None = None
    description: str = ""
    cancelled_snoozes: bool = False


class NotificationStateActionsMixin:
    """Dismiss, mute, snooze, and read notification rows."""

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

    def _resolve_notification_state_targets(
        self: Any,
    ) -> _NotificationTargetSelection:
        """Resolve marks or the highlighted row to stable notification ids."""
        if self._marked_notification_ids:
            live_ids = tuple(
                n.id
                for n in self._notifications
                if n.id in self._marked_notification_ids
            )
            if live_ids:
                return _NotificationTargetSelection(live_ids, True)
            self._marked_notification_ids.clear()

        idx = self._get_selected_index()
        if idx is None or idx >= len(self._notifications):
            return _NotificationTargetSelection((), False)
        return _NotificationTargetSelection((self._notifications[idx].id,), False)

    def _live_notifications_for_ids(
        self: Any, notification_ids: tuple[str, ...]
    ) -> list[Any]:
        """Return currently live notifications for ids in modal dataset order."""
        id_set = set(notification_ids)
        return [n for n in self._notifications if n.id in id_set]

    def _submit_notification_state_task(
        self: Any,
        *,
        label: str,
        task: Callable[[], _NotificationMutationResult],
        on_complete: Callable[[_NotificationMutationResult], None],
    ) -> bool:
        """Run a notification state write through the app task queue when present."""

        def _task() -> TrackedTaskResult[_NotificationMutationResult]:
            result = task()
            return TrackedTaskResult(
                success=result.success,
                message=result.message,
                payload=result,
                error=None if result.success else result.message,
            )

        def _on_complete(
            completion: TrackedTaskCompletion[_NotificationMutationResult],
        ) -> None:
            result = completion.payload
            if result is None:
                result = _NotificationMutationResult(
                    action="mute",
                    ids=(),
                    success=False,
                    message=completion.error or completion.message,
                )
            on_complete(result)

        try:
            app = self.app
        except Exception:
            app = None
        submit = getattr(app, "_submit_tracked_task", None)
        if callable(submit):
            task_info = submit(
                "notification",
                "notifications",
                "",
                _task,
                display_name=label,
                dedup_key="notification-state",
                exclusive_scopes=("notification-state",),
                duplicate_message="A notification update is already running",
                on_complete=_on_complete,
                reload_on_complete=False,
                notify_on_complete=False,
            )
            return task_info is not None

        result = _task()
        if result.payload is not None:
            on_complete(result.payload)
        elif not result.success:
            on_complete(
                _NotificationMutationResult(
                    action="mute",
                    ids=(),
                    success=False,
                    message=result.error or result.message,
                )
            )
        return True

    def _notification_modal_still_active(self: Any) -> bool:
        """Return whether it is reasonable to touch modal widgets."""
        try:
            app = self.app
        except Exception:
            return True
        screen = getattr(app, "screen", None)
        if screen is self:
            return True
        stack = getattr(app, "screen_stack", None)
        if isinstance(stack, (list, tuple)) and stack:
            return self in stack
        return screen is None

    def _rebuild_after_bulk_notification_reclassification(
        self: Any,
        *,
        previous_tabs: Any,
        replacement_notification_id: str | None,
        preferred_notification_id: str | None,
    ) -> None:
        """Rebuild after multiple rows may have moved between tabs."""
        previous_active_tag = self._active_notification_tag
        self._coerce_active_notification_tag(previous_tabs=previous_tabs)
        tab_switched = self._active_notification_tag != previous_active_tag
        if tab_switched:
            highlight = self._first_visible_notification_index()
        else:
            highlight = self._visible_notification_index_for_id(
                preferred_notification_id
            )
            if highlight is None:
                highlight = self._visible_notification_index_for_id(
                    replacement_notification_id
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
        del self._notifications[start_idx:end_idx]
        self._coerce_active_notification_tag(previous_tabs=previous_tabs)
        highlight = min(start_idx, len(self._notifications) - 1)
        self._rebuild_list(highlight_index=highlight if highlight >= 0 else None)
        return len(notification_ids)

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

        def _task() -> _NotificationMutationResult:
            try:
                matched = self._mark_many_muted(list(ids), new_muted)
            except Exception as exc:
                return _NotificationMutationResult(
                    action="mute",
                    ids=ids,
                    success=False,
                    message=str(exc),
                    muted=new_muted,
                    cancelled_snoozes=cancelled_snoozes,
                )
            return _NotificationMutationResult(
                action="mute",
                ids=ids,
                success=True,
                message="Notifications updated",
                matched_count=matched,
                muted=new_muted,
                cancelled_snoozes=cancelled_snoozes,
            )

        self._submit_notification_state_task(
            label="Update notifications",
            task=_task,
            on_complete=self._complete_bulk_toggle_mute,
        )

    def _complete_bulk_toggle_mute(
        self: Any, result: _NotificationMutationResult
    ) -> None:
        """Apply a completed bulk mute/unmute mutation on the UI thread."""
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
        notification = self._notifications[idx]

        def _on_picked(result: timedelta | datetime | None) -> None:
            if result is None:
                self.notify("Snooze cancelled")
                return
            previous_tabs = self._tag_tabs()
            replacement_id = self._replacement_notification_id_after_reclassification(
                idx
            )
            if isinstance(result, datetime):
                snooze_until = result
                description = "until tomorrow morning"
            else:
                snooze_until = datetime.now(get_timezone()) + result
                description = f"for {self._format_delta(result)}"

            self._mark_snoozed(notification.id, snooze_until)
            notification.muted = True
            notification.snooze_until = snooze_until.isoformat()

            self._rebuild_after_notification_reclassification(
                previous_tabs=previous_tabs,
                changed_notification_id=notification.id,
                replacement_notification_id=replacement_id,
            )
            self.notify(f"Snoozed {description}")

        self.app.push_screen(SnoozeDurationModal(), callback=_on_picked)

    def _push_bulk_snooze_picker(self: Any, notification_ids: tuple[str, ...]) -> None:
        """Open one picker for a mark-targeted snooze operation."""

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
            self._dispatch_bulk_snooze(
                notification_ids,
                snooze_until=snooze_until,
                description=description,
            )

        self.app.push_screen(SnoozeDurationModal(), callback=_on_picked)

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

        def _task() -> _NotificationMutationResult:
            try:
                matched = self._mark_many_snoozed(list(ids), snooze_until)
            except Exception as exc:
                return _NotificationMutationResult(
                    action="snooze",
                    ids=ids,
                    success=False,
                    message=str(exc),
                    snooze_until=snooze_until.isoformat(),
                    description=description,
                )
            return _NotificationMutationResult(
                action="snooze",
                ids=ids,
                success=True,
                message="Notifications snoozed",
                matched_count=matched,
                snooze_until=snooze_until.isoformat(),
                description=description,
            )

        self._submit_notification_state_task(
            label="Snooze notifications",
            task=_task,
            on_complete=self._complete_bulk_snooze,
        )

    def _complete_bulk_snooze(self: Any, result: _NotificationMutationResult) -> None:
        """Apply a completed bulk snooze mutation on the UI thread."""
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

    def action_read_all(self: Any) -> None:
        """Mark all notifications as read and rebuild the display."""
        self._mark_all_read()

        for n in self._notifications:
            n.read = True

        self._rebuild_list()
