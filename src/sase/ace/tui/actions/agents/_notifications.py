"""Notification polling and display methods for the ace TUI app."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from sase.notifications import Notification

# Type alias for tab names
TabName = Literal["changespecs", "agents", "axe"]


class AgentNotificationMixin:
    """Mixin providing notification polling and display methods.

    Type hints below declare attributes that are defined at runtime by AceApp.
    """

    _pending_attention_count: int
    _last_unread_count: int
    current_tab: TabName

    def _poll_agent_completions(self) -> None:
        """Poll notification store for new unread notifications.

        Detects when unread count increases and triggers bell/toast.
        Called on every auto-refresh regardless of current tab.
        """
        from sase.notifications import load_notifications

        notifications = load_notifications()
        unread = [n for n in notifications if not n.read]
        unread_count = len(unread)

        # Detect newly arrived notifications
        if unread_count > self._last_unread_count:
            self._ring_tmux_bell()
            # Fire toast for new notifications
            new_count = unread_count - self._last_unread_count
            self.notify(  # type: ignore[attr-defined]
                f"{new_count} new notification{'s' if new_count != 1 else ''}",
                severity="information",
                timeout=8,
            )

        self._last_unread_count = unread_count
        self._pending_attention_count = unread_count

        if unread_count > 0 and self.current_tab != "agents":
            self._update_tab_bar_emphasis()
        elif unread_count == 0:
            self._clear_tab_bar_emphasis()

    def _ring_tmux_bell(self) -> None:
        """Ring tmux bell to notify user of agent completion."""
        import os
        import subprocess

        # Get current tmux pane from environment
        tmux_pane = os.environ.get("TMUX_PANE")
        if not tmux_pane:
            return  # Not in tmux

        try:
            subprocess.run(
                ["tmux_ring_bell", tmux_pane, "3", "0.1"],
                check=False,
                capture_output=True,
            )
        except FileNotFoundError:
            pass  # Script not available

    def _update_tab_bar_emphasis(self) -> None:
        """Update tab bar with attention count badge."""
        from ...widgets import TabBar

        tab_bar = self.query_one("#tab-bar", TabBar)  # type: ignore[attr-defined]
        tab_bar.set_attention_count(self._pending_attention_count)

    def _clear_tab_bar_emphasis(self) -> None:
        """Clear tab bar attention badge."""
        from ...widgets import TabBar

        tab_bar = self.query_one("#tab-bar", TabBar)  # type: ignore[attr-defined]
        tab_bar.set_attention_count(0)

    def action_show_notifications(self) -> None:
        """Show the notification modal with unread notifications."""
        from sase.notifications import load_notifications, mark_read

        from ...modals import NotificationModal

        notifications = load_notifications()
        unread = [n for n in notifications if not n.read]

        def _on_dismiss(result: Notification | None) -> None:
            if result is None:
                return
            # Mark the selected notification as read
            mark_read(result.id)
            # Update badge count
            self._last_unread_count = max(0, self._last_unread_count - 1)
            self._pending_attention_count = self._last_unread_count
            if self._last_unread_count > 0:
                self._update_tab_bar_emphasis()
            else:
                self._clear_tab_bar_emphasis()

        self.push_screen(NotificationModal(unread), callback=_on_dismiss)  # type: ignore[attr-defined]
