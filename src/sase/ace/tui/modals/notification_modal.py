"""Notification modal for viewing unread notifications."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList, Static
from textual.widgets.option_list import Option

from sase.notifications import (
    Notification,
    format_relative_time,
    mark_all_read,
    mark_dismissed,
)

from .base import OptionListNavigationMixin
from .notification_file_browser import NotificationFileBrowser


# Action badge mapping
_ACTION_BADGES: dict[str | None, str] = {
    "JumpToChangeSpec": "[CL]",
    "Tmux": "[tmux]",
    "HITL": "[HITL]",
}


class NotificationModal(OptionListNavigationMixin, ModalScreen[Notification | None]):
    """Modal for viewing and selecting unread notifications."""

    _option_list_id = "notification-list"
    BINDINGS = [
        *OptionListNavigationMixin.NAVIGATION_BINDINGS,
        ("d", "dismiss_notification", "Dismiss"),
        ("f", "show_files", "Files"),
        ("R", "read_all", "Read All"),  # uppercase R
    ]

    def __init__(self, notifications: list[Notification]) -> None:
        """Initialize the notification modal.

        Args:
            notifications: List of notifications to display.
        """
        super().__init__()
        self._notifications = list(notifications)

    def compose(self) -> ComposeResult:
        """Compose the modal layout."""
        with Container(id="notification-container"):
            yield Label("Notifications", id="notification-title")
            if self._notifications:
                yield OptionList(
                    *self._create_options(),
                    id="notification-list",
                )
            else:
                yield Static(
                    "No unread notifications",
                    id="notification-empty",
                )
            yield Label(
                "Enter: select  d: dismiss  f: files  R: read all  q/Esc: close",
                id="notification-hints",
            )

    def _create_styled_label(self, notification: Notification) -> Text:
        """Create styled text for a notification option."""
        text = Text()

        # Unread indicator
        if not notification.read:
            text.append("* ", style="bold #FFD700")

        # Sender
        text.append(f"[{notification.sender}]", style="bold")
        text.append(" ", style="")

        # First notes line (truncated)
        if notification.notes:
            note = notification.notes[0]
            if len(note) > 50:
                note = note[:47] + "..."
            text.append(note, style="")
        else:
            text.append("(no message)", style="dim italic")

        # Relative time
        text.append(f"  {format_relative_time(notification.timestamp)}", style="dim")

        # Action badge
        badge = _ACTION_BADGES.get(notification.action, "")
        if badge:
            text.append(f"  {badge}", style="bold #00D7FF")

        # File count
        if notification.files:
            count = len(notification.files)
            text.append(
                f"  {count} file{'s' if count != 1 else ''}",
                style="dim",
            )

        return text

    def _create_options(self) -> list[Option]:
        """Create options from notifications."""
        return [
            Option(self._create_styled_label(n), id=str(i))
            for i, n in enumerate(self._notifications)
        ]

    def on_mount(self) -> None:
        """Focus the option list on mount."""
        try:
            option_list = self.query_one("#notification-list", OptionList)
            option_list.focus()
        except Exception:
            pass  # No list if empty

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle option selection (Enter or click)."""
        if event.option and event.option.id is not None:
            idx = int(event.option.id)
            if 0 <= idx < len(self._notifications):
                self.dismiss(self._notifications[idx])

    def _get_selected_index(self) -> int | None:
        """Get the currently highlighted notification index."""
        try:
            option_list = self.query_one("#notification-list", OptionList)
            highlighted = option_list.highlighted
            if highlighted is not None:
                option = option_list.get_option_at_index(highlighted)
                if option.id is not None:
                    return int(option.id)
        except Exception:
            pass
        return None

    def action_dismiss_notification(self) -> None:
        """Dismiss the currently highlighted notification."""
        idx = self._get_selected_index()
        if idx is None or idx >= len(self._notifications):
            return

        notification = self._notifications[idx]
        mark_dismissed(notification.id)

        # Remove from local list and rebuild
        self._notifications.pop(idx)
        self._rebuild_list()

    def action_show_files(self) -> None:
        """Show file browser for the currently highlighted notification."""
        idx = self._get_selected_index()
        if idx is None or idx >= len(self._notifications):
            return

        notification = self._notifications[idx]
        if not notification.files:
            self.notify("No files attached to this notification", severity="warning")
            return

        self.app.push_screen(NotificationFileBrowser(notification.files))

    def action_read_all(self) -> None:
        """Mark all notifications as read and rebuild the display."""
        mark_all_read()

        # Update local state
        for n in self._notifications:
            n.read = True

        self._rebuild_list()

    def _rebuild_list(self) -> None:
        """Rebuild the option list from current notifications."""
        try:
            option_list = self.query_one("#notification-list", OptionList)
        except Exception:
            return

        option_list.clear_options()

        if not self._notifications:
            # Replace option list with empty message
            option_list.add_class("hidden")
            try:
                self.query_one("#notification-empty", Static)
            except Exception:
                # Insert empty message before hints
                container = self.query_one("#notification-container", Container)
                container.mount(
                    Static(
                        "No unread notifications",
                        id="notification-empty",
                    ),
                    before="#notification-hints",
                )
            return

        for option in self._create_options():
            option_list.add_option(option)
