"""Lifecycle, quit, and inactivity action methods for the ace TUI app."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from ...changespec import ChangeSpec

from ..activity_log import ActivityEventType, ActivityLog

# Type alias for tab names (used in type hints)
TabName = Literal["changespecs", "agents", "axe"]


class LifecycleMixin:
    """Mixin providing quit, inactivity, selection persistence, and agent tracking init."""

    # Type hints for attributes accessed from AceApp (defined at runtime)
    changespecs: list[ChangeSpec]
    current_idx: int
    current_tab: TabName
    _changespecs_last_idx: int
    _last_activity_time: float
    _pinned_idle: bool
    _last_unread_count: int
    _activity_log: ActivityLog

    def _initialize_agent_tracking(self) -> None:
        """Initialize notification tracking by seeding unread count.

        This ensures we don't trigger bell/toast for notifications that
        were already unread when the TUI started.
        """
        from sase.notifications import load_notifications

        from ..widgets import NotificationIndicator

        notifications = load_notifications()
        unread_count = sum(1 for n in notifications if not n.read)
        self._last_unread_count = unread_count

        indicator = self.query_one("#notification-indicator", NotificationIndicator)  # type: ignore[attr-defined]
        indicator.set_count(unread_count)

    def _save_current_selection(self) -> None:
        """Save the currently selected ChangeSpec name."""
        from ...last_selection import save_last_selection

        if self.changespecs:
            if self.current_tab == "changespecs":
                idx = min(self.current_idx, len(self.changespecs) - 1)
            else:
                idx = min(self._changespecs_last_idx, len(self.changespecs) - 1)
            changespec = self.changespecs[idx]
            save_last_selection(changespec.name)
            self._save_selection_for_current_query()  # type: ignore[attr-defined]

    def _restore_last_selection(self) -> None:
        """Restore the previously selected ChangeSpec if it exists."""
        from ...last_selection import load_last_selection

        last_name = load_last_selection()
        if last_name is None:
            return
        for idx, cs in enumerate(self.changespecs):
            if cs.name == last_name:
                self.current_idx = idx
                return

    def _count_running_tasks(self) -> int:
        """Return the count of running background tasks."""
        return self._task_queue.running_count  # type: ignore[attr-defined]

    def _kill_all_running_tasks(self) -> None:
        """Kill all running background tasks."""
        for task in self._task_queue.get_all():  # type: ignore[attr-defined]
            if task.status == "running":
                self._kill_background_task(task.task_id)  # type: ignore[attr-defined]

    async def action_quit(self) -> None:
        """Quit the application, saving the current selection."""
        count = self._count_running_tasks()
        if count > 0:
            from ..modals import ConfirmActionModal

            def _on_confirm(confirmed: bool | None) -> None:
                if not confirmed:
                    return
                self._kill_all_running_tasks()
                self._do_quit()

            self.push_screen(  # type: ignore[attr-defined]
                ConfirmActionModal(
                    title="Quit",
                    message=f"{count} background task(s) still running. Quit and kill them?",
                ),
                callback=_on_confirm,
            )
            return
        self._do_quit()

    def _do_quit(self) -> None:
        """Run the quit cleanup sequence and exit."""
        self._save_current_selection()
        from sase.ace.tui_activity import (
            remove_idle_state,
            remove_last_keypress,
            remove_tui_pid,
            write_activity_timestamp,
        )

        if self._pinned_idle:
            # Pinned idle persists across restarts — leave idle state files
            # intact so external consumers still see the user as idle.
            remove_tui_pid()
        else:
            write_activity_timestamp(time.time())
            remove_idle_state()
            remove_last_keypress()
            remove_tui_pid()
        self.exit()  # type: ignore[attr-defined]

    def action_mark_inactive(self) -> None:
        """Toggle manual idle mode.

        First press enters idle (epoch 0, idle_state=True).
        Second press exits idle and resumes normal activity tracking.
        No-op when pinned idle is active (only I can clear pinned idle).
        """
        from ..widgets import InactiveIndicator

        if self._pinned_idle:
            return

        indicator = self.query_one("#inactive-indicator", InactiveIndicator)  # type: ignore[attr-defined]
        if not hasattr(self, "_last_activity_time"):
            # Currently in manual idle — exit it.
            from sase.ace.tui_activity import write_activity_timestamp, write_idle_state

            self._last_activity_time = time.monotonic()
            write_activity_timestamp(time.time())
            write_idle_state(False)
            indicator.set_idle(False)
            self._activity_log.record(ActivityEventType.ACTIVE)
            return

        # Enter manual idle.
        from sase.ace.tui_activity import write_activity_timestamp, write_idle_state

        write_activity_timestamp(0)
        write_idle_state(True)
        # Clear activity tracking so _on_countdown_tick() doesn't overwrite
        # the inactive marker (epoch 0) with the current time.
        del self._last_activity_time
        indicator.set_idle(True)
        self._activity_log.record(ActivityEventType.IDLE_MANUAL)

    def action_mark_inactive_pinned(self) -> None:
        """Toggle pinned idle mode.

        Pinned idle stays active until explicitly toggled off with I.
        Regular keypresses do not clear pinned idle.  The state is
        persisted to disk so it survives TUI restarts.
        """
        from ..widgets import InactiveIndicator

        indicator = self.query_one("#inactive-indicator", InactiveIndicator)  # type: ignore[attr-defined]
        if self._pinned_idle:
            # Currently in pinned idle — exit it.
            from sase.ace.tui_activity import (
                write_activity_timestamp,
                write_idle_state,
                write_pinned_idle,
            )

            self._pinned_idle = False
            self._last_activity_time = time.monotonic()
            write_activity_timestamp(time.time())
            write_idle_state(False)
            write_pinned_idle(False)
            indicator.set_idle(False)
            self._activity_log.record(ActivityEventType.ACTIVE)
            return

        # Enter pinned idle.
        from sase.ace.tui_activity import (
            write_activity_timestamp,
            write_idle_state,
            write_pinned_idle,
        )

        self._pinned_idle = True
        write_activity_timestamp(0)
        write_idle_state(True)
        write_pinned_idle(True)
        # Clear activity tracking so _on_countdown_tick() doesn't overwrite
        # the inactive marker (epoch 0) with the current time.
        if hasattr(self, "_last_activity_time"):
            del self._last_activity_time
        indicator.set_idle(True, pinned=True)
        self._activity_log.record(ActivityEventType.IDLE_PINNED)
