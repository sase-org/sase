"""Notification modal for viewing unread notifications."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList, Static

from sase.ace.tui.graphics import (
    ImageRenderContext,
    image_preview,
)
from sase.notifications import (
    Notification,
    mark_all_read,
    mark_dismissed,
    mark_many_dismissed,
    mark_many_muted,
    mark_many_snoozed,
    mark_muted,
    mark_snoozed,
)

from .base import OptionListNavigationMixin
from .notification_modal_actions import NotificationStateActionsMixin
from .notification_modal_attachments import NotificationAttachmentMixin
from .notification_modal_constants import DEFAULT_HINT_TEXT, HEADER_ID_PREFIX
from .notification_modal_options import NotificationOptionMixin
from .notification_modal_question import NotificationQuestionMixin
from .notification_modal_report import NotificationReportMixin
from .notification_modal_sent_at import NotificationSentAtMixin
from .notification_modal_tags import (
    NotificationTagStrip,
    NotificationTagTab,
    classify_notification_modal_tabs,
)


class NotificationModal(
    NotificationQuestionMixin,
    NotificationReportMixin,
    NotificationAttachmentMixin,
    NotificationOptionMixin,
    NotificationStateActionsMixin,
    NotificationSentAtMixin,
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
        ("d", "debug_view", "Debug"),
        ("y", "confirm_dismiss_notification", "Confirm Dismiss"),
        ("n", "cancel_dismiss_notification", "Cancel Dismiss"),
        ("e", "open_in_editor", "Edit"),
        ("V", "view_image", "View"),
        ("Y", "copy_file_path", "Copy path"),
        ("ctrl+n", "next_file", "Next File"),
        ("ctrl+p", "prev_file", "Previous File"),
        ("left_square_bracket", "prev_notification_tag_tab", "Prev Tag"),
        ("right_square_bracket", "next_notification_tag_tab", "Next Tag"),
        ("R", "read_all", "Read All"),
        ("M", "toggle_mute", "Toggle Mute"),
        ("m", "toggle_mark", "Mark"),
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
        self._notification_tab_keys: dict[str, str | None] = {}
        tabs = self._tag_tabs()
        self._active_notification_tag: str | None = tabs[0].tag if tabs else None
        self._pending_confirm_notification_id: str | None = None
        self._pending_confirm_notification_ids: list[str] | None = None
        self._marked_notification_ids: set[str] = set()
        self._entry_jump_mode_active = False
        self._entry_jump_pending_prefix = ""
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
                        tabs = self._tag_tabs()
                        yield NotificationTagStrip(
                            tabs,
                            self._active_notification_tag,
                            id="notification-tag-tabs",
                            classes="hidden" if len(tabs) <= 1 else None,
                        )
                        yield OptionList(
                            *self._create_notification_options(),
                            id="notification-list",
                        )
                    else:
                        yield Static(
                            "No unread notifications",
                            id="notification-empty",
                        )
                with Vertical(id="notification-right"):
                    yield Label("No files attached", id="notification-file-title")
                    yield Label("", id="notification-sent-at", classes="hidden")
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
        context: ImageRenderContext,
        *,
        columns: int,
        rows: int,
    ) -> Any:
        """Build an attachment image preview.

        Kept as a method so tests and integrations that patch this module's
        ``image_preview`` symbol still affect preview rendering after the split.
        """
        return image_preview(path, context, columns=columns, rows=rows)

    def _mark_all_read(self) -> None:
        """Mark all notifications as read in the backing store."""
        mark_all_read()

    def _mark_dismissed(self, notification_id: str) -> None:
        """Mark one notification as dismissed in the backing store."""
        mark_dismissed(notification_id)

    def _mark_many_dismissed(self, notification_ids: list[str]) -> int:
        """Mark multiple notifications as dismissed in the backing store."""
        return mark_many_dismissed(notification_ids)

    def _mark_many_muted(self, notification_ids: list[str], muted: bool) -> int:
        """Persist multiple notifications' muted state."""
        return mark_many_muted(notification_ids, muted)

    def _mark_muted(self, notification_id: str, muted: bool) -> None:
        """Persist one notification's muted state."""
        mark_muted(notification_id, muted)

    def _mark_many_snoozed(self, notification_ids: list[str], snooze_until: Any) -> int:
        """Persist multiple notifications' snooze deadline."""
        return mark_many_snoozed(notification_ids, snooze_until)

    def _mark_snoozed(self, notification_id: str, snooze_until: Any) -> bool:
        """Persist one notification's snooze deadline."""
        return mark_snoozed(notification_id, snooze_until)

    def _get_highlighted_notification(self) -> Notification | None:
        """Return the notification object for the currently highlighted option."""
        idx = self._get_selected_index()
        if idx is not None and 0 <= idx < len(self._notifications):
            return self._notifications[idx]
        return None

    def action_debug_view(self) -> None:
        """Open Gate Debug for the selected row, gate-backed or otherwise."""
        notification = self._get_highlighted_notification()
        if notification is None:
            self.notify("No notification selected", severity="warning")
            return
        from sase.notification_gates.debug import debug_context_from_notification

        from .gate_debug_modal import GateDebugModal

        self.app.push_screen(
            GateDebugModal(debug_context_from_notification(notification))
        )

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
                self._update_hint_footer()

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

    def _replacement_notification_id_after_reclassification(
        self, idx: int
    ) -> str | None:
        """Return the nearby visible id before a row moves to another tab."""
        return self._replacement_notification_id_after_dismiss(idx)

    def _replacement_notification_id_after_bulk_dismiss(
        self, indices: list[int]
    ) -> str | None:
        """Return the notification id to highlight after bulk dismiss."""
        if not indices:
            return None
        visual_order = self._visual_notification_index_order()
        marked = set(indices)
        last_visual_position: int | None = None
        for position, idx in enumerate(visual_order):
            if idx in marked:
                last_visual_position = position
        if last_visual_position is None:
            return None

        for position in range(last_visual_position + 1, len(visual_order)):
            idx = visual_order[position]
            if idx not in marked:
                return self._notifications[idx].id
        for position in range(last_visual_position - 1, -1, -1):
            idx = visual_order[position]
            if idx not in marked:
                return self._notifications[idx].id
        return None

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
        display_index: int | None = None
        try:
            option_list = self.query_one("#notification-list", OptionList)
            row: int | None = None
            if 0 <= self._initial_index < len(self._notifications):
                row = self._row_for_notification_index(option_list, self._initial_index)
                if row is not None:
                    display_index = self._initial_index
            if row is None:
                display_index = self._first_visible_notification_index()
                if display_index is not None:
                    row = self._row_for_notification_index(option_list, display_index)
            if row is not None:
                option_list.highlighted = row
            option_list.focus()
        except Exception:
            pass

        if self._notifications:
            if display_index is None:
                display_index = self._first_visible_notification_index()
            if display_index is None:
                display_index = max(
                    0, min(self._initial_index, len(self._notifications) - 1)
                )
            self._display_file(self._notifications[display_index])

    def _tag_tabs(self) -> list[NotificationTagTab]:
        """Return tag tabs for the current in-memory modal dataset.

        Rebuilding also refreshes ``_notification_tab_keys``, so per-row tab
        membership stays a dict lookup instead of one core call per row.
        """
        tabs, self._notification_tab_keys = classify_notification_modal_tabs(
            self._notifications
        )
        return tabs

    def _coerce_active_notification_tag(
        self,
        *,
        previous_tabs: list[NotificationTagTab] | None = None,
    ) -> None:
        """Keep the active tag valid after notification mutations."""
        current_tags = [tab.tag for tab in self._tag_tabs()]
        if not current_tags:
            self._active_notification_tag = None
            return
        if self._active_notification_tag in current_tags:
            return

        if previous_tabs is not None:
            previous_tags = [tab.tag for tab in previous_tabs]
            try:
                old_position = previous_tags.index(self._active_notification_tag)
            except ValueError:
                old_position = -1

            if old_position >= 0:
                for offset in range(1, len(previous_tags) + 1):
                    for candidate_position in (
                        old_position + offset,
                        old_position - offset,
                    ):
                        if not 0 <= candidate_position < len(previous_tags):
                            continue
                        candidate = previous_tags[candidate_position]
                        if candidate in current_tags:
                            self._active_notification_tag = candidate
                            return

        self._active_notification_tag = current_tags[0]

    def _refresh_tag_strip(self) -> None:
        """Refresh the visible tag strip when mounted."""
        try:
            strip = self.query_one("#notification-tag-tabs", NotificationTagStrip)
        except Exception:
            return

        tabs = self._tag_tabs()
        strip.set_tabs(tabs, self._active_notification_tag)
        if len(tabs) <= 1:
            strip.add_class("hidden")
        else:
            strip.remove_class("hidden")

    def _first_visible_notification_index(self) -> int | None:
        """Return the first selectable notification for the active tab."""
        visible = self._visual_notification_index_order()
        return visible[0] if visible else None

    def _switch_notification_tag_tab(self, tag: str | None) -> None:
        """Switch the active tag tab and rebuild the in-memory list."""
        tags = [tab.tag for tab in self._tag_tabs()]
        if not tags:
            next_tag = None
        elif tag in tags:
            next_tag = tag
        else:
            next_tag = tags[0]
        if next_tag == self._active_notification_tag:
            return

        self._active_notification_tag = next_tag
        self._clear_tab_scoped_state()
        self._rebuild_list(highlight_index=self._first_visible_notification_index())

    def _clear_tab_scoped_state(self) -> None:
        """Clear modal-local state whose selected rows may now be hidden."""
        self._marked_notification_ids.clear()
        self._pending_confirm_notification_id = None
        self._pending_confirm_notification_ids = None

    def _visible_notification_index_for_id(
        self, notification_id: str | None
    ) -> int | None:
        """Return a notification index if the id is visible in the active tab."""
        if notification_id is None:
            return None
        for idx in self._visual_notification_index_order():
            if self._notifications[idx].id == notification_id:
                return idx
        return None

    def _rebuild_after_notification_reclassification(
        self,
        *,
        previous_tabs: list[NotificationTagTab],
        changed_notification_id: str,
        replacement_notification_id: str | None,
    ) -> None:
        """Rebuild after one row changes which top-level tab owns it."""
        previous_active_tag = self._active_notification_tag
        self._coerce_active_notification_tag(previous_tabs=previous_tabs)
        tab_switched = self._active_notification_tag != previous_active_tag
        if tab_switched:
            self._clear_tab_scoped_state()
            highlight = self._first_visible_notification_index()
        else:
            highlight = self._visible_notification_index_for_id(changed_notification_id)
            if highlight is None:
                highlight = self._visible_notification_index_for_id(
                    replacement_notification_id
                )
            if highlight is None:
                highlight = self._first_visible_notification_index()

        self._rebuild_list(highlight_index=highlight)

    def action_prev_notification_tag_tab(self) -> None:
        """Switch to the previous notification tag tab."""
        self._coerce_active_notification_tag()
        tags = [tab.tag for tab in self._tag_tabs()]
        if len(tags) <= 1:
            return
        try:
            position = tags.index(self._active_notification_tag)
        except ValueError:
            position = 0
        self._switch_notification_tag_tab(tags[(position - 1) % len(tags)])

    def action_next_notification_tag_tab(self) -> None:
        """Switch to the next notification tag tab."""
        self._coerce_active_notification_tag()
        tags = [tab.tag for tab in self._tag_tabs()]
        if len(tags) <= 1:
            return
        try:
            position = tags.index(self._active_notification_tag)
        except ValueError:
            position = 0
        self._switch_notification_tag_tab(tags[(position + 1) % len(tags)])

    def on_notification_tag_strip_tab_clicked(
        self, event: NotificationTagStrip.TabClicked
    ) -> None:
        """Handle mouse selection of a notification tag tab."""
        event.stop()
        self._switch_notification_tag_tab(event.tag)

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
        self._coerce_active_notification_tag()
        self._refresh_tag_strip()

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
        for option in self._create_notification_options(jump_hints=jump_hints):
            option_list.add_option(option)

        if highlight_index is not None:
            row = self._row_for_notification_index(option_list, highlight_index)
            if row is not None:
                option_list.highlighted = row

        self._current_file_index = 0
        notification = self._get_highlighted_notification()
        self._display_file(notification)
