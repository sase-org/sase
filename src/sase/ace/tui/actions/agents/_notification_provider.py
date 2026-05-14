"""ACE notification read provider helpers."""

from __future__ import annotations

from typing import Any

from sase.daemon.client import LOCAL_DAEMON_DEFAULT_PAGE_LIMIT, LocalDaemonClient
from sase.daemon.read_facade import DaemonReadResult, read_or_fallback

from ._notification_provider_daemon import (
    daemon_notification_count_snapshot,
    daemon_notification_detail,
    daemon_notification_snapshot,
    daemon_pending_actions,
    daemon_unread_notification_page,
    pending_actions_from_daemon,
)
from ._notification_provider_direct import (
    direct_notification_count_snapshot,
    direct_notification_detail,
    direct_pending_actions,
    direct_unread_notification_page,
    notification_snapshot_from_direct,
)
from ._notification_provider_metadata import (
    apply_notification_count_delta,
    count_value,
    counts_from_notifications,
    counts_mapping,
    notification_count_snapshot_from_counts,
    notification_detail_with_shared_metadata,
    notification_page_with_shared_metadata,
    notification_row_handle,
    notification_snapshot_with_shared_metadata,
    pending_actions_with_shared_metadata,
)
from ._notification_provider_models import (
    AceNotificationCountSnapshot,
    AceNotificationCounts,
    AceNotificationDetail,
    AceNotificationPage,
    AceNotificationPendingActions,
    AceNotificationSnapshot,
)

