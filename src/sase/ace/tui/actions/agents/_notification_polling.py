"""Notification polling and indicator refresh for the ACE agents TUI."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ._notification_plan_reconciliation import (
    PreparedPlanNotificationReconciliation,
    prepare_plan_notification_reconciliation,
)
from ._notification_utils import (
    apply_disappeared_plan_notification_refresh,
    is_active_agent_refresh_notification,
    prepare_disappeared_plan_notification_refresh,
    prepare_pending_gate_notification_refresh,
    unread_notification_buckets,
)

if TYPE_CHECKING:
    from sase.notifications import Notification
    from sase.notifications.delivery import NotificationDelivery, NotificationSound

log = logging.getLogger(__name__)


def _resolve_arrival_deliveries(
    arrivals: Sequence[Notification],
) -> dict[str, NotificationDelivery]:
    """Resolve every arrival's delivery in one call, keyed by notification id.

    Reads config and crosses the FFI boundary, so it runs on the worker hop. A
    failure here must never swallow an announcement: it is logged and yields no
    entries, which :func:`_delivery_for` reads as the built-in toast and bell.
    """
    from sase.notifications.delivery import resolve_notification_deliveries

    try:
        deliveries = resolve_notification_deliveries(arrivals)
    except Exception:
        log.exception("Notification delivery rules failed; announcing normally")
        return {}
    return {
        notification.id: delivery
        for notification, delivery in zip(arrivals, deliveries, strict=True)
    }


def _delivery_for(
    deliveries: dict[str, NotificationDelivery],
    notification: Notification,
) -> NotificationDelivery:
    from sase.notifications.delivery import DEFAULT_NOTIFICATION_DELIVERY

    return deliveries.get(notification.id, DEFAULT_NOTIFICATION_DELIVERY)


def _tick_sound(
    notifications: Sequence[Notification],
    deliveries: dict[str, NotificationDelivery],
) -> NotificationSound | None:
    """Return the one sound for this poll tick, or ``None`` for a silent tick.

    A burst is announced once, not once per row: the sound is the resolved sound
    of the first arrival in batch order whose sound is not ``none``.
    """
    from sase.notifications.delivery import SOUND_NONE

    for notification in notifications:
        sound = _delivery_for(deliveries, notification).sound
        if sound.kind != SOUND_NONE:
            return sound
    return None


def _consume_sound_playback(playback: Any) -> None:
    """Read a detached playback's outcome so asyncio never logs it as unhandled."""
    if not playback.cancelled():
        playback.exception()


def _prepare_notification_reconciliation(
    app: Any,
    previous_notifications: list[Notification],
    current_notifications: list[Notification],
    actionable_notifications: list[Notification],
    new_notifications: list[Notification],
    arrivals: list[Notification],
) -> tuple[
    PreparedPlanNotificationReconciliation,
    tuple[Path, ...],
    bool,
    tuple[Path, ...],
    dict[str, NotificationDelivery],
]:
    """Prepare response, disappearance, gate dirs, and deliveries on a worker thread.

    ``arrivals`` is every newly delivered row, before plan reconciliation
    dismisses any; resolving the superset keeps the delivery lookup on this one
    hop even though the dismissals are only known afterwards.
    """
    prepared_plan_notifications = prepare_plan_notification_reconciliation(
        app,
        actionable_notifications,
    )
    artifact_dirs, needs_broad_fallback = prepare_disappeared_plan_notification_refresh(
        app,
        previous_notifications,
        current_notifications,
    )
    pending_gate_dirs = prepare_pending_gate_notification_refresh(
        app,
        new_notifications,
    )
    return (
        prepared_plan_notifications,
        artifact_dirs,
        needs_broad_fallback,
        pending_gate_dirs,
        _resolve_arrival_deliveries(arrivals),
    )


