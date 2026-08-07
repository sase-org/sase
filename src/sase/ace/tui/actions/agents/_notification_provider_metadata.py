"""Shared snapshot metadata helpers for ACE notification provider reads."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from sase.notifications.models import Notification

from ...provider_contract import (
    AceDeltaBatch,
    AceFallbackMetadata,
    AceProviderCapabilities,
    AceProviderInfo,
    AceRowHandle,
    AceSnapshot,
    make_snapshot,
    trace_provider_snapshot,
)
from ._notification_provider_models import (
    AceNotificationCountSnapshot,
    AceNotificationCounts,
    AceNotificationDetail,
    AceNotificationPage,
    AceNotificationPendingActions,
    AceNotificationSnapshot,
)

if TYPE_CHECKING:
    from ...modals.notification_modal_tags import NotificationTagTab


def apply_notification_count_delta(
    counts: AceNotificationCounts,
    delta: AceDeltaBatch[Any],
) -> AceNotificationCounts:
    """Apply notification count patches without reparsing the JSONL store."""

    values = {
        "priority": counts.priority,
        "errors": counts.errors,
        "rest": counts.rest,
        "muted": counts.muted,
    }
    for patch in delta.count_patches:
        if patch.key in values:
            values[patch.key] = max(0, int(patch.value))
    return AceNotificationCounts(**values)


def notification_row_handle(notification: Notification) -> AceRowHandle:
    """Return the stable ACE row handle for a notification row."""

    handle = f"notification:{notification.id}"
    return AceRowHandle(
        surface="notifications",
        stable_id=handle,
        daemon_handle=handle,
        local_identity=notification.id,
    )


def notification_snapshot_with_shared_metadata(
    snapshot: AceNotificationSnapshot,
    *,
    provider_source: str,
    prefers_daemon: bool,
    fallback_reason: str | None,
    fallback_message: str | None,
    snapshot_id: str | None,
    page_count: int,
) -> AceNotificationSnapshot:
    shared_snapshot: AceSnapshot[Notification] = make_snapshot(
        surface="notifications",
        rows=snapshot.notifications,
        row_handles=[
            notification_row_handle(notification)
            for notification in snapshot.notifications
        ],
        provider=AceProviderInfo(
            identity=f"notifications:{provider_source}",
            surface="notifications",
            source=provider_source,
            prefers_daemon=prefers_daemon,
            capabilities=AceProviderCapabilities(
                pages=provider_source == "daemon",
                counts=True,
            ),
            fallback=AceFallbackMetadata(fallback_reason, fallback_message),
        ),
        snapshot_id=snapshot_id,
        page_count=page_count,
        facets={
            "priority": snapshot.counts.priority,
            "errors": snapshot.counts.errors,
            "rest": snapshot.counts.rest,
            "muted": snapshot.counts.muted,
        },
        full_reload=True,
    )
    trace_provider_snapshot(shared_snapshot)
    return AceNotificationSnapshot(
        notifications=snapshot.notifications,
        counts=snapshot.counts,
        tabs=snapshot.tabs,
        expired_ids=snapshot.expired_ids,
        next_snooze_deadline=snapshot.next_snooze_deadline,
        shared_snapshot=shared_snapshot,
    )


def notification_count_snapshot_from_counts(
    counts: Mapping[str, Any],
    *,
    tabs: Sequence[NotificationTagTab] = (),
    provider_source: str,
    prefers_daemon: bool,
    fallback_reason: str | None,
    fallback_message: str | None,
) -> AceNotificationCountSnapshot:
    normalized = AceNotificationCounts(
        priority=int(counts.get("priority", 0)),
        errors=int(counts.get("errors", 0)),
        rest=int(counts.get("rest", 0)),
        muted=int(counts.get("muted", 0)),
    )
    shared_snapshot: AceSnapshot[Notification] = make_snapshot(
        surface="notification_counts",
        rows=[],
        row_handles=[],
        provider=AceProviderInfo(
            identity=f"notification_counts:{provider_source}",
            surface="notification_counts",
            source=provider_source,
            prefers_daemon=prefers_daemon,
            capabilities=AceProviderCapabilities(counts=True),
            fallback=AceFallbackMetadata(fallback_reason, fallback_message),
        ),
        snapshot_id=None,
        page_count=0,
        facets={
            "priority": normalized.priority,
            "errors": normalized.errors,
            "rest": normalized.rest,
            "muted": normalized.muted,
        },
        full_reload=False,
    )
    trace_provider_snapshot(shared_snapshot)
    return AceNotificationCountSnapshot(
        counts=normalized,
        tabs=list(tabs),
        shared_snapshot=shared_snapshot,
    )


def notification_page_with_shared_metadata(
    page: AceNotificationPage,
    *,
    provider_source: str,
    prefers_daemon: bool,
    fallback_reason: str | None,
    fallback_message: str | None,
    snapshot_id: str | None,
    page_count: int,
) -> AceNotificationPage:
    shared_snapshot = make_snapshot(
        surface="notifications",
        rows=page.notifications,
        row_handles=[
            notification_row_handle(notification) for notification in page.notifications
        ],
        provider=AceProviderInfo(
            identity=f"notifications:{provider_source}",
            surface="notifications",
            source=provider_source,
            prefers_daemon=prefers_daemon,
            capabilities=AceProviderCapabilities(
                pages=provider_source == "daemon",
                counts=True,
                lazy_details=provider_source == "daemon",
            ),
            fallback=AceFallbackMetadata(fallback_reason, fallback_message),
        ),
        snapshot_id=snapshot_id,
        page_count=page_count,
        next_cursor=page.next_cursor,
        facets={
            "priority": page.counts.priority,
            "errors": page.counts.errors,
            "rest": page.counts.rest,
            "muted": page.counts.muted,
        },
        metadata={"bounded": page.bounded, "truncated": page.truncated},
        full_reload=provider_source != "daemon",
    )
    trace_provider_snapshot(shared_snapshot)
    return AceNotificationPage(
        notifications=page.notifications,
        counts=page.counts,
        next_cursor=page.next_cursor,
        shared_snapshot=shared_snapshot,
        bounded=page.bounded,
        truncated=page.truncated,
    )


def notification_detail_with_shared_metadata(
    detail: AceNotificationDetail,
    *,
    provider_source: str,
    prefers_daemon: bool,
    fallback_reason: str | None,
    fallback_message: str | None,
    snapshot_id: str | None,
) -> AceNotificationDetail:
    rows = [] if detail.notification is None else [detail.notification]
    shared_snapshot = make_snapshot(
        surface="notification_detail",
        rows=rows,
        row_handles=[notification_row_handle(notification) for notification in rows],
        provider=AceProviderInfo(
            identity=f"notification_detail:{provider_source}",
            surface="notification_detail",
            source=provider_source,
            prefers_daemon=prefers_daemon,
            capabilities=AceProviderCapabilities(
                lazy_details=provider_source == "daemon"
            ),
            fallback=AceFallbackMetadata(fallback_reason, fallback_message),
        ),
        snapshot_id=snapshot_id,
        page_count=1 if rows else 0,
        metadata={"bounded": detail.bounded, "truncated": detail.truncated},
        full_reload=False,
    )
    trace_provider_snapshot(shared_snapshot)
    return AceNotificationDetail(
        notification=detail.notification,
        shared_snapshot=shared_snapshot,
        bounded=detail.bounded,
        truncated=detail.truncated,
    )


def pending_actions_with_shared_metadata(
    pending: AceNotificationPendingActions,
    *,
    provider_source: str,
    prefers_daemon: bool,
    fallback_reason: str | None,
    fallback_message: str | None,
    snapshot_id: str | None,
) -> AceNotificationPendingActions:
    row_handles = [
        AceRowHandle(
            surface="notification_pending_actions",
            stable_id=f"notification_action:{action.get('prefix', index)}",
            daemon_handle=f"notification_action:{action.get('prefix', index)}",
            local_identity=str(action.get("prefix", index)),
        )
        for index, action in enumerate(pending.actions)
    ]
    shared_snapshot = make_snapshot(
        surface="notification_pending_actions",
        rows=pending.actions,
        row_handles=row_handles,
        provider=AceProviderInfo(
            identity=f"notification_pending_actions:{provider_source}",
            surface="notification_pending_actions",
            source=provider_source,
            prefers_daemon=prefers_daemon,
            capabilities=AceProviderCapabilities(
                pages=provider_source == "daemon",
                lazy_details=provider_source == "daemon",
            ),
            fallback=AceFallbackMetadata(fallback_reason, fallback_message),
        ),
        snapshot_id=snapshot_id,
        page_count=1,
        metadata={"bounded": pending.bounded, "truncated": pending.truncated},
        full_reload=provider_source != "daemon",
    )
    trace_provider_snapshot(shared_snapshot)
    return AceNotificationPendingActions(
        store=pending.store,
        actions=pending.actions,
        shared_snapshot=shared_snapshot,
        bounded=pending.bounded,
        truncated=pending.truncated,
    )


def count_value(counts: Any, key: str) -> int:
    if isinstance(counts, dict):
        return int(counts.get(key, 0))
    return int(getattr(counts, key, 0))


def counts_mapping(counts: Any) -> dict[str, int]:
    return {
        "priority": count_value(counts, "priority"),
        "errors": count_value(counts, "errors"),
        "rest": count_value(counts, "rest"),
        "muted": count_value(counts, "muted"),
    }


def counts_from_notifications(notifications: list[Any]) -> dict[str, int]:
    from sase.notifications.priority import is_error, is_priority

    counts = {"priority": 0, "errors": 0, "rest": 0, "muted": 0}
    for notification in notifications:
        if notification.read or notification.silent:
            continue
        if notification.muted:
            counts["muted"] += 1
        elif is_error(notification):
            counts["errors"] += 1
        elif is_priority(notification):
            counts["priority"] += 1
        else:
            counts["rest"] += 1
    return counts


__all__ = [
    "apply_notification_count_delta",
    "count_value",
    "counts_from_notifications",
    "counts_mapping",
    "notification_count_snapshot_from_counts",
    "notification_detail_with_shared_metadata",
    "notification_page_with_shared_metadata",
    "notification_row_handle",
    "notification_snapshot_with_shared_metadata",
    "pending_actions_with_shared_metadata",
]
