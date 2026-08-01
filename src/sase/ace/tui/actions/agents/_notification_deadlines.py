"""Nearest-deadline coordination for ACE notification snoozes."""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any

from ...util.pump_tasks import spawn_pump_free_task
from ._notification_utils import request_notification_agents_refresh

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from textual.timer import Timer

NOTIFICATION_DEADLINE_RECHECK_SECONDS = 1.0


def _notification_wall_time() -> float:
    """Return the wall-clock epoch used to compare durable UTC deadlines."""
    return time.time()


def _deadline_epoch(value: object) -> float | None:
    """Parse one aware RFC-3339-ish deadline into epoch seconds."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.timestamp()


class AgentNotificationDeadlineMixin:
    """Maintain one short wall-clock recheck timer for the nearest snooze."""

    _notification_deadline_timer: Timer | None
    _notification_deadline_epoch: float | None
    _notification_poll_scheduled: bool
    _notification_poll_running: bool
    _notification_poll_pending: bool

    def _sync_notification_deadline_from_snapshot(self: Any, snapshot: object) -> None:
        """Replace the cached deadline and timer from an authoritative snapshot."""
        self._notification_deadline_epoch = _deadline_epoch(  # type: ignore[attr-defined]
            getattr(snapshot, "next_snooze_deadline", None)
        )
        self._stop_notification_deadline_timer()
        self._arm_notification_deadline_timer()

    def _stop_notification_deadline_timer(self: Any) -> None:
        """Stop and forget the current deadline timer, if any."""
        timer = getattr(self, "_notification_deadline_timer", None)
        self._notification_deadline_timer = None  # type: ignore[attr-defined]
        if timer is None:
            return
        try:
            timer.stop()
        except Exception:
            log.debug("Failed to stop notification deadline timer", exc_info=True)

    def _arm_notification_deadline_timer(self: Any) -> None:
        """Arm one timer no more than a second toward the cached deadline."""
        deadline_epoch = getattr(self, "_notification_deadline_epoch", None)
        set_timer = getattr(self, "set_timer", None)
        if deadline_epoch is None or not callable(set_timer):
            return
        remaining = max(0.0, deadline_epoch - _notification_wall_time())
        delay = min(remaining, NOTIFICATION_DEADLINE_RECHECK_SECONDS)
        self._notification_deadline_timer = set_timer(  # type: ignore[attr-defined]
            delay,
            self._on_notification_deadline_timer,
            name="notification-deadline",
        )

    def _on_notification_deadline_timer(self: Any) -> None:
        """Recheck wall time synchronously, launching disk work only when due."""
        self._notification_deadline_timer = None  # type: ignore[attr-defined]
        deadline_epoch = getattr(self, "_notification_deadline_epoch", None)
        if deadline_epoch is None:
            return
        if _notification_wall_time() < deadline_epoch:
            self._arm_notification_deadline_timer()
            return
        self._schedule_notification_poll(source="deadline")

    def _schedule_notification_poll(self: Any, *, source: str = "notification") -> None:
        """Launch one pump-free poll, coalescing timer/watcher/mutation bursts."""
        if getattr(self, "_notification_poll_scheduled", False) or getattr(
            self, "_notification_poll_running", False
        ):
            self._notification_poll_pending = True  # type: ignore[attr-defined]
            return
        self._notification_poll_scheduled = True  # type: ignore[attr-defined]
        task = spawn_pump_free_task(
            self,
            self._run_scheduled_notification_poll(source=source),
            name=f"sase-notification-poll:{source}",
            registry_attr="_pump_free_async_tasks",
        )
        if task is None:
            self._notification_poll_scheduled = False  # type: ignore[attr-defined]

    async def _run_scheduled_notification_poll(self: Any, *, source: str) -> None:
        """Run a scheduled poll and keep deadline failures retryable."""
        self._notification_poll_scheduled = False  # type: ignore[attr-defined]
        try:
            saw_new = await self._poll_agent_completions()
        except Exception:
            log.exception("Notification poll failed (source=%s)", source)
            self._schedule_notification_poll_retry()
            return
        self._dirty_notifications = False  # type: ignore[attr-defined]
        if saw_new and getattr(self, "current_tab", None) == "agents":
            request_notification_agents_refresh(self)

    def _schedule_notification_poll_retry(self: Any) -> None:
        """Retry any failed current-state read even with refresh disabled."""
        set_timer = getattr(self, "set_timer", None)
        if not callable(set_timer):
            return
        self._stop_notification_deadline_timer()
        self._notification_deadline_timer = set_timer(  # type: ignore[attr-defined]
            NOTIFICATION_DEADLINE_RECHECK_SECONDS,
            self._on_notification_poll_retry,
            name="notification-poll-retry",
        )

    def _on_notification_poll_retry(self: Any) -> None:
        """Timer callback that launches a coalesced retry off the pump."""
        self._notification_deadline_timer = None  # type: ignore[attr-defined]
        self._schedule_notification_poll(source="retry")

    def _cancel_notification_deadline_coordinator(self: Any) -> None:
        """Cancel deadline state during controlled and normal teardown."""
        self._stop_notification_deadline_timer()
        self._notification_deadline_epoch = None  # type: ignore[attr-defined]
        self._notification_poll_pending = False  # type: ignore[attr-defined]


__all__ = [
    "AgentNotificationDeadlineMixin",
    "NOTIFICATION_DEADLINE_RECHECK_SECONDS",
]