class AgentNotificationPollingMixin:
    """Poll notification state and update notification indicators."""

    async def _poll_agent_completions(self: Any) -> bool:
        """Run notification reads serially and collapse overlap to one follow-up."""
        if getattr(self, "_notification_poll_running", False):
            self._notification_poll_pending = True  # type: ignore[attr-defined]
            return False

        self._notification_poll_running = True  # type: ignore[attr-defined]
        saw_new = False
        new_completions: list[Notification] = []
        pending_gate_dirs: list[Path] = []
        try:
            while True:
                self._notification_poll_pending = False  # type: ignore[attr-defined]
                saw_new = await self._poll_agent_completions_once() or saw_new
                new_completions.extend(
                    getattr(self, "_once_new_completion_notifications", ())
                )
                pending_gate_dirs.extend(
                    getattr(self, "_once_pending_gate_artifact_dirs", ())
                )
                if not getattr(self, "_notification_poll_pending", False):
                    self._last_new_completion_notifications = (  # type: ignore[attr-defined]
                        new_completions
                    )
                    self._last_pending_gate_artifact_dirs = (  # type: ignore[attr-defined]
                        pending_gate_dirs
                    )
                    return saw_new
        finally:
            self._notification_poll_running = False  # type: ignore[attr-defined]

    async def _poll_agent_completions_once(self: Any) -> bool:
        """Poll notification store for new unread notifications.

        Detects when unread count increases and applies the toast/sound policy
        that ``ace.notification_rules`` resolves for each arrival.
        Called on every auto-refresh regardless of current tab. The disk
        parse happens off the main thread so the polling tick doesn't
        block the event loop while the user is settling into the TUI.

        Returns ``True`` when the poll observed newly unread, non-resurfaced
        activity that may require an Agents refresh. Snooze expirations update
        indicators/toasts and ring the bell without rebuilding the agent list.
        """
        import asyncio

        from ._toasts import format_batch_toasts
        from sase.notifications import notification_activity_cursor

        previous_snapshot = getattr(self, "_notification_snapshot_cache", None)
        previous_notifications = list(
            getattr(previous_snapshot, "notifications", []) or []
        )
        snapshot = await self._read_notification_snapshot_guarded(
            expire_due_snoozes=True,
        )
        notifications = snapshot.notifications
        expired_snoozes = snapshot.expired_ids
        unread_priority, unread_errors, unread_rest, unread_muted = (
            unread_notification_buckets(notifications)
        )

        unread_active = unread_priority + unread_errors + unread_rest
        current_ids = {n.id for n in unread_active}
        delivered_activity_cursors = getattr(
            self,
            "_delivered_notification_activity_cursors",
            None,
        )
        if delivered_activity_cursors is None:
            delivered_activity_cursors = set()
            self._delivered_notification_activity_cursors = (  # type: ignore[attr-defined]
                delivered_activity_cursors
            )
        new_notifications: list[Notification] = []
        new_activity_cursors: set[tuple[str, str]] = set()
        for notification in unread_active:
            activity_cursor = notification_activity_cursor(notification)
            if activity_cursor in delivered_activity_cursors:
                continue
            new_notifications.append(notification)
            new_activity_cursors.add(activity_cursor)
        new_non_resurface_notifications = [
            notification
            for notification in new_notifications
            if notification.id not in expired_snoozes
            and notification.resurfaced_at is None
        ]
        (
            prepared_plan_notifications,
            disappeared_artifact_dirs,
            needs_broad_fallback,
            pending_gate_dirs,
            deliveries,
        ) = await asyncio.to_thread(
            _prepare_notification_reconciliation,
            self,
            previous_notifications,
            notifications,
            unread_active + unread_muted,
            new_non_resurface_notifications,
            new_notifications,
        )
        delivered_activity_cursors.update(new_activity_cursors)
        # The guarded read (above) already cached this snapshot as soon as
        # the disk parse landed; no need to set it again here.
        apply_disappeared_plan_notification_refresh(
            self,
            disappeared_artifact_dirs,
            needs_broad_fallback=needs_broad_fallback,
        )

        self._last_unread_ids = current_ids  # type: ignore[attr-defined]

        from ...widgets import NotificationIndicator

        indicator = self.query_one(  # type: ignore[attr-defined]
            "#notification-indicator", NotificationIndicator
        )
        indicator.set_tabs(snapshot.tabs)

        # Muting quiets the indicator; it should not break agent lifecycle state.
        auto_dismissed_ids = self._reconcile_plan_notification_lifecycle(
            unread_active + unread_muted,
            prepared_external_plan_responses=(
                prepared_plan_notifications.external_responses
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
        # expirations are delivered through the durable activity cursor, so a
        # reader that did not win expired_ids still alerts once for the new
        # resurfaced generation. Rows whose delivery rule sets ``toast: false``
        # leave the batch before it is formed so a grouped toast never counts
        # them; they still reached the indicator and snapshot cache above.
        toasted_notifications = [
            notification
            for notification in new_notifications
            if _delivery_for(deliveries, notification).toast
        ]
        for message, severity in format_batch_toasts(toasted_notifications):
            self.notify(  # type: ignore[attr-defined]
                message,
                severity=severity,
                timeout=8,
            )

        before_unread_agents = set(getattr(self, "_unread_completed_agent_ids", set()))
        self._reconcile_unread_from_completion_notifications(notifications)
        self._patch_unread_completed_agent_changes(before_unread_agents)

        # Announce the sound last so the bell or player subprocess never blocks
        # the event loop ahead of indicator/toast updates.
        tick_sound = _tick_sound(new_notifications, deliveries)
        if tick_sound is not None:
            await self._announce_notification_sound_async(tick_sound)

        self._once_new_completion_notifications = [  # type: ignore[attr-defined]
            notification
            for notification in new_non_resurface_notifications
            if is_active_agent_refresh_notification(notification)
        ]
        self._once_pending_gate_artifact_dirs = pending_gate_dirs  # type: ignore[attr-defined]
        return bool(new_non_resurface_notifications)

    def _refresh_notification_count(self: Any) -> None:
        """Reload unread notification count from disk and update the indicator.

        Called after notifications are dismissed outside the notification modal
        (e.g. when an agent is killed or dismissed-done). A direct full
        snapshot already carries notifications, counts, and tabs together,
        so this reads the store exactly once instead of a separate
        count-only parse followed by a full one.
        """
        from ...widgets import NotificationIndicator

        snapshot = self._read_notification_snapshot_from_provider()
        self._set_notification_snapshot_cache(snapshot)
        unread_priority, unread_errors, unread_rest, _ = unread_notification_buckets(
            snapshot.notifications
        )
        tabs = snapshot.tabs
        self._last_unread_ids = {
            n.id for n in unread_priority + unread_errors + unread_rest
        }

        try:
            indicator = self.query_one(  # type: ignore[attr-defined]
                "#notification-indicator", NotificationIndicator
            )
        except Exception:
            return
        indicator.set_tabs(tabs)
        self._reconcile_unread_from_cached_notifications()

    async def _refresh_notification_count_async(self: Any) -> None:
        """Async variant that reads the notifications file off the main thread.

        The widget update still runs on the asyncio event loop (main thread).
        Routes through the guarded single-flight snapshot loader so an
        overlapping completion poll and count refresh share one direct-store
        parse instead of each doing its own.
        """
        import asyncio

        from ...widgets import NotificationIndicator

        try:
            previous_snapshot = getattr(self, "_notification_snapshot_cache", None)
            previous_notifications = list(
                getattr(previous_snapshot, "notifications", []) or []
            )
            snapshot = await self._read_notification_snapshot_guarded()
            if previous_notifications:
                # The guarded read replaced the cache the completion poll uses
                # as its "previous" list, so a gate answered elsewhere would
                # vanish unobserved. Resolve disappearances here, off-thread.
                (
                    disappeared_dirs,
                    needs_broad_fallback,
                ) = await asyncio.to_thread(
                    prepare_disappeared_plan_notification_refresh,
                    self,
                    previous_notifications,
                    snapshot.notifications,
                )
                apply_disappeared_plan_notification_refresh(
                    self,
                    disappeared_dirs,
                    needs_broad_fallback=needs_broad_fallback,
                )
            unread_priority, unread_errors, unread_rest, _ = (
                unread_notification_buckets(snapshot.notifications)
            )
            tabs = snapshot.tabs
            self._last_unread_ids = {
                n.id for n in unread_priority + unread_errors + unread_rest
            }

            try:
                indicator = self.query_one(  # type: ignore[attr-defined]
                    "#notification-indicator", NotificationIndicator
                )
            except Exception:
                return
            indicator.set_tabs(tabs)
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

    async def _announce_notification_sound_async(
        self: Any, sound: NotificationSound
    ) -> None:
        """Announce one resolved notification sound on a worker thread.

        ``bell`` dispatches to `_ring_tmux_bell` and ``file`` to
        ``play_sound_file``; ``none`` announces nothing. Keeps `_ring_tmux_bell`
        as the sync leaf so fake apps and tests can patch a single method
        without juggling threads.

        The bell is three short beeps and stays awaited, but a sound file runs
        as long as the file does, so it plays on a detached task: neither this
        tick nor the Agents refresh behind it waits out a chime. Only one
        playback runs at a time, so ticks arriving faster than a long file
        cannot stack up players.
        """
        import asyncio

        from sase.notifications.delivery import SOUND_BELL, SOUND_FILE

        if sound.kind == SOUND_FILE and sound.path:
            from ...sound_playback import play_sound_file

            in_flight = getattr(self, "_notification_sound_playback", None)
            if in_flight is not None and not in_flight.done():
                return
            playback = asyncio.ensure_future(
                asyncio.to_thread(play_sound_file, sound.path)
            )
            playback.add_done_callback(_consume_sound_playback)
            self._notification_sound_playback = playback  # type: ignore[attr-defined]
        elif sound.kind == SOUND_BELL:
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
