"""ACE notification read provider helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...util.pump_tasks import spawn_pump_free_task
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
_direct_notification_count_snapshot = direct_notification_count_snapshot
_direct_notification_detail = direct_notification_detail
_direct_pending_actions = direct_pending_actions
_direct_unread_notification_page = direct_unread_notification_page
_notification_count_snapshot_from_counts = notification_count_snapshot_from_counts
_notification_detail_with_shared_metadata = notification_detail_with_shared_metadata
_notification_page_with_shared_metadata = notification_page_with_shared_metadata
_notification_snapshot_from_direct = notification_snapshot_from_direct
_notification_snapshot_with_shared_metadata = notification_snapshot_with_shared_metadata
_pending_actions_with_shared_metadata = pending_actions_with_shared_metadata

DEFAULT_NOTIFICATION_PAGE_LIMIT = 100


@dataclass(frozen=True)
class _DirectReadResult[T]:
    value: T
    surface: str
    used_daemon: bool = False
    fallback_reason: str | None = None
    fallback_message: str | None = None


def _read_notification_snapshot_for_tui(
    *,
    include_dismissed: bool = False,
    expire_due_snoozes: bool = False,
    args: Any | None = None,
    client: Any | None = None,
) -> _DirectReadResult[Any]:
    """Return the ACE notification snapshot through direct source-store reads."""
    _ = (args, client)

    from sase.notifications import read_notification_snapshot

    snapshot = notification_snapshot_from_direct(
        read_notification_snapshot(
            include_dismissed,
            expire_due_snoozes,
        )
    )
    return _DirectReadResult(
        value=notification_snapshot_with_shared_metadata(
            snapshot,
            provider_source="direct",
            prefers_daemon=False,
            fallback_reason=None,
            fallback_message=None,
            snapshot_id=(
                snapshot.shared_snapshot.snapshot_id
                if snapshot.shared_snapshot is not None
                else None
            ),
            page_count=(
                int(snapshot.shared_snapshot.metadata.get("page_count", 1))
                if snapshot.shared_snapshot is not None
                else 1
            ),
        ),
        surface="notification_list",
    )


def _read_notification_counts_for_tui(
    *,
    args: Any | None = None,
    client: Any | None = None,
) -> _DirectReadResult[AceNotificationCountSnapshot]:
    """Return count-only notification data for the ACE indicator."""
    _ = (args, client)

    direct = direct_notification_count_snapshot()
    return _DirectReadResult(
        value=notification_count_snapshot_from_counts(
            counts_mapping(direct.counts),
            provider_source="direct",
            prefers_daemon=False,
            fallback_reason=None,
            fallback_message=None,
        ),
        surface="notification_counts",
    )


def _read_unread_notification_page_for_tui(
    *,
    include_dismissed: bool = False,
    limit: int = DEFAULT_NOTIFICATION_PAGE_LIMIT,
    cursor: str | None = None,
    args: Any | None = None,
    client: Any | None = None,
) -> _DirectReadResult[AceNotificationPage]:
    """Return one unread notification modal page from direct source stores."""
    _ = (args, client, cursor)

    page = direct_unread_notification_page(
        include_dismissed=include_dismissed,
        limit=limit,
    )
    return _DirectReadResult(
        value=notification_page_with_shared_metadata(
            page,
            provider_source="direct",
            prefers_daemon=False,
            fallback_reason=None,
            fallback_message=None,
            snapshot_id=None,
            page_count=1,
        ),
        surface="notification_list",
    )


def _read_notification_detail_for_tui(
    notification_id: str,
    *,
    args: Any | None = None,
    client: Any | None = None,
) -> _DirectReadResult[AceNotificationDetail]:
    """Return selected notification detail with bounded payload metadata."""
    _ = (args, client)

    detail = direct_notification_detail(notification_id)
    return _DirectReadResult(
        value=notification_detail_with_shared_metadata(
            detail,
            provider_source="direct",
            prefers_daemon=False,
            fallback_reason=None,
            fallback_message=None,
            snapshot_id=None,
        ),
        surface="notification_detail",
    )


def _read_notification_pending_actions_for_tui(
    *,
    args: Any | None = None,
    client: Any | None = None,
) -> _DirectReadResult[AceNotificationPendingActions]:
    """Return pending HITL/plan/question action details through the provider."""
    _ = (args, client)

    pending = direct_pending_actions()
    return _DirectReadResult(
        value=pending_actions_with_shared_metadata(
            pending,
            provider_source="direct",
            prefers_daemon=False,
            fallback_reason=None,
            fallback_message=None,
            snapshot_id=None,
        ),
        surface="notification_pending_actions",
    )


class AgentNotificationProviderMixin:
    """Provider-backed notification read methods."""

    def _set_notification_snapshot_cache(self: Any, snapshot: object) -> None:
        """Store the latest notification snapshot for hot-path readers."""
        self._notification_snapshot_cache = snapshot  # type: ignore[attr-defined]
        self._notification_snapshot_version = (  # type: ignore[attr-defined]
            getattr(self, "_notification_snapshot_version", 0) + 1
        )

    def _read_notification_snapshot_from_provider(
        self: Any,
        *,
        include_dismissed: bool = False,
        expire_due_snoozes: bool = False,
    ) -> Any:
        """Return the notification snapshot via the configured ACE provider."""
        result = _read_notification_snapshot_for_tui(
            include_dismissed=include_dismissed,
            expire_due_snoozes=expire_due_snoozes,
        )
        self._notification_provider_used_daemon = False  # type: ignore[attr-defined]
        self._notification_provider_fallback_reason = None  # type: ignore[attr-defined]
        self._notification_provider_snapshot = getattr(  # type: ignore[attr-defined]
            result.value, "shared_snapshot", None
        )
        return result.value

    def _read_notification_counts_from_provider(self: Any) -> Any:
        """Return count-only notification data via the configured ACE provider."""
        from dataclasses import replace

        from ...provider_contract import AceCountPatch, AceDeltaBatch

        result = _read_notification_counts_for_tui()
        self._notification_provider_used_daemon = False  # type: ignore[attr-defined]
        self._notification_provider_fallback_reason = None  # type: ignore[attr-defined]
        self._notification_provider_snapshot = getattr(  # type: ignore[attr-defined]
            result.value, "shared_snapshot", None
        )
        previous_counts = getattr(self, "_notification_counts_cache", None)
        if previous_counts is not None:
            patched_counts = apply_notification_count_delta(
                previous_counts,
                AceDeltaBatch(
                    surface="notification_counts",
                    snapshot_id=None,
                    sequence=None,
                    count_patches=[
                        AceCountPatch("priority", result.value.counts.priority),
                        AceCountPatch("errors", result.value.counts.errors),
                        AceCountPatch("rest", result.value.counts.rest),
                        AceCountPatch("muted", result.value.counts.muted),
                    ],
                ),
            )
            result = replace(result, value=replace(result.value, counts=patched_counts))
        self._notification_counts_cache = result.value.counts  # type: ignore[attr-defined]
        return result.value

    def _read_unread_notification_page_from_provider(
        self: Any,
        *,
        include_dismissed: bool = False,
        limit: int | None = None,
    ) -> Any:
        """Return one unread modal page via the configured ACE provider."""
        result = _read_unread_notification_page_for_tui(
            include_dismissed=include_dismissed,
            limit=limit or DEFAULT_NOTIFICATION_PAGE_LIMIT,
        )
        self._notification_provider_used_daemon = False  # type: ignore[attr-defined]
        self._notification_provider_fallback_reason = None  # type: ignore[attr-defined]
        self._notification_provider_snapshot = getattr(  # type: ignore[attr-defined]
            result.value, "shared_snapshot", None
        )
        return result.value

    def _read_notification_detail_from_provider(
        self: Any,
        notification_id: str,
    ) -> Any:
        """Return selected notification detail via the configured provider."""
        result = _read_notification_detail_for_tui(notification_id)
        self._notification_detail_provider_used_daemon = False  # type: ignore[attr-defined]
        self._notification_detail_provider_snapshot = getattr(  # type: ignore[attr-defined]
            result.value, "shared_snapshot", None
        )
        return result.value

    def _read_notification_pending_actions_from_provider(self: Any) -> Any:
        """Return pending notification actions via the configured provider."""
        result = _read_notification_pending_actions_for_tui()
        self._notification_pending_actions_provider_used_daemon = False  # type: ignore[attr-defined]
        self._notification_pending_actions_provider_snapshot = getattr(  # type: ignore[attr-defined]
            result.value, "shared_snapshot", None
        )
        return result.value

    def _schedule_notification_snapshot_refresh(self: Any) -> None:
        """Refresh the notification cache off the current finalization frame."""
        if getattr(self, "_notification_snapshot_refresh_pending", False):
            self._notification_snapshot_refresh_followup = True  # type: ignore[attr-defined]
            return
        self._notification_snapshot_refresh_pending = True  # type: ignore[attr-defined]
        task = spawn_pump_free_task(
            self,
            self._refresh_notification_count_async(),
            name="sase-notification-count-refresh",
            registry_attr="_pump_free_async_tasks",
        )
        if task is None:
            self._notification_snapshot_refresh_pending = False  # type: ignore[attr-defined]


__all__ = [
    "AgentNotificationProviderMixin",
    "apply_notification_count_delta",
    "notification_row_handle",
]
