"""Notification polling and indicator refresh for the ACE agents TUI."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from ._notification_status_overrides import (
    PreparedPlanNotificationReconciliation,
    prepare_plan_notification_reconciliation,
)
from ._notification_utils import (
    apply_disappeared_plan_notification_refresh,
    prepare_disappeared_plan_notification_refresh,
    unread_notification_buckets,
)

if TYPE_CHECKING:
    from sase.notifications import Notification


def _prepare_notification_reconciliation(
    app: Any,
    previous_notifications: list[Notification],
    current_notifications: list[Notification],
    actionable_notifications: list[Notification],
) -> tuple[
    PreparedPlanNotificationReconciliation,
    tuple[Path, ...],
    bool,
]:
    """Prepare response and disappearance transitions on a worker thread."""
    prepared_plan_notifications = prepare_plan_notification_reconciliation(
        app,
        actionable_notifications,
    )
    artifact_dirs, needs_broad_fallback = prepare_disappeared_plan_notification_refresh(
        app,
        previous_notifications,
        current_notifications,
    )
    return prepared_plan_notifications, artifact_dirs, needs_broad_fallback


class AgentNotificationPollingMixin:
    """Poll notification state and update notification indicators."""

    async def _poll_agent_completions(self: Any) -> bool:
        """Run notification reads serially and collapse overlap to one follow-up."""
        if getattr(self, "_notification_poll_running", False):
            self._notification_poll_pending = True  # type: ignore[attr-defined]
            return False

        self._notification_poll_running = True  # type: ignore[attr-defined]
        saw_new = False
        try:
            while True:
                self._notification_poll_pending = False  # type: ignore[attr-defined]
                saw_new = await self._poll_agent_completions_once() or saw_new
                if not getattr(self, "_notification_poll_pending", False):
                    return saw_new
        finally:
            self._notification_poll_running = False  # type: ignore[attr-defined]

    async def _poll_agent_completions_once(self: Any) -> bool:
        """Poll notification store for new unread notifications.

        Detects when unread count increases and applies toast/bell policy.
        Called on every auto-refresh regardless of current tab. The disk
        parse happens off the main thread so the polling tick doesn't
        block the event loop while the user is settling into the TUI.

        Returns ``True`` when the poll observed newly unread, non-resurfaced
        activity that may require an Agents refresh. Snooze expirations update
        indicators/toasts and ring the bell without rebuilding the agent list.
        """
        import asyncio

        from ._toasts import format_batch_toasts

        previous_snapshot = getattr(self, "_notification_snapshot_cache", None)
        previous_notifications = list(
            getattr(previous_snapshot, "notifications", []) or []
        )
        snapshot = await asyncio.to_thread(
            self._read_notification_snapshot_from_provider,
            expire_due_snoozes=True,
        )
        notifications = snapshot.notifications
        expired_snoozes = snapshot.expired_ids
        unread_priority, unread_errors, unread_rest, unread_muted = (
            unread_notification_buckets(notifications)
        )

        unread_active = unread_priority + unread_errors + unread_rest
        (
            prepared_plan_notifications,
            disappeared_artifact_dirs,
            needs_broad_fallback,
        ) = await asyncio.to_thread(
            _prepare_notification_reconciliation,
            self,
            previous_notifications,
            notifications,
            unread_active + unread_muted,
        )
        self._set_notification_snapshot_cache(snapshot)
        apply_disappeared_plan_notification_refresh(
            self,
            disappeared_artifact_dirs,
            needs_broad_fallback=needs_broad_fallback,
        )
        current_ids = {n.id for n in unread_active}
        new_ids = current_ids - self._last_unread_ids  # type: ignore[attr-defined]
        new_notifications = [n for n in unread_active if n.id in new_ids]
        new_non_resurface_notifications = [
            notification
            for notification in new_notifications
            if notification.id not in expired_snoozes
            and notification.resurfaced_at is None
        ]

        self._last_unread_ids = current_ids  # type: ignore[attr-defined]

        from ...widgets import NotificationIndicator

        counts = snapshot.counts
        indicator = self.query_one(  # type: ignore[attr-defined]
            "#notification-indicator", NotificationIndicator
        )
        indicator.set_counts(counts.priority + counts.errors, counts.rest, counts.muted)

        # Muting quiets the indicator; it should not break agent lifecycle state.
        auto_dismissed_ids = self._apply_notification_status_overrides(
            unread_active + unread_muted,
            prepared_external_plan_responses=(
                prepared_plan_notifications.external_responses
            ),
            prepared_neutral_plan_notification_ids=(
                prepared_plan_notifications.neutral_notification_ids
            ),
        )
        if auto_dismissed_ids:
            new_notifications = [
                notification
                for notification in new_notifications
                if notification.id not in auto_dismissed_ids
            ]
            new_non_resurface_notifications = [
                notification
                for notification in new_non_resurface_notifications
                if notification.id not in auto_dismissed_ids
            ]

        # Muted arrivals do not toast or ring. Already-handled plan reviews have
        # been filtered out of new_notifications by reconciliation. Snooze
        # expirations independently contribute transition metadata. Durable
        # unread/resurface state also makes an expiry visible when another
        # process won the store transition before this reader acquired the lock.
        should_ring_bell = bool(new_notifications or expired_snoozes)
        if new_notifications:
            for message, severity in format_batch_toasts(new_notifications):
                self.notify(  # type: ignore[attr-defined]
                    message,
                    severity=severity,
                    timeout=8,
                )

        before_unread_agents = set(getattr(self, "_unread_completed_agent_ids", set()))
        self._reconcile_unread_from_completion_notifications(notifications)
        self._patch_unread_completed_agent_changes(before_unread_agents)

        # Ring the bell last so the tmux subprocess never blocks the event loop
        # ahead of indicator/toast updates.
        if should_ring_bell:
            await self._ring_tmux_bell_async()

        return bool(new_non_resurface_notifications)

    def _refresh_notification_count(self: Any) -> None:
        """Reload unread notification count from disk and update the indicator.

        Called after notifications are dismissed outside the notification modal
        (e.g. when an agent is killed or dismissed-done).
        """
        from ...widgets import NotificationIndicator

        count_snapshot = self._read_notification_counts_from_provider()
        counts = count_snapshot.counts

        if not getattr(self, "_notification_provider_used_daemon", False):
            snapshot = self._read_notification_snapshot_from_provider()
            self._set_notification_snapshot_cache(snapshot)
            unread_priority, unread_errors, unread_rest, _ = (
                unread_notification_buckets(snapshot.notifications)
            )
            counts = snapshot.counts
            self._last_unread_ids = {
                n.id for n in unread_priority + unread_errors + unread_rest
            }
        elif (
            cached := getattr(self, "_notification_snapshot_cache", None)
        ) is not None:
            unread_priority, unread_errors, unread_rest, _ = (
                unread_notification_buckets(cached.notifications)
            )
            self._last_unread_ids = {
                n.id for n in unread_priority + unread_errors + unread_rest
            }

        try:
            indicator = self.query_one(  # type: ignore[attr-defined]
                "#notification-indicator", NotificationIndicator
            )
        except Exception:
            return
        indicator.set_counts(counts.priority + counts.errors, counts.rest, counts.muted)
        self._reconcile_unread_from_cached_notifications()

    async def _refresh_notification_count_async(self: Any) -> None:
        """Async variant that reads the notifications file off the main thread.

        The widget update still runs on the asyncio event loop (main thread).
        """
        import asyncio

        from ...widgets import NotificationIndicator

        try:
            count_snapshot = await asyncio.to_thread(
                self._read_notification_counts_from_provider
            )
            counts = count_snapshot.counts

            if not getattr(self, "_notification_provider_used_daemon", False):
                snapshot = await asyncio.to_thread(
                    self._read_notification_snapshot_from_provider
                )
                self._set_notification_snapshot_cache(snapshot)
                unread_priority, unread_errors, unread_rest, _ = (
                    unread_notification_buckets(snapshot.notifications)
                )
                counts = snapshot.counts
                self._last_unread_ids = {
                    n.id for n in unread_priority + unread_errors + unread_rest
                }
            elif (
                cached := getattr(self, "_notification_snapshot_cache", None)
            ) is not None:
                unread_priority, unread_errors, unread_rest, _ = (
                    unread_notification_buckets(cached.notifications)
                )
                self._last_unread_ids = {
                    n.id for n in unread_priority + unread_errors + unread_rest
                }

            try:
                indicator = self.query_one(  # type: ignore[attr-defined]
                    "#notification-indicator", NotificationIndicator
                )
            except Exception:
                return
            indicator.set_counts(
                counts.priority + counts.errors,
                counts.rest,
                counts.muted,
            )
            self._reconcile_unread_from_cached_notifications()
        finally:
            # Keep the coalescing guard armed across both awaits. Under
            # ``call_later`` Textual serialized the whole coroutine; detached
            # tasks must preserve that non-overlap explicitly.
            self._notification_snapshot_refresh_pending = False  # type: ignore[attr-defined]
            if getattr(self, "_notification_snapshot_refresh_followup", False):
                self._notification_snapshot_refresh_followup = False  # type: ignore[attr-defined]
                schedule_refresh = getattr(
                    self,
                    "_schedule_notification_snapshot_refresh",
                    None,
                )
                if callable(schedule_refresh):
                    schedule_refresh()

    async def _ring_tmux_bell_async(self: Any) -> None:
        """Run the tmux bell on a worker thread.

        Keeps `_ring_tmux_bell` as the sync leaf so fake apps and tests can
        patch a single method without juggling threads.
        """
        import asyncio

        await asyncio.to_thread(self._ring_tmux_bell)

    def _ring_tmux_bell(self: Any) -> None:
        """Ring tmux bell for an audible notification or reminder."""
        import os
        import subprocess

        from sase.core.shell import get_vendored_tool

        tmux_pane = os.environ.get("TMUX_PANE")
        if not tmux_pane:
            return

        try:
            subprocess.run(
                [get_vendored_tool("tmux_ring_bell"), tmux_pane, "3", "0.1"],
                check=False,
                capture_output=True,
            )
        except FileNotFoundError:
            pass
