"""Shared infrastructure for notification modal state actions."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from sase.ace.tui.actions._durable_ops import (
    durable_fingerprint,
    durable_request_payload,
    sase_argv,
)
from sase.ops.names import NOTIFY_APPLY_STATE

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
        action: str,
        ids: tuple[str, ...],
        on_complete: Callable[[NotificationMutationResult], None],
        cancelled_snoozes: bool = False,
        description: str = "",
        muted: bool | None = None,
        snooze_until: str | None = None,
        tab_key: str | None = None,
    ) -> bool:
        """Run a notification state write through a durable CLI operation."""

        def _on_complete(completion: Any) -> None:
            result = _notification_result_from_completion(
                completion,
                fallback_action=action,
                fallback_ids=ids,
                fallback_muted=muted,
                fallback_snooze_until=snooze_until,
                fallback_description=description,
                fallback_cancelled_snoozes=cancelled_snoozes,
            )
            on_complete(result)

        try:
            app = self.app
        except Exception:
            app = None
        submit = getattr(app, "_submit_durable_proc", None)
        if callable(submit):
            proc_info = submit(
                _notification_state_argv(action, ids, tab_key=tab_key),
                operation=NOTIFY_APPLY_STATE,
                request=durable_request_payload(
                    cancelled_snoozes=cancelled_snoozes,
                    description=description,
                    ids=list(ids),
                    muted=muted,
                    tab_key=tab_key,
                    until=snooze_until,
                ),
                request_fingerprint=durable_fingerprint(
                    NOTIFY_APPLY_STATE,
                    action,
                    ",".join(ids),
                    snooze_until or "",
                    tab_key or "",
                ),
                concurrency_keys=("notification-state",),
                label=label,
                display_name=label,
                cl_name="notifications",
                project_file="",
                on_complete=_on_complete,
                reload_on_complete=False,
                notify_on_complete=False,
            )
            return proc_info is not None

        on_complete(
            _run_notification_state_direct(
                action=action,
                ids=ids,
                cancelled_snoozes=cancelled_snoozes,
                description=description,
                muted=muted,
                snooze_until=snooze_until,
                tab_key=tab_key,
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


def _notification_state_argv(
    action: str,
    ids: tuple[str, ...],
    *,
    tab_key: str | None = None,
) -> list[str]:
    if tab_key or len(ids) != 1:
        return sase_argv("notify", "apply-state-many", action)
    return sase_argv("notify", "apply-state", ids[0], action)


def _notification_result_from_completion(
    completion: Any,
    *,
    fallback_action: str,
    fallback_ids: tuple[str, ...],
    fallback_muted: bool | None,
    fallback_snooze_until: str | None,
    fallback_description: str,
    fallback_cancelled_snoozes: bool,
) -> NotificationMutationResult:
    payload = getattr(completion, "payload", None)
    if not isinstance(payload, dict):
        return NotificationMutationResult(
            action=_result_action(fallback_action),
            ids=fallback_ids,
            success=False,
            message=str(
                getattr(completion, "error", None) or getattr(completion, "message", "")
            ),
            muted=fallback_muted,
            snooze_until=fallback_snooze_until,
            description=fallback_description,
            cancelled_snoozes=fallback_cancelled_snoozes,
        )
    raw_ids = payload.get("ids")
    result_ids = (
        tuple(str(item) for item in raw_ids)
        if isinstance(raw_ids, list)
        else fallback_ids
    )
    muted = payload.get("muted")
    return NotificationMutationResult(
        action=_result_action(str(payload.get("action") or fallback_action)),
        ids=result_ids,
        success=bool(getattr(completion, "success", False)),
        message=str(getattr(completion, "message", "")),
        matched_count=_int_payload(payload.get("matched_count")),
        muted=muted if isinstance(muted, bool) else fallback_muted,
        snooze_until=(
            str(payload["snooze_until"])
            if isinstance(payload.get("snooze_until"), str)
            else fallback_snooze_until
        ),
        description=str(payload.get("description") or fallback_description),
        cancelled_snoozes=bool(
            payload.get("cancelled_snoozes", fallback_cancelled_snoozes)
        ),
    )


def _run_notification_state_direct(
    *,
    action: str,
    ids: tuple[str, ...],
    cancelled_snoozes: bool,
    description: str,
    muted: bool | None,
    snooze_until: str | None,
    tab_key: str | None,
) -> NotificationMutationResult:
    from datetime import datetime

    from sase.notifications.store import (
        mark_many_dismissed,
        mark_many_muted,
        mark_many_snoozed,
        mark_read,
        mark_tab_read,
    )

    try:
        if action == "read" and tab_key:
            matched = mark_tab_read(tab_key)
            success = matched > 0
        elif action == "read":
            matched = sum(1 for notification_id in ids if mark_read(notification_id))
            success = matched == len(ids)
        elif action == "dismiss":
            matched = mark_many_dismissed(ids)
            success = matched == len(ids)
        elif action == "mute":
            matched = mark_many_muted(ids, True)
            success = matched == len(ids)
        elif action == "unmute":
            matched = mark_many_muted(ids, False)
            success = matched == len(ids)
        elif action == "snooze" and snooze_until:
            matched = mark_many_snoozed(ids, datetime.fromisoformat(snooze_until))
            success = matched == len(ids)
        else:
            return NotificationMutationResult(
                action=_result_action(action),
                ids=ids,
                success=False,
                message=f"Unsupported notification action: {action}",
            )
    except Exception as exc:
        return NotificationMutationResult(
            action=_result_action(action),
            ids=ids,
            success=False,
            message=str(exc),
            muted=muted,
            snooze_until=snooze_until,
            description=description,
            cancelled_snoozes=cancelled_snoozes,
        )
    return NotificationMutationResult(
        action=_result_action(action),
        ids=ids,
        success=success,
        message=(
            f"Applied {action} to {matched} notification(s)"
            if success
            else "one or more notifications are stale or no longer exist"
        ),
        matched_count=matched,
        muted=muted,
        snooze_until=snooze_until,
        description=description,
        cancelled_snoozes=cancelled_snoozes,
    )


def _result_action(action: str) -> Literal["mute", "snooze", "read"]:
    if action == "unmute":
        return "mute"
    if action == "mute":
        return "mute"
    if action == "snooze":
        return "snooze"
    if action == "read":
        return "read"
    return "read"


def _int_payload(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0
