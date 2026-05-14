"""ACE notification read provider helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sase.daemon.client import LOCAL_DAEMON_DEFAULT_PAGE_LIMIT, LocalDaemonClient
from sase.daemon.read_facade import DaemonReadResult, read_or_fallback
from sase.daemon.read_models import (
    notification_counts_from_dict,
    notification_list_from_dict,
)
from sase.notifications.models import Notification

from ...provider_contract import (
    AceFallbackMetadata,
    AceProviderCapabilities,
    AceProviderInfo,
    AceRowHandle,
    AceSnapshot,
    make_snapshot,
    trace_provider_snapshot,
)


@dataclass(frozen=True)
class _AceNotificationCounts:
    """Notification count shape consumed by ACE indicator code."""

    priority: int = 0
    errors: int = 0
    rest: int = 0
    muted: int = 0


@dataclass(frozen=True)
class _AceNotificationSnapshot:
    """Notification snapshot shape consumed by ACE notification code."""

    notifications: list[Notification] = field(default_factory=list)
    counts: _AceNotificationCounts = field(default_factory=_AceNotificationCounts)
    expired_ids: list[str] = field(default_factory=list)
    shared_snapshot: AceSnapshot[Notification] | None = None


def read_notification_snapshot_for_tui(
    *,
    include_dismissed: bool = False,
    expire_due_snoozes: bool = False,
    args: Any | None = None,
    client: LocalDaemonClient | None = None,
) -> DaemonReadResult[Any]:
    """Return the ACE notification snapshot through daemon reads when possible."""

    from sase.notifications import read_notification_snapshot

    result = read_or_fallback(
        "notification_list",
        args=args,
        client=client,
        daemon_loader=lambda daemon: _daemon_notification_snapshot(
            daemon,
            include_dismissed=include_dismissed,
            expire_due_snoozes=expire_due_snoozes,
        ),
        direct_loader=lambda: _notification_snapshot_from_direct(
            read_notification_snapshot(
                include_dismissed,
                expire_due_snoozes,
            )
        ),
    )
    if result.used_daemon:
        return result
    return DaemonReadResult(
        value=_notification_snapshot_with_shared_metadata(
            result.value,
            provider_source="direct_fallback",
            prefers_daemon=True,
            fallback_reason=result.fallback_reason,
            fallback_message=result.fallback_message,
            snapshot_id=(
                result.value.shared_snapshot.snapshot_id
                if result.value.shared_snapshot is not None
                else None
            ),
            page_count=(
                int(result.value.shared_snapshot.metadata.get("page_count", 1))
                if result.value.shared_snapshot is not None
                else 1
            ),
        ),
        surface=result.surface,
        used_daemon=False,
        fallback_reason=result.fallback_reason,
        fallback_message=result.fallback_message,
    )


def _daemon_notification_snapshot(
    client: LocalDaemonClient,
    *,
    include_dismissed: bool,
    expire_due_snoozes: bool,
) -> _AceNotificationSnapshot:
    notifications = []
    cursor: str | None = None
    snapshot_id: str | None = None
    page_count = 0
    while True:
        page = notification_list_from_dict(
            client.notification_list(
                include_dismissed=include_dismissed,
                limit=LOCAL_DAEMON_DEFAULT_PAGE_LIMIT,
                cursor=cursor,
            )
        )
        page_count += 1
        snapshot_id = snapshot_id or page.snapshot.snapshot_id
        notifications.extend(page.notifications)
        cursor = page.page.next_cursor
        if not cursor:
            break

    counts = notification_counts_from_dict(client.notification_counts()).counts
    expired_ids: list[str] = []
    if expire_due_snoozes:
        from sase.notifications.store import expire_due_snoozes as expire_rows

        expired = expire_rows(notifications)
        expired_ids = [notification.id for notification in expired]
        if expired_ids:
            counts = _counts_from_notifications(notifications)
    snapshot = _AceNotificationSnapshot(
        notifications=notifications,
        counts=_AceNotificationCounts(
            priority=int(counts.get("priority", 0)),
            errors=int(counts.get("errors", 0)),
            rest=int(counts.get("rest", 0)),
            muted=int(counts.get("muted", 0)),
        ),
        expired_ids=expired_ids,
    )
    return _notification_snapshot_with_shared_metadata(
        snapshot,
        provider_source="daemon",
        prefers_daemon=True,
        fallback_reason=None,
        fallback_message=None,
        snapshot_id=snapshot_id,
        page_count=page_count,
    )


# pyvision: sdd/epics/202605/rust_daemon_epic9_ace_ui_virtualization.md
def notification_row_handle(notification: Notification) -> AceRowHandle:
    """Return the stable ACE row handle for a notification row."""

    handle = f"notification:{notification.id}"
    return AceRowHandle(
        surface="notifications",
        stable_id=handle,
        daemon_handle=handle,
        local_identity=notification.id,
    )


def _notification_snapshot_from_direct(snapshot: Any) -> _AceNotificationSnapshot:
    counts = getattr(snapshot, "counts", _AceNotificationCounts())
    notifications = list(getattr(snapshot, "notifications", []))
    expired_ids = list(getattr(snapshot, "expired_ids", []))
    normalized = _AceNotificationSnapshot(
        notifications=notifications,
        counts=_AceNotificationCounts(
            priority=_count_value(counts, "priority"),
            errors=_count_value(counts, "errors"),
            rest=_count_value(counts, "rest"),
            muted=_count_value(counts, "muted"),
        ),
        expired_ids=expired_ids,
    )
    return _notification_snapshot_with_shared_metadata(
        normalized,
        provider_source="direct",
        prefers_daemon=False,
        fallback_reason=None,
        fallback_message=None,
        snapshot_id=None,
        page_count=1,
    )


def _notification_snapshot_with_shared_metadata(
    snapshot: _AceNotificationSnapshot,
    *,
    provider_source: str,
    prefers_daemon: bool,
    fallback_reason: str | None,
    fallback_message: str | None,
    snapshot_id: str | None,
    page_count: int,
) -> _AceNotificationSnapshot:
    shared_snapshot = make_snapshot(
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
    return _AceNotificationSnapshot(
        notifications=snapshot.notifications,
        counts=snapshot.counts,
        expired_ids=snapshot.expired_ids,
        shared_snapshot=shared_snapshot,
    )


def _count_value(counts: Any, key: str) -> int:
    if isinstance(counts, dict):
        return int(counts.get(key, 0))
    return int(getattr(counts, key, 0))


def _counts_from_notifications(notifications: list[Any]) -> dict[str, int]:
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
    "notification_row_handle",
    "read_notification_snapshot_for_tui",
]
