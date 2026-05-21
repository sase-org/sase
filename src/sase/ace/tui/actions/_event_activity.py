"""Activity and idle timer handlers for the ACE TUI."""

from __future__ import annotations

import time

from ..activity_log import ActivityEventType
from ..widgets import InactiveIndicator
from ._event_base import EventHandlersBase


class EventActivityMixin(EventHandlersBase):
    """Mixin providing activity tracking timer callbacks."""

    def _on_countdown_tick(self) -> None:
        """Countdown tick handler called every second."""
        now_mono = time.monotonic()
        if now_mono - self._last_activity_flush >= 10:
            if hasattr(self, "_last_activity_time"):
                activity_wall = time.time() - (now_mono - self._last_activity_time)
                # Always write the keypress file — this is the true
                # last-interaction timestamp that is_idle() uses as a
                # safety net.  It is never overwritten on idle transitions.
                from sase.ace.tui_activity import write_last_keypress, write_tui_pid

                write_last_keypress(activity_wall)
                # Re-write PID file periodically so it recovers if
                # deleted externally (e.g. stale cleanup race).
                write_tui_pid()
                # Only write the activity timestamp while the user is
                # active.  When idle, _check_idle_state already wrote
                # the idle transition time and we must not overwrite it
                # with the stale last-keypress time — is_idle() uses
                # the activity timestamp to detect manual/pinned idle
                # (epoch=0) vs natural idle.
                indicator = self.query_one("#inactive-indicator", InactiveIndicator)  # type: ignore[attr-defined]
                if not indicator._idle:
                    from sase.ace.tui_activity import write_activity_timestamp

                    write_activity_timestamp(activity_wall)
                self._last_activity_flush = now_mono
        self._check_idle_state(now_mono)
        # Deferred Tier 2 reconcile: scheduled lazily on input idleness
        # to keep the ~2.7 s full-history scan out of the startup path
        # (see _maybe_trigger_idle_tier2_reconcile).
        try:
            self._maybe_trigger_idle_tier2_reconcile(  # type: ignore[attr-defined]
                now_mono=now_mono
            )
        except AttributeError:
            pass
        self._countdown_remaining -= 1
        if self._countdown_remaining < 0:
            self._countdown_remaining = self.refresh_interval
        if self.current_tab == "changespecs":
            self._update_info_panel()  # type: ignore[attr-defined]
        elif self.current_tab == "agents":
            self._update_agents_info_panel()  # type: ignore[attr-defined]
            self._patch_agent_runtime_rows()  # type: ignore[attr-defined]
            self._poll_starting_agent_transitions()  # type: ignore[attr-defined]
        else:  # axe
            self._update_axe_info_panel()  # type: ignore[attr-defined]
            # Stream live output for an active chop run without waiting for
            # the slower full-fleet refresh interval.
            self._axe_live_tick()  # type: ignore[attr-defined]

    def _check_idle_state(self, now_mono: float) -> None:
        """Update the idle indicator based on elapsed inactivity."""
        if not hasattr(self, "_last_activity_time"):
            # Already manually marked inactive (I key) — leave idle on
            return
        elapsed = now_mono - self._last_activity_time
        idle = elapsed >= self._inactive_seconds
        indicator = self.query_one("#inactive-indicator", InactiveIndicator)  # type: ignore[attr-defined]
        was_idle = indicator._idle
        indicator.set_idle(idle)
        if idle != was_idle:
            from sase.ace.tui_activity import write_activity_timestamp, write_idle_state

            write_idle_state(idle)
            if idle:
                # Write the current wall-clock time so is_idle() can
                # distinguish natural idle (non-zero epoch) from
                # manual/pinned idle (epoch=0).
                write_activity_timestamp(time.time())
                self._activity_log.record(ActivityEventType.IDLE_AUTO)

    def _record_user_activity(self) -> None:
        """Record user activity to reset the idle indicator.

        Called from on_key() for normal bindings and directly from
        priority-binding actions (e.g. tab switching) that bypass on_key().
        """
        # Pinned idle: only the I key can clear it, ignore all other activity.
        if getattr(self, "_pinned_idle", False):
            return
        # When manually idle (i key), _last_activity_time is absent.
        # Re-enable tracking — any user activity should exit idle mode.
        if not hasattr(self, "_last_activity_time"):
            self._last_activity_time = time.monotonic()
        self._last_activity_time = time.monotonic()
        indicator = self.query_one("#inactive-indicator", InactiveIndicator)  # type: ignore[attr-defined]
        was_idle = indicator._idle
        indicator.set_idle(False)
        if was_idle:
            # Flush to disk immediately when transitioning from idle to
            # active so external consumers (e.g. Telegram outbound chop)
            # see the change before their next poll cycle.
            from sase.ace.tui_activity import write_activity_timestamp, write_idle_state

            write_idle_state(False)
            write_activity_timestamp(time.time())
            self._last_activity_flush = time.monotonic()
            self._activity_log.record(ActivityEventType.ACTIVE)
