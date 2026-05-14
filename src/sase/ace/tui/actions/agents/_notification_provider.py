"""ACE notification read provider helpers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from sase.daemon.client import LOCAL_DAEMON_DEFAULT_PAGE_LIMIT, LocalDaemonClient
from sase.daemon.read_facade import DaemonReadResult, read_or_fallback
from sase.daemon.read_models import (
    NotificationPendingActionsRead,
    notification_counts_from_dict,
    notification_detail_from_dict,
    notification_list_from_dict,
    notification_pending_actions_from_dict,
)
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


@dataclass(frozen=True)
class _AceNotificationCountSnapshot:
    """Count-only notification provider result for the persistent indicator."""

    counts: _AceNotificationCounts = field(default_factory=_AceNotificationCounts)
    shared_snapshot: AceSnapshot[Notification] | None = None


@dataclass(frozen=True)
class _AceNotificationPage:
    """One modal/list page from the notification provider."""

    notifications: list[Notification] = field(default_factory=list)
    counts: _AceNotificationCounts = field(default_factory=_AceNotificationCounts)
    next_cursor: str | None = None
    shared_snapshot: AceSnapshot[Notification] | None = None
    bounded: bool = False
    truncated: bool = False


@dataclass(frozen=True)
class _AceNotificationDetail:
    """Selected notification detail payload."""

    notification: Notification | None = None
    shared_snapshot: AceSnapshot[Notification] | None = None
    bounded: bool = False
    truncated: bool = False


@dataclass(frozen=True)
class _AceNotificationPendingActions:
    """Pending notification action/detail payload."""

    store: dict[str, Any] = field(default_factory=dict)
    actions: list[dict[str, Any]] = field(default_factory=list)
    shared_snapshot: AceSnapshot[dict[str, Any]] | None = None
    bounded: bool = False
    truncated: bool = False


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


def read_notification_counts_for_tui(
    *,
    args: Any | None = None,
    client: LocalDaemonClient | None = None,
) -> DaemonReadResult[_AceNotificationCountSnapshot]:
    """Return count-only notification data for the ACE indicator."""

    result = read_or_fallback(
        "notification_counts",
        args=args,
        client=client,
        daemon_loader=lambda daemon: _notification_count_snapshot_from_counts(
            notification_counts_from_dict(daemon.notification_counts()).counts,
            provider_source="daemon",
            prefers_daemon=True,
            fallback_reason=None,
            fallback_message=None,
        ),
        direct_loader=_direct_notification_count_snapshot,
    )
    if result.used_daemon:
        return result
    return DaemonReadResult(
        value=_notification_count_snapshot_from_counts(
            _counts_mapping(result.value.counts),
            provider_source="direct_fallback",
            prefers_daemon=True,
            fallback_reason=result.fallback_reason,
            fallback_message=result.fallback_message,
        ),
        surface=result.surface,
        used_daemon=False,
        fallback_reason=result.fallback_reason,
        fallback_message=result.fallback_message,
    )


def read_unread_notification_page_for_tui(
    *,
    include_dismissed: bool = False,
    limit: int = LOCAL_DAEMON_DEFAULT_PAGE_LIMIT,
    cursor: str | None = None,
    args: Any | None = None,
    client: LocalDaemonClient | None = None,
) -> DaemonReadResult[_AceNotificationPage]:
    """Return one unread notification modal page with direct fallback."""

    result = read_or_fallback(
        "notification_list",
        args=args,
        client=client,
        daemon_loader=lambda daemon: _daemon_unread_notification_page(
            daemon,
            include_dismissed=include_dismissed,
            limit=limit,
            cursor=cursor,
        ),
        direct_loader=lambda: _direct_unread_notification_page(
            include_dismissed=include_dismissed,
            limit=limit,
        ),
    )
    if result.used_daemon:
        return result
    return DaemonReadResult(
        value=_notification_page_with_shared_metadata(
            result.value,
            provider_source="direct_fallback",
            prefers_daemon=True,
            fallback_reason=result.fallback_reason,
            fallback_message=result.fallback_message,
            snapshot_id=None,
            page_count=1,
        ),
        surface=result.surface,
        used_daemon=False,
        fallback_reason=result.fallback_reason,
        fallback_message=result.fallback_message,
    )


def read_notification_detail_for_tui(
    notification_id: str,
    *,
    args: Any | None = None,
    client: LocalDaemonClient | None = None,
) -> DaemonReadResult[_AceNotificationDetail]:
    """Return selected notification detail with bounded payload metadata."""

    result = read_or_fallback(
        "notification_detail",
        args=args,
        client=client,
        daemon_loader=lambda daemon: _daemon_notification_detail(
            daemon,
            notification_id,
        ),
        direct_loader=lambda: _direct_notification_detail(notification_id),
    )
    if result.used_daemon:
        return result
    return DaemonReadResult(
        value=_notification_detail_with_shared_metadata(
            result.value,
            provider_source="direct_fallback",
            prefers_daemon=True,
            fallback_reason=result.fallback_reason,
            fallback_message=result.fallback_message,
            snapshot_id=None,
        ),
        surface=result.surface,
        used_daemon=False,
        fallback_reason=result.fallback_reason,
        fallback_message=result.fallback_message,
    )


def read_notification_pending_actions_for_tui(
    *,
    args: Any | None = None,
    client: LocalDaemonClient | None = None,
) -> DaemonReadResult[_AceNotificationPendingActions]:
    """Return pending HITL/plan/question action details through the provider."""

    result = read_or_fallback(
        "notification_pending_actions",
        args=args,
        client=client,
        daemon_loader=lambda daemon: _pending_actions_from_daemon(
            notification_pending_actions_from_dict(
                daemon.notification_pending_actions()
            )
        ),
        direct_loader=_direct_pending_actions,
    )
    if result.used_daemon:
        return result
    return DaemonReadResult(
        value=_pending_actions_with_shared_metadata(
            result.value,
            provider_source="direct_fallback",
            prefers_daemon=True,
            fallback_reason=result.fallback_reason,
            fallback_message=result.fallback_message,
            snapshot_id=None,
        ),
        surface=result.surface,
        used_daemon=False,
        fallback_reason=result.fallback_reason,
        fallback_message=result.fallback_message,
    )


def apply_notification_count_delta(
    counts: _AceNotificationCounts,
    delta: AceDeltaBatch[Any],
) -> _AceNotificationCounts:
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
    return _AceNotificationCounts(**values)


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


def _daemon_unread_notification_page(
    client: LocalDaemonClient,
    *,
    include_dismissed: bool,
    limit: int,
    cursor: str | None,
) -> _AceNotificationPage:
    page = notification_list_from_dict(
        client.notification_list(
            include_dismissed=include_dismissed,
            unread=True,
            limit=max(1, limit),
            cursor=cursor,
        )
    )
    notifications = [n for n in page.notifications if not n.read and not n.silent]
    counts = _counts_from_notifications(notifications)
    bounded = page.bounded
    snapshot = _AceNotificationPage(
        notifications=notifications,
        counts=_AceNotificationCounts(
            priority=int(counts.get("priority", 0)),
            errors=int(counts.get("errors", 0)),
            rest=int(counts.get("rest", 0)),
            muted=int(counts.get("muted", 0)),
        ),
        next_cursor=page.page.next_cursor,
        bounded=bounded is not None,
        truncated=bool(bounded.truncated) if bounded is not None else False,
    )
    return _notification_page_with_shared_metadata(
        snapshot,
        provider_source="daemon",
        prefers_daemon=True,
        fallback_reason=None,
        fallback_message=None,
        snapshot_id=page.snapshot.snapshot_id,
        page_count=1,
    )


def _daemon_notification_detail(
    client: LocalDaemonClient,
    notification_id: str,
) -> _AceNotificationDetail:
    detail = notification_detail_from_dict(client.notification_detail(notification_id))
    bounded = detail.bounded
    snapshot = _AceNotificationDetail(
        notification=detail.notification,
        bounded=bounded is not None,
        truncated=bool(bounded.truncated) if bounded is not None else False,
    )
    return _notification_detail_with_shared_metadata(
        snapshot,
        provider_source="daemon",
        prefers_daemon=True,
        fallback_reason=None,
        fallback_message=None,
        snapshot_id=detail.snapshot.snapshot_id,
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


def _direct_notification_count_snapshot() -> _AceNotificationCountSnapshot:
    from sase.notifications import read_notification_snapshot

    snapshot = _notification_snapshot_from_direct(read_notification_snapshot())
    return _notification_count_snapshot_from_counts(
        _counts_mapping(snapshot.counts),
        provider_source="direct",
        prefers_daemon=False,
        fallback_reason=None,
        fallback_message=None,
    )


def _direct_unread_notification_page(
    *,
    include_dismissed: bool,
    limit: int,
) -> _AceNotificationPage:
    from sase.notifications import read_notification_snapshot

    snapshot = _notification_snapshot_from_direct(
        read_notification_snapshot(include_dismissed=include_dismissed)
    )
    unread = [
        n
        for n in snapshot.notifications
        if not n.read and not n.silent and (include_dismissed or not n.dismissed)
    ][: max(0, limit)]
    page = _AceNotificationPage(
        notifications=unread,
        counts=_AceNotificationCounts(
            priority=snapshot.counts.priority,
            errors=snapshot.counts.errors,
            rest=snapshot.counts.rest,
            muted=snapshot.counts.muted,
        ),
    )
    return _notification_page_with_shared_metadata(
        page,
        provider_source="direct",
        prefers_daemon=False,
        fallback_reason=None,
        fallback_message=None,
        snapshot_id=None,
        page_count=1,
    )


def _direct_notification_detail(notification_id: str) -> _AceNotificationDetail:
    from sase.notifications import load_notifications

    notification = next(
        (
            notification
            for notification in load_notifications(include_dismissed=True)
            if notification.id == notification_id
        ),
        None,
    )
    detail = _AceNotificationDetail(notification=notification)
    return _notification_detail_with_shared_metadata(
        detail,
        provider_source="direct",
        prefers_daemon=False,
        fallback_reason=None,
        fallback_message=None,
        snapshot_id=None,
    )


def _direct_pending_actions() -> _AceNotificationPendingActions:
    from sase.notifications import pending_actions

    store = pending_actions.read_pending_action_store(include_legacy=True)
    actions = [
        dict(action)
        for action in store.get("actions", {}).values()
        if isinstance(action, dict)
    ]
    actions.sort(key=lambda action: str(action.get("prefix", "")))
    return _pending_actions_with_shared_metadata(
        _AceNotificationPendingActions(store=store, actions=actions),
        provider_source="direct",
        prefers_daemon=False,
        fallback_reason=None,
        fallback_message=None,
        snapshot_id=None,
    )


def _pending_actions_from_daemon(
    read: NotificationPendingActionsRead,
) -> _AceNotificationPendingActions:
    bounded = read.bounded
    return _pending_actions_with_shared_metadata(
        _AceNotificationPendingActions(
            store=read.store,
            actions=read.actions,
            bounded=bounded is not None,
            truncated=bool(bounded.truncated) if bounded is not None else False,
        ),
        provider_source="daemon",
        prefers_daemon=True,
        fallback_reason=None,
        fallback_message=None,
        snapshot_id=read.snapshot.snapshot_id,
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
    return _AceNotificationSnapshot(
        notifications=snapshot.notifications,
        counts=snapshot.counts,
        expired_ids=snapshot.expired_ids,
        shared_snapshot=shared_snapshot,
    )


def _notification_count_snapshot_from_counts(
    counts: Mapping[str, Any],
    *,
    provider_source: str,
    prefers_daemon: bool,
    fallback_reason: str | None,
    fallback_message: str | None,
) -> _AceNotificationCountSnapshot:
    normalized = _AceNotificationCounts(
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
    return _AceNotificationCountSnapshot(
        counts=normalized,
        shared_snapshot=shared_snapshot,
    )


def _notification_page_with_shared_metadata(
    page: _AceNotificationPage,
    *,
    provider_source: str,
    prefers_daemon: bool,
    fallback_reason: str | None,
    fallback_message: str | None,
    snapshot_id: str | None,
    page_count: int,
) -> _AceNotificationPage:
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
    return _AceNotificationPage(
        notifications=page.notifications,
        counts=page.counts,
        next_cursor=page.next_cursor,
        shared_snapshot=shared_snapshot,
        bounded=page.bounded,
        truncated=page.truncated,
    )


def _notification_detail_with_shared_metadata(
    detail: _AceNotificationDetail,
    *,
    provider_source: str,
    prefers_daemon: bool,
    fallback_reason: str | None,
    fallback_message: str | None,
    snapshot_id: str | None,
) -> _AceNotificationDetail:
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
    return _AceNotificationDetail(
        notification=detail.notification,
        shared_snapshot=shared_snapshot,
        bounded=detail.bounded,
        truncated=detail.truncated,
    )


def _pending_actions_with_shared_metadata(
    pending: _AceNotificationPendingActions,
    *,
    provider_source: str,
    prefers_daemon: bool,
    fallback_reason: str | None,
    fallback_message: str | None,
    snapshot_id: str | None,
) -> _AceNotificationPendingActions:
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
    return _AceNotificationPendingActions(
        store=pending.store,
        actions=pending.actions,
        shared_snapshot=shared_snapshot,
        bounded=pending.bounded,
        truncated=pending.truncated,
    )


def _count_value(counts: Any, key: str) -> int:
    if isinstance(counts, dict):
        return int(counts.get(key, 0))
    return int(getattr(counts, key, 0))


def _counts_mapping(counts: Any) -> dict[str, int]:
    return {
        "priority": _count_value(counts, "priority"),
        "errors": _count_value(counts, "errors"),
        "rest": _count_value(counts, "rest"),
        "muted": _count_value(counts, "muted"),
    }


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
    "apply_notification_count_delta",
    "notification_row_handle",
    "read_notification_counts_for_tui",
    "read_notification_detail_for_tui",
    "read_notification_pending_actions_for_tui",
    "read_notification_snapshot_for_tui",
    "read_unread_notification_page_for_tui",
]
