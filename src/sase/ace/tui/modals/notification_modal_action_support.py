"""Shared infrastructure for notification modal state actions."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sase.ace.tui.actions.proc_actions import (
    TrackedProcCompletion,
    TrackedProcResult,
)

from .notification_modal_action_types import (
    NotificationMutationResult,
    NotificationTargetSelection,
)


class NotificationActionSupportMixin:
    """Target selection, task dispatch, and refresh helpers for modal actions."""

    def _resolve_notification_state_targets(
        self: Any,
    ) -> NotificationTargetSelection:
        """Resolve marks or the highlighted row to stable notification ids."""
        if self._marked_notification_ids:
            live_ids = tuple(
                n.id
                for n in self._notifications
                if n.id in self._marked_notification_ids
            )
            if live_ids:
                return NotificationTargetSelection(live_ids, True)
            self._marked_notification_ids.clear()

        idx = self._get_selected_index()
        if idx is None or idx >= len(self._notifications):
            return NotificationTargetSelection((), False)
        return NotificationTargetSelection((self._notifications[idx].id,), False)

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
        task: Callable[[], NotificationMutationResult],
        on_complete: Callable[[NotificationMutationResult], None],
    ) -> bool:
        """Run a notification state write through the app task queue when present."""

        def _task() -> TrackedProcResult[NotificationMutationResult]:
            result = task()
            return TrackedProcResult(
                success=result.success,
                message=result.message,
                payload=result,
                error=None if result.success else result.message,
            )

        def _on_complete(
            completion: TrackedProcCompletion[NotificationMutationResult],
        ) -> None:
            result = completion.payload
            if result is None:
                result = NotificationMutationResult(
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
        submit = getattr(app, "_submit_tracked_proc", None)
        if callable(submit):
            proc_info = submit(
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
            return proc_info is not None

        result = _task()
        if result.payload is not None:
            on_complete(result.payload)
        elif not result.success:
            on_complete(
                NotificationMutationResult(
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

    def _request_authoritative_notification_refresh(self: Any) -> None:
        """Refresh ACE's snapshot/deadline cache after a modal mutation."""
        try:
            app = self.app
        except Exception:
            return
        schedule = getattr(app, "_schedule_notification_poll", None)
        if callable(schedule):
            schedule(source="mutation")
            return
        schedule = getattr(app, "_schedule_notification_snapshot_refresh", None)
        if callable(schedule):
            schedule()

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
