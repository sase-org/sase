"""Notification modal for viewing unread notifications."""

from __future__ import annotations

import os
from pathlib import Path

from rich.syntax import Syntax
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList, Static
from textual.widgets.option_list import Option

from sase.ace.tui.widgets.file_panel import _EXTENSION_TO_LEXER
from sase.notifications import (
    Notification,
    format_relative_time,
    mark_all_read,
    mark_dismissed,
)

from .base import OptionListNavigationMixin


# Action badge mapping
_ACTION_BADGES: dict[str | None, str] = {
    "JumpToChangeSpec": "[CL]",
    "Tmux": "[tmux]",
    "HITL": "[HITL]",
    "PlanApproval": "[plan]",
    "UserQuestion": "[question]",
}


class NotificationModal(OptionListNavigationMixin, ModalScreen[Notification | None]):
    """Modal for viewing and selecting unread notifications."""

    _option_list_id = "notification-list"
    BINDINGS = [
        *OptionListNavigationMixin.NAVIGATION_BINDINGS,
        ("d", "dismiss_notification", "Dismiss"),
        ("ctrl+n", "next_file", "Next File"),
        ("ctrl+p", "prev_file", "Previous File"),
        ("R", "read_all", "Read All"),  # uppercase R
        ("ctrl+d", "scroll_file_down", "Scroll down"),
        ("ctrl+u", "scroll_file_up", "Scroll up"),
    ]

    def __init__(self, notifications: list[Notification]) -> None:
        """Initialize the notification modal.

        Args:
            notifications: List of notifications to display.
        """
        super().__init__()
        self._notifications = list(notifications)
        self._current_file_index: int = 0

    def compose(self) -> ComposeResult:
        """Compose the modal layout."""
        with Container(id="notification-container"):
            yield Label("Notifications", id="notification-title")
            with Horizontal(id="notification-panels"):
                with Vertical(id="notification-left"):
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
                with Vertical(id="notification-right"):
                    yield Label("No files attached", id="notification-file-title")
                    with VerticalScroll(id="notification-file-scroll"):
                        yield Static(id="notification-file-content")
            yield Label(
                "Enter: select  d: dismiss  C-n/C-p: next/prev file  C-d/C-u: scroll  R: read all  q: close",
                id="notification-hints",
            )

    @staticmethod
    def _shorten_path(path: str) -> str:
        """Shorten a path by replacing home directory with ~."""
        return path.replace(str(Path.home()), "~")

    def _get_highlighted_notification(self) -> Notification | None:
        """Return the notification object for the currently highlighted option."""
        idx = self._get_selected_index()
        if idx is not None and 0 <= idx < len(self._notifications):
            return self._notifications[idx]
        return None

    def _display_file(self, notification: Notification | None) -> None:
        """Render file content with syntax highlighting in the right pane."""
        title = self.query_one("#notification-file-title", Label)
        content_widget = self.query_one("#notification-file-content", Static)

        if notification is None or not notification.files:
            title.update("No files attached")
            content_widget.update("")
            return

        files = notification.files
        # Clamp index
        if self._current_file_index >= len(files):
            self._current_file_index = 0

        file_path = files[self._current_file_index]
        short = self._shorten_path(file_path)
        title.update(f"File {self._current_file_index + 1}/{len(files)}: {short}")

        expanded_path = os.path.expanduser(file_path)

        try:
            with open(expanded_path, encoding="utf-8") as f:
                content = f.read()
        except Exception:
            content_widget.update(Text("Could not read file.", style="dim italic"))
            self._reset_file_scroll()
            return

        if not content.strip():
            content_widget.update(Text("File is empty.", style="dim italic"))
            self._reset_file_scroll()
            return

        # Detect lexer from file extension
        _, ext = os.path.splitext(expanded_path)
        lexer = _EXTENSION_TO_LEXER.get(ext.lower(), "text")

        syntax = Syntax(
            content,
            lexer,
            theme="monokai",
            line_numbers=True,
            word_wrap=True,
        )
        content_widget.update(syntax)
        self._reset_file_scroll()

    def _reset_file_scroll(self) -> None:
        """Reset the file scroll pane to the top."""
        try:
            scroll = self.query_one("#notification-file-scroll", VerticalScroll)
            scroll.scroll_home(animate=False)
        except Exception:
            pass

    def action_next_file(self) -> None:
        """Cycle to the next attached file."""
        notification = self._get_highlighted_notification()
        if notification and notification.files:
            self._current_file_index = (self._current_file_index + 1) % len(
                notification.files
            )
            self._display_file(notification)

    def action_scroll_file_down(self) -> None:
        """Scroll the file content down by half a page."""
        scroll = self.query_one("#notification-file-scroll", VerticalScroll)
        height = scroll.scrollable_content_region.height
        scroll.scroll_relative(y=height // 2, animate=False)

    def action_scroll_file_up(self) -> None:
        """Scroll the file content up by half a page."""
        scroll = self.query_one("#notification-file-scroll", VerticalScroll)
        height = scroll.scrollable_content_region.height
        scroll.scroll_relative(y=-(height // 2), animate=False)

    def action_prev_file(self) -> None:
        """Cycle to the previous attached file."""
        notification = self._get_highlighted_notification()
        if notification and notification.files:
            self._current_file_index = (self._current_file_index - 1) % len(
                notification.files
            )
            self._display_file(notification)

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        """Update the right pane when a different notification is highlighted."""
        self._current_file_index = 0
        if event.option and event.option.id is not None:
            idx = int(event.option.id)
            if 0 <= idx < len(self._notifications):
                self._display_file(self._notifications[idx])

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
        """Focus the option list on mount and display first file."""
        try:
            option_list = self.query_one("#notification-list", OptionList)
            option_list.focus()
        except Exception:
            pass  # No list if empty

        # Display file for the first notification
        if self._notifications:
            self._display_file(self._notifications[0])

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

        # Determine which index to highlight after removal:
        # same index (now the next item), or last item if we dismissed the tail
        if self._notifications:
            highlight = min(idx, len(self._notifications) - 1)
        else:
            highlight = None

        self._rebuild_list(highlight_index=highlight)

    def action_read_all(self) -> None:
        """Mark all notifications as read and rebuild the display."""
        mark_all_read()

        # Update local state
        for n in self._notifications:
            n.read = True

        self._rebuild_list()

    def _rebuild_list(self, highlight_index: int | None = None) -> None:
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
                # Insert empty message into the left panel
                left_panel = self.query_one("#notification-left", Vertical)
                left_panel.mount(
                    Static(
                        "No unread notifications",
                        id="notification-empty",
                    ),
                )
            # Update right pane
            self._display_file(None)
            return

        for option in self._create_options():
            option_list.add_option(option)

        # Restore highlight to the requested index
        if highlight_index is not None:
            option_list.highlighted = highlight_index

        # Update right pane for whatever is now highlighted
        self._current_file_index = 0
        notification = self._get_highlighted_notification()
        self._display_file(notification)
