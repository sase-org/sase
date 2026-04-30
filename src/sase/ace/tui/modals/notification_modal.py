"""Notification modal for viewing unread notifications."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList, Static

from sase.ace.tui.graphics import (
    GraphicsCapability,
    KittyImageRenderable,
    image_preview,
)
from sase.notifications import (
    Notification,
    mark_all_read,
    mark_dismissed,
    mark_muted,
    mark_snoozed,
)

from .base import OptionListNavigationMixin
from .notification_modal_actions import NotificationStateActionsMixin
from .notification_modal_attachments import NotificationAttachmentMixin
from .notification_modal_constants import DEFAULT_HINT_TEXT, HEADER_ID_PREFIX
from .notification_modal_options import NotificationOptionMixin


class NotificationModal(
    NotificationAttachmentMixin,
    NotificationOptionMixin,
    NotificationStateActionsMixin,
    OptionListNavigationMixin,
    ModalScreen[Notification | None],
):
    """Modal for viewing and selecting unread notifications."""

    _option_list_id = "notification-list"
    BINDINGS = [
        *(
            b
            for b in OptionListNavigationMixin.NAVIGATION_BINDINGS
            if b[0] not in ("ctrl+n", "ctrl+p")
        ),
        ("x", "dismiss_notification", "Dismiss"),
        ("y", "confirm_dismiss_notification", "Confirm Dismiss"),
        ("n", "cancel_dismiss_notification", "Cancel Dismiss"),
        ("e", "open_in_editor", "Edit"),
        ("ctrl+n", "next_file", "Next File"),
        ("ctrl+p", "prev_file", "Previous File"),
        ("R", "read_all", "Read All"),
        ("m", "toggle_mute", "Toggle Mute"),
        ("s", "snooze", "Snooze"),
        ("apostrophe", "jump_to_entry", "Jump"),
        ("ctrl+d", "scroll_file_down", "Scroll down"),
        ("ctrl+u", "scroll_file_up", "Scroll up"),
    ]

    def __init__(
        self, notifications: list[Notification], *, initial_index: int = 0
    ) -> None:
        """Initialize the notification modal.

        Args:
            notifications: List of notifications to display.
            initial_index: Index of the notification to highlight initially.
        """
        super().__init__()
        self._notifications = list(notifications)
        self._initial_index = initial_index
        self._current_file_index: int = 0
        self._pending_confirm_notification_id: str | None = None
        self._current_image_renderable: KittyImageRenderable | None = None
        self._entry_jump_mode_active = False
        self._entry_jump_hint_to_index: dict[str, int] = {}
        self._entry_jump_index_to_hint: dict[int, str] = {}
        self._entry_jump_last_index: int | None = None

    def compose(self) -> ComposeResult:
        """Compose the modal layout."""
        with Container(id="notification-container"):
            yield Label("Notifications", id="notification-title")
            with Horizontal(id="notification-panels"):
                with Vertical(id="notification-left"):
                    if self._notifications:
                        yield OptionList(
                            *self._create_sectioned_options(),
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
                DEFAULT_HINT_TEXT,
                id="notification-hints",
            )

    @staticmethod
    def _shorten_path(path: str) -> str:
        """Shorten a path by replacing home directory with ~."""
        return path.replace(str(Path.home()), "~")

    def _image_preview(
        self,
        path: str,
        capability: GraphicsCapability,
        *,
        columns: int,
        rows: int,
    ) -> Any:
        """Build an attachment image preview.

        Kept as a method so tests and integrations that patch this module's
        ``image_preview`` symbol still affect preview rendering after the split.
        """
        return image_preview(path, capability, columns=columns, rows=rows)

    def _mark_all_read(self) -> None:
        """Mark all notifications as read in the backing store."""
        mark_all_read()

    def _mark_dismissed(self, notification_id: str) -> None:
        """Mark one notification as dismissed in the backing store."""
        mark_dismissed(notification_id)

    def _mark_muted(self, notification_id: str, muted: bool) -> None:
        """Persist one notification's muted state."""
        mark_muted(notification_id, muted)

    def _mark_snoozed(self, notification_id: str, snooze_until: Any) -> None:
        """Persist one notification's snooze deadline."""
        mark_snoozed(notification_id, snooze_until)

    def _get_highlighted_notification(self) -> Notification | None:
        """Return the notification object for the currently highlighted option."""
        idx = self._get_selected_index()
        if idx is not None and 0 <= idx < len(self._notifications):
            return self._notifications[idx]
        return None

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        """Update the right pane when a different notification is highlighted."""
        self._current_file_index = 0
        if (
            event.option
            and event.option.id is not None
            and not event.option.id.startswith(HEADER_ID_PREFIX)
        ):
            idx = int(event.option.id)
            if 0 <= idx < len(self._notifications):
                self._display_file(self._notifications[idx])

    def _replacement_notification_id_after_dismiss(self, idx: int) -> str | None:
        """Return the notification id that should be highlighted after dismiss."""
        visual_order = self._visual_notification_index_order()
        try:
            visual_position = visual_order.index(idx)
        except ValueError:
            return None

        if visual_position + 1 < len(visual_order):
            replacement_idx = visual_order[visual_position + 1]
        elif visual_position > 0:
            replacement_idx = visual_order[visual_position - 1]
        else:
            return None

        return self._notifications[replacement_idx].id

    def _row_for_notification_index(
        self, option_list: OptionList, notification_idx: int
    ) -> int | None:
        """Return the option-list row position for a notification index."""
        target = str(notification_idx)
        for row in range(option_list.option_count):
            opt = option_list.get_option_at_index(row)
            if opt.id == target:
                return row
        return None

    def on_mount(self) -> None:
        """Focus the option list on mount and display initial file."""
        try:
            option_list = self.query_one("#notification-list", OptionList)
            if 0 <= self._initial_index < len(self._notifications):
                row = self._row_for_notification_index(option_list, self._initial_index)
                if row is not None:
                    option_list.highlighted = row
            option_list.focus()
        except Exception:
            pass

        if self._notifications:
            idx = min(self._initial_index, len(self._notifications) - 1)
            self._display_file(self._notifications[max(0, idx)])

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle option selection (Enter or click)."""
        if (
            event.option
            and event.option.id is not None
            and not event.option.id.startswith(HEADER_ID_PREFIX)
        ):
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
                if option.id is not None and not option.id.startswith(HEADER_ID_PREFIX):
                    return int(option.id)
        except Exception:
            pass
        return None

    def _rebuild_list(
        self, highlight_index: int | None = None, *, show_jump_hints: bool = False
    ) -> None:
        """Rebuild the option list from current notifications."""
        if not show_jump_hints:
            self._clear_entry_jump_hints()
            self._update_hint_footer()

        try:
            option_list = self.query_one("#notification-list", OptionList)
        except Exception:
            return

        option_list.clear_options()

        if not self._notifications:
            option_list.add_class("hidden")
            try:
                self.query_one("#notification-empty", Static)
            except Exception:
                left_panel = self.query_one("#notification-left", Vertical)
                left_panel.mount(
                    Static(
                        "No unread notifications",
                        id="notification-empty",
                    ),
                )
            self._display_file(None)
            return

        jump_hints = self._entry_jump_index_to_hint if show_jump_hints else None
        for option in self._create_sectioned_options(jump_hints=jump_hints):
            option_list.add_option(option)

        if highlight_index is not None:
            row = self._row_for_notification_index(option_list, highlight_index)
            if row is not None:
                option_list.highlighted = row

        self._current_file_index = 0
        notification = self._get_highlighted_notification()
        self._display_file(notification)
