"""Notification provider read helpers for the ACE agents TUI."""

from __future__ import annotations

from typing import Any


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
        from ._notification_provider import read_notification_snapshot_for_tui

        result = read_notification_snapshot_for_tui(
            include_dismissed=include_dismissed,
            expire_due_snoozes=expire_due_snoozes,
            client=getattr(self, "_daemon_read_client", None),
            args=getattr(self, "_daemon_read_args", None),
        )
        self._notification_provider_used_daemon = result.used_daemon  # type: ignore[attr-defined]
        self._notification_provider_fallback_reason = result.fallback_reason  # type: ignore[attr-defined]
        self._notification_provider_snapshot = getattr(  # type: ignore[attr-defined]
            result.value, "shared_snapshot", None
        )
        return result.value

    def _read_notification_counts_from_provider(self: Any) -> Any:
        """Return count-only notification data via the configured ACE provider."""
        from ...provider_contract import AceCountPatch, AceDeltaBatch
        from ._notification_provider import (
            apply_notification_count_delta,
            read_notification_counts_for_tui,
        )

        result = read_notification_counts_for_tui(
            client=getattr(self, "_daemon_read_client", None),
            args=getattr(self, "_daemon_read_args", None),
        )
        self._notification_provider_used_daemon = result.used_daemon  # type: ignore[attr-defined]
        self._notification_provider_fallback_reason = result.fallback_reason  # type: ignore[attr-defined]
        self._notification_provider_snapshot = getattr(  # type: ignore[attr-defined]
            result.value, "shared_snapshot", None
        )
        previous_counts = getattr(self, "_notification_counts_cache", None)
        if previous_counts is not None:
            from dataclasses import replace

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
        from sase.daemon.client import LOCAL_DAEMON_DEFAULT_PAGE_LIMIT

        from ._notification_provider import read_unread_notification_page_for_tui

        result = read_unread_notification_page_for_tui(
            include_dismissed=include_dismissed,
            limit=limit or LOCAL_DAEMON_DEFAULT_PAGE_LIMIT,
            client=getattr(self, "_daemon_read_client", None),
            args=getattr(self, "_daemon_read_args", None),
        )
        self._notification_provider_used_daemon = result.used_daemon  # type: ignore[attr-defined]
        self._notification_provider_fallback_reason = result.fallback_reason  # type: ignore[attr-defined]
        self._notification_provider_snapshot = getattr(  # type: ignore[attr-defined]
            result.value, "shared_snapshot", None
        )
        return result.value

    def _read_notification_detail_from_provider(
        self: Any,
        notification_id: str,
    ) -> Any:
        """Return selected notification detail via the configured provider."""
        from ._notification_provider import read_notification_detail_for_tui

        result = read_notification_detail_for_tui(
            notification_id,
            client=getattr(self, "_daemon_read_client", None),
            args=getattr(self, "_daemon_read_args", None),
        )
        self._notification_detail_provider_used_daemon = result.used_daemon  # type: ignore[attr-defined]
        self._notification_detail_provider_snapshot = getattr(  # type: ignore[attr-defined]
            result.value, "shared_snapshot", None
        )
        return result.value

    def _read_notification_pending_actions_from_provider(self: Any) -> Any:
        """Return pending notification actions via the configured provider."""
        from ._notification_provider import read_notification_pending_actions_for_tui

        result = read_notification_pending_actions_for_tui(
            client=getattr(self, "_daemon_read_client", None),
            args=getattr(self, "_daemon_read_args", None),
        )
        self._notification_pending_actions_provider_used_daemon = result.used_daemon  # type: ignore[attr-defined]
        self._notification_pending_actions_provider_snapshot = getattr(  # type: ignore[attr-defined]
            result.value, "shared_snapshot", None
        )
        return result.value

    def _schedule_notification_snapshot_refresh(self: Any) -> None:
        """Refresh the notification cache off the current finalization frame."""
        if getattr(self, "_notification_snapshot_refresh_pending", False):
            return
        self._notification_snapshot_refresh_pending = True  # type: ignore[attr-defined]
        call_later = getattr(self, "call_later", None)
        if callable(call_later):
            call_later(self._refresh_notification_count_async)
            return
        self._notification_snapshot_refresh_pending = False  # type: ignore[attr-defined]