_AceNotificationCountSnapshot = AceNotificationCountSnapshot
_AceNotificationCounts = AceNotificationCounts
_AceNotificationDetail = AceNotificationDetail
_AceNotificationPage = AceNotificationPage
_AceNotificationPendingActions = AceNotificationPendingActions
_AceNotificationSnapshot = AceNotificationSnapshot
_count_value = count_value
_counts_from_notifications = counts_from_notifications
_counts_mapping = counts_mapping
_daemon_notification_count_snapshot = daemon_notification_count_snapshot
_daemon_notification_detail = daemon_notification_detail
_daemon_notification_snapshot = daemon_notification_snapshot
_daemon_pending_actions = daemon_pending_actions
_daemon_unread_notification_page = daemon_unread_notification_page
_direct_notification_count_snapshot = direct_notification_count_snapshot
_direct_notification_detail = direct_notification_detail
_direct_pending_actions = direct_pending_actions
_direct_unread_notification_page = direct_unread_notification_page
_notification_count_snapshot_from_counts = notification_count_snapshot_from_counts
_notification_detail_with_shared_metadata = notification_detail_with_shared_metadata
_notification_page_with_shared_metadata = notification_page_with_shared_metadata
_notification_snapshot_from_direct = notification_snapshot_from_direct
_notification_snapshot_with_shared_metadata = notification_snapshot_with_shared_metadata
_pending_actions_from_daemon = pending_actions_from_daemon
_pending_actions_with_shared_metadata = pending_actions_with_shared_metadata


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
        "ace_notification_list",
        args=args,
        client=client,
        daemon_loader=lambda daemon: daemon_notification_snapshot(
            daemon,
            include_dismissed=include_dismissed,
            expire_due_snoozes=expire_due_snoozes,
        ),
        direct_loader=lambda: notification_snapshot_from_direct(
            read_notification_snapshot(
                include_dismissed,
                expire_due_snoozes,
            )
        ),
    )
    if result.used_daemon:
        return result
    return DaemonReadResult(
        value=notification_snapshot_with_shared_metadata(
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
        fallback_diagnostics=result.fallback_diagnostics,
    )


def read_notification_counts_for_tui(
    *,
    args: Any | None = None,
    client: LocalDaemonClient | None = None,
) -> DaemonReadResult[AceNotificationCountSnapshot]:
    """Return count-only notification data for the ACE indicator."""

    result = read_or_fallback(
        "ace_notification_counts",
        args=args,
        client=client,
        daemon_loader=daemon_notification_count_snapshot,
        direct_loader=direct_notification_count_snapshot,
    )
    if result.used_daemon:
        return result
    return DaemonReadResult(
        value=notification_count_snapshot_from_counts(
            counts_mapping(result.value.counts),
            provider_source="direct_fallback",
            prefers_daemon=True,
            fallback_reason=result.fallback_reason,
            fallback_message=result.fallback_message,
        ),
        surface=result.surface,
        used_daemon=False,
        fallback_reason=result.fallback_reason,
        fallback_message=result.fallback_message,
        fallback_diagnostics=result.fallback_diagnostics,
    )


def read_unread_notification_page_for_tui(
    *,
    include_dismissed: bool = False,
    limit: int = LOCAL_DAEMON_DEFAULT_PAGE_LIMIT,
    cursor: str | None = None,
    args: Any | None = None,
    client: LocalDaemonClient | None = None,
) -> DaemonReadResult[AceNotificationPage]:
    """Return one unread notification modal page with direct fallback."""

    result = read_or_fallback(
        "ace_notification_list",
        args=args,
        client=client,
        daemon_loader=lambda daemon: daemon_unread_notification_page(
            daemon,
            include_dismissed=include_dismissed,
            limit=limit,
            cursor=cursor,
        ),
        direct_loader=lambda: direct_unread_notification_page(
            include_dismissed=include_dismissed,
            limit=limit,
        ),
    )
    if result.used_daemon:
        return result
    return DaemonReadResult(
        value=notification_page_with_shared_metadata(
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
        fallback_diagnostics=result.fallback_diagnostics,
    )


def read_notification_startup_for_tui(
    *,
    limit: int = LOCAL_DAEMON_DEFAULT_PAGE_LIMIT,
    args: Any | None = None,
    client: LocalDaemonClient | None = None,
) -> DaemonReadResult[AceNotificationSnapshot]:
    """Return the bounded startup seed for the ACE notification indicator."""

    daemon_client = client or LocalDaemonClient()
    page_result = read_unread_notification_page_for_tui(
        limit=limit,
        args=args,
        client=daemon_client,
    )
    page = page_result.value
    counts = page.counts
    fallback_diagnostics = page_result.fallback_diagnostics
    if not page.counts_complete:
        counts_result = read_notification_counts_for_tui(
            args=args,
            client=daemon_client,
        )
        counts = counts_result.value.counts
        fallback_diagnostics = (
            fallback_diagnostics or counts_result.fallback_diagnostics
        )

    return DaemonReadResult(
        value=AceNotificationSnapshot(
            notifications=page.notifications,
            counts=counts,
            expired_ids=[],
            shared_snapshot=page.shared_snapshot,
        ),
        surface=page_result.surface,
        used_daemon=page_result.used_daemon,
        fallback_reason=page_result.fallback_reason,
        fallback_message=page_result.fallback_message,
        fallback_diagnostics=fallback_diagnostics,
    )


def read_notification_detail_for_tui(
    notification_id: str,
    *,
    args: Any | None = None,
    client: LocalDaemonClient | None = None,
) -> DaemonReadResult[AceNotificationDetail]:
    """Return selected notification detail with bounded payload metadata."""

    result = read_or_fallback(
        "ace_notification_detail",
        args=args,
        client=client,
        daemon_loader=lambda daemon: daemon_notification_detail(
            daemon,
            notification_id,
        ),
        direct_loader=lambda: direct_notification_detail(notification_id),
    )
    if result.used_daemon:
        return result
    return DaemonReadResult(
        value=notification_detail_with_shared_metadata(
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
        fallback_diagnostics=result.fallback_diagnostics,
    )


def read_notification_pending_actions_for_tui(
    *,
    args: Any | None = None,
    client: LocalDaemonClient | None = None,
) -> DaemonReadResult[AceNotificationPendingActions]:
    """Return pending HITL/plan/question action details through the provider."""

    result = read_or_fallback(
        "ace_notification_pending_actions",
        args=args,
        client=client,
        daemon_loader=daemon_pending_actions,
        direct_loader=direct_pending_actions,
    )
    if result.used_daemon:
        return result
    return DaemonReadResult(
        value=pending_actions_with_shared_metadata(
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
        fallback_diagnostics=result.fallback_diagnostics,
    )


__all__ = [
    "apply_notification_count_delta",
    "notification_row_handle",
    "read_notification_counts_for_tui",
    "read_notification_detail_for_tui",
    "read_notification_pending_actions_for_tui",
    "read_notification_startup_for_tui",
    "read_notification_snapshot_for_tui",
    "read_unread_notification_page_for_tui",
]
