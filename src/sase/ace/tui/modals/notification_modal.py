"""Notification modal for viewing unread notifications."""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from rich.console import Group
from rich.syntax import Syntax
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList, Static
from textual.widgets.option_list import Option

from sase.ace.hints import build_editor_args
from sase.ace.tui.actions.navigation.jump_hints import (
    build_jump_hint_maps,
    normalize_jump_key,
)
from sase.ace.tui.graphics import (
    GraphicsCapability,
    KittyImageRenderable,
    TerminalControlRenderable,
    image_preview,
    image_preview_size_for_viewport,
    is_supported_image_path,
)
from sase.ace.tui.widgets.file_panel import _EXTENSION_TO_LEXER
from sase.core.time import get_timezone
from sase.notifications import (
    Notification,
    format_relative_time,
    format_relative_until,
    is_priority,
    mark_all_read,
    mark_dismissed,
    mark_muted,
    mark_snoozed,
)

from .base import OptionListNavigationMixin
from .snooze_duration_modal import SnoozeDurationModal


# Action badge mapping
_ACTION_BADGES: dict[str | None, str] = {
    "JumpToChangeSpec": "[CL]",
    "JumpToMentorReview": "[mentor]",
    "JumpToAgent": "[agent]",
    "Tmux": "[tmux]",
    "HITL": "[HITL]",
    "PlanApproval": "[plan]",
    "UserQuestion": "[question]",
    "ViewErrorReport": "[error]",
}


# Section taxonomy: (key, label, color). Order is render order.
_SECTIONS: list[tuple[str, str, str]] = [
    ("priority", "PRIORITY", "#FF4444"),
    ("inbox", "INBOX", "#FFD700"),
    ("muted", "MUTED", "#5FAFAF"),
]

_HEADER_ID_PREFIX = "hdr:"
_DEFAULT_HINT_TEXT = (
    "Enter: select  x: dismiss  m: mute  s: snooze  e: edit  "
    "C-n/C-p: next/prev file  C-d/C-u: scroll  R: read all  q: close"
)


class NotificationModal(OptionListNavigationMixin, ModalScreen[Notification | None]):
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
        ("R", "read_all", "Read All"),  # uppercase R
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
                _DEFAULT_HINT_TEXT,
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
            cleanup = self._consume_image_cleanup_segments()
            content_widget.update(Group(*cleanup, "") if cleanup else "")
            return

        files = notification.files
        # Clamp index
        if self._current_file_index >= len(files):
            self._current_file_index = 0

        file_path = files[self._current_file_index]
        short = self._shorten_path(file_path)
        title.update(f"File {self._current_file_index + 1}/{len(files)}: {short}")

        expanded_path = os.path.expanduser(file_path)

        if is_supported_image_path(expanded_path):
            self._display_image_file(expanded_path, content_widget)
            return

        cleanup = self._consume_image_cleanup_segments()
        try:
            with open(expanded_path, encoding="utf-8") as f:
                content = f.read()
        except Exception:
            text = Text("Could not read file.", style="dim italic")
            content_widget.update(Group(*cleanup, text) if cleanup else text)
            self._reset_file_scroll()
            return

        if not content.strip():
            text = Text("File is empty.", style="dim italic")
            content_widget.update(Group(*cleanup, text) if cleanup else text)
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
        content_widget.update(Group(*cleanup, syntax) if cleanup else syntax)
        self._reset_file_scroll()

    def _display_image_file(self, expanded_path: str, content_widget: Static) -> None:
        """Render an image attachment using the TUI graphics preview layer."""
        cleanup = self._consume_image_cleanup_segments()
        capability = self._graphics_capability()
        columns, rows = self._image_preview_size(content_widget)
        renderable = image_preview(
            expanded_path,
            capability,
            columns=columns,
            rows=rows,
        )
        self._current_image_renderable = (
            renderable if isinstance(renderable, KittyImageRenderable) else None
        )
        content_widget.update(Group(*cleanup, renderable))
        self._reset_file_scroll()

    def _image_preview_size(self, content_widget: Static) -> tuple[int, int]:
        """Choose a placeholder size from the visible notification file pane."""
        try:
            scroll = self.query_one("#notification-file-scroll", VerticalScroll)
        except Exception:
            scroll = None
        return image_preview_size_for_viewport(
            scroll_widget=scroll,
            content_widget=content_widget,
        )

    def _graphics_capability(self) -> GraphicsCapability:
        """Return app graphics support, or a fallback when the modal is unmounted."""
        try:
            capability = getattr(self.app, "graphics_capability", None)  # type: ignore[attr-defined]
        except Exception:
            capability = None
        if isinstance(capability, GraphicsCapability):
            return capability
        return GraphicsCapability.unavailable("terminal graphics were not probed")

    def _consume_image_cleanup_segments(self) -> list[TerminalControlRenderable]:
        """Return terminal cleanup controls for the active Kitty image, if any."""
        current = self._current_image_renderable
        self._current_image_renderable = None
        if isinstance(current, KittyImageRenderable):
            return [TerminalControlRenderable(current.cleanup_sequence())]
        return []

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

    def action_open_in_editor(self) -> None:
        """Open the currently displayed file in $EDITOR."""
        notification = self._get_highlighted_notification()
        if not notification or not notification.files:
            return

        file_path = notification.files[self._current_file_index]
        expanded = os.path.expanduser(file_path)
        editor = os.environ.get("EDITOR") or "nvim"
        editor_args = build_editor_args(editor, [expanded])

        with self.app.suspend():  # type: ignore[attr-defined]
            subprocess.run(editor_args, check=False)

        # Re-render file pane (content may have changed)
        self._display_file(notification)

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        """Update the right pane when a different notification is highlighted."""
        self._current_file_index = 0
        if (
            event.option
            and event.option.id is not None
            and not event.option.id.startswith(_HEADER_ID_PREFIX)
        ):
            idx = int(event.option.id)
            if 0 <= idx < len(self._notifications):
                self._display_file(self._notifications[idx])

    def _create_styled_label(
        self, notification: Notification, *, hint_char: str | None = None
    ) -> Text:
        """Create styled text for a notification option."""
        text = Text()

        if hint_char is not None:
            text.append("[", style="dim")
            text.append(hint_char, style="bold #FFFF00")
            text.append("] ", style="dim")

        # Prefix column is always 2 cells wide so [sender] aligns across rows.
        if notification.muted:
            text.append("~ ", style="dim")
        elif not notification.read:
            text.append("* ", style="bold #FFD700")
        else:
            text.append("  ", style="")

        # Body style: dim everything for muted rows so they read as quieted.
        body_style = "dim" if notification.muted else ""
        bold_style = "dim" if notification.muted else "bold"

        # Sender
        text.append(f"[{notification.sender}]", style=bold_style)
        text.append(" ", style="")

        # First notes line (truncated)
        if notification.notes:
            note = notification.notes[0]
            if len(note) > 50:
                note = note[:47] + "..."
            text.append(note, style=body_style)
        else:
            text.append("(no message)", style="dim italic")

        # Relative time
        text.append(f"  {format_relative_time(notification.timestamp)}", style="dim")

        # Action badge
        badge = _ACTION_BADGES.get(notification.action, "")
        if badge:
            badge_style = "dim" if notification.muted else "bold #00D7FF"
            text.append(f"  {badge}", style=badge_style)

        # File count
        if notification.files:
            count = len(notification.files)
            text.append(
                f"  {count} file{'s' if count != 1 else ''}",
                style="dim",
            )

        # Snooze remaining-time badge
        if notification.snooze_until:
            text.append(
                f"  ⏰ {format_relative_until(notification.snooze_until)}",
                style="dim",
            )

        return text

    @staticmethod
    def _section_for(notification: Notification) -> str:
        """Return the section key for a notification (mute dominates priority)."""
        if notification.muted:
            return "muted"
        if is_priority(notification):
            return "priority"
        return "inbox"

    @staticmethod
    def _build_header_text(key: str, count: int) -> Text:
        """Build the styled header row text for a section."""
        label, color = next((lbl, c) for k, lbl, c in _SECTIONS if k == key)
        text = Text()
        accent = f"bold {color}"
        text.append("▌ ", style=accent)
        text.append(label, style=accent)
        text.append(f" · {count}", style=accent)
        return text

    def _create_sectioned_options(
        self, *, jump_hints: dict[int, str] | None = None
    ) -> list[Option]:
        """Create options grouped by section, with disabled header rows."""
        groups: dict[str, list[tuple[int, Notification]]] = {
            key: [] for key, _, _ in _SECTIONS
        }
        for i, n in enumerate(self._notifications):
            groups[self._section_for(n)].append((i, n))

        options: list[Option] = []
        for key, _, _ in _SECTIONS:
            items = groups[key]
            if not items:
                continue
            options.append(
                Option(
                    self._build_header_text(key, len(items)),
                    id=f"{_HEADER_ID_PREFIX}{key}",
                    disabled=True,
                )
            )
            for idx, n in items:
                options.append(
                    Option(
                        self._create_styled_label(
                            n,
                            hint_char=(
                                None if jump_hints is None else jump_hints.get(idx)
                            ),
                        ),
                        id=str(idx),
                    )
                )
        return options

    def _visual_notification_index_order(self) -> list[int]:
        """Return notification indexes in the order displayed to the user."""
        indexes: list[int] = []
        for option in self._create_sectioned_options():
            option_id = option.id
            if (
                option.disabled
                or option_id is None
                or option_id.startswith(_HEADER_ID_PREFIX)
            ):
                continue
            indexes.append(int(option_id))
        return indexes

    def _jump_candidate_indices(self) -> list[int]:
        """Return selectable notification indexes in visual order."""
        return self._visual_notification_index_order()

    def action_jump_to_entry(self) -> None:
        """Enter one-key jump mode for notification rows."""
        indices = self._jump_candidate_indices()
        if not indices:
            return
        self._entry_jump_hint_to_index, self._entry_jump_index_to_hint = (
            build_jump_hint_maps(indices)
        )
        if not self._entry_jump_hint_to_index:
            return

        self._entry_jump_mode_active = True
        self._update_hint_footer()
        self._rebuild_list(
            highlight_index=self._get_selected_index(),
            show_jump_hints=True,
        )

    def _clear_entry_jump_hints(self) -> None:
        """Clear transient jump hint maps."""
        self._entry_jump_mode_active = False
        self._entry_jump_hint_to_index = {}
        self._entry_jump_index_to_hint = {}

    def _exit_entry_jump_mode(self) -> None:
        """Cancel jump mode and remove hint markers."""
        highlight_index = self._get_selected_index()
        self._clear_entry_jump_hints()
        self._update_hint_footer()
        self._rebuild_list(highlight_index=highlight_index)

    def _handle_entry_jump_key(self, key: str) -> bool:
        """Handle one keypress while notification jump mode is active."""
        if not self._entry_jump_mode_active:
            return False
        if key == "escape":
            self._exit_entry_jump_mode()
            return True

        if key == "apostrophe":
            if (
                self._entry_jump_last_index is not None
                and 0 <= self._entry_jump_last_index < len(self._notifications)
            ):
                last_target = self._entry_jump_last_index
                current = self._get_selected_index()
                if current is not None:
                    self._entry_jump_last_index = current
                return self._select_notification_index(last_target)
            key = "1"

        hint_target = self._entry_jump_hint_to_index.get(key)
        if hint_target is None:
            self._exit_entry_jump_mode()
            return True

        current = self._get_selected_index()
        if current is not None:
            self._entry_jump_last_index = current
        return self._select_notification_index(hint_target)

    def _select_notification_index(self, notification_idx: int) -> bool:
        """Highlight and select the given notification index."""
        if not 0 <= notification_idx < len(self._notifications):
            self._exit_entry_jump_mode()
            return True

        try:
            option_list = self.query_one("#notification-list", OptionList)
            row = self._row_for_notification_index(option_list, notification_idx)
            if row is not None:
                option_list.highlighted = row
        except Exception:
            pass

        notification = self._notifications[notification_idx]
        self._clear_entry_jump_hints()
        self._update_hint_footer()
        self.dismiss(notification)
        return True

    def _update_hint_footer(self) -> None:
        """Update the modal help line for normal or jump mode."""
        try:
            footer = self.query_one("#notification-hints", Label)
        except Exception:
            return

        if self._entry_jump_mode_active:
            action = "back" if self._entry_jump_last_index is not None else "first"
            footer.update(f"JUMP ' {action}  <esc> cancel")
        else:
            footer.update(_DEFAULT_HINT_TEXT)

    def on_key(self, event: events.Key) -> None:
        """Intercept jump-mode keypresses before modal bindings run."""
        if not self._entry_jump_mode_active:
            return

        key = normalize_jump_key(event.key, event.character)
        if self._handle_entry_jump_key(key):
            event.prevent_default()
            event.stop()

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
            pass  # No list if empty

        # Display file for the initially selected notification
        if self._notifications:
            idx = min(self._initial_index, len(self._notifications) - 1)
            self._display_file(self._notifications[max(0, idx)])

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle option selection (Enter or click)."""
        if (
            event.option
            and event.option.id is not None
            and not event.option.id.startswith(_HEADER_ID_PREFIX)
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
                if option.id is not None and not option.id.startswith(
                    _HEADER_ID_PREFIX
                ):
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

        # Plan/question notifications require an explicit y/n confirmation.
        if notification.action in ("PlanApproval", "UserQuestion"):
            self._pending_confirm_notification_id = notification.id
            self.notify("Dismiss plan/question notification? (y/n)")
            return

        self._pending_confirm_notification_id = None
        self._dismiss_notification_by_index(idx)

    def action_confirm_dismiss_notification(self) -> None:
        """Confirm dismissal of a plan/question notification."""
        pending_id = self._pending_confirm_notification_id
        if pending_id is None:
            return

        idx = next(
            (
                i
                for i, notification in enumerate(self._notifications)
                if notification.id == pending_id
            ),
            None,
        )
        self._pending_confirm_notification_id = None
        if idx is None:
            return

        self._dismiss_notification_by_index(idx)

    def action_cancel_dismiss_notification(self) -> None:
        """Cancel a pending plan/question dismiss confirmation."""
        if self._pending_confirm_notification_id is None:
            return
        self._pending_confirm_notification_id = None
        self.notify("Dismiss canceled")

    def _dismiss_notification_by_index(self, idx: int) -> None:
        """Dismiss notification at index and rebuild the list UI."""
        notification = self._notifications[idx]
        replacement_id = self._replacement_notification_id_after_dismiss(idx)
        mark_dismissed(notification.id)

        self._notifications.pop(idx)
        highlight = next(
            (
                i
                for i, notification in enumerate(self._notifications)
                if notification.id == replacement_id
            ),
            None,
        )
        self._rebuild_list(highlight_index=highlight)

    def action_toggle_mute(self) -> None:
        """Toggle mute on the highlighted notification."""
        idx = self._get_selected_index()
        if idx is None or idx >= len(self._notifications):
            return

        notification = self._notifications[idx]
        new_muted = not notification.muted
        was_snoozed = notification.snooze_until is not None
        mark_muted(notification.id, new_muted)
        notification.muted = new_muted
        if not new_muted:
            notification.snooze_until = None

        # Rebuild list so the new prefix / dim style is reflected. Keep the
        # highlight on the same row so users muting a streak don't lose
        # their place.
        self._rebuild_list(highlight_index=idx)
        if new_muted:
            self.notify("Muted")
        elif was_snoozed:
            self.notify("Unmuted (snooze cancelled)")
        else:
            self.notify("Unmuted")

    def action_snooze(self) -> None:
        """Snooze the highlighted notification via the duration picker."""
        idx = self._get_selected_index()
        if idx is None or idx >= len(self._notifications):
            return

        notification = self._notifications[idx]

        def _on_picked(result: timedelta | datetime | None) -> None:
            if result is None:
                self.notify("Snooze cancelled")
                return
            if isinstance(result, datetime):
                snooze_until = result
                description = "until tomorrow morning"
            else:
                snooze_until = datetime.now(get_timezone()) + result
                description = f"for {self._format_delta(result)}"

            mark_snoozed(notification.id, snooze_until)
            notification.muted = True
            notification.snooze_until = snooze_until.isoformat()

            self._rebuild_list(highlight_index=idx)
            self.notify(f"Snoozed {description}")

        self.app.push_screen(SnoozeDurationModal(), callback=_on_picked)

    @staticmethod
    def _format_delta(delta: timedelta) -> str:
        """Format a timedelta for the snooze toast (e.g. '15m', '1h30m')."""
        total = int(delta.total_seconds())
        hours, remainder = divmod(total, 3600)
        minutes, seconds = divmod(remainder, 60)
        parts: list[str] = []
        if hours:
            parts.append(f"{hours}h")
        if minutes:
            parts.append(f"{minutes}m")
        if seconds and not hours and not minutes:
            parts.append(f"{seconds}s")
        return "".join(parts) or "0s"

    def action_read_all(self) -> None:
        """Mark all notifications as read and rebuild the display."""
        mark_all_read()

        # Update local state
        for n in self._notifications:
            n.read = True

        self._rebuild_list()

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

        jump_hints = self._entry_jump_index_to_hint if show_jump_hints else None
        for option in self._create_sectioned_options(jump_hints=jump_hints):
            option_list.add_option(option)

        # `highlight_index` is a notification index; translate to row position
        # in the freshly-built (sectioned) option list.
        if highlight_index is not None:
            row = self._row_for_notification_index(option_list, highlight_index)
            if row is not None:
                option_list.highlighted = row

        # Update right pane for whatever is now highlighted
        self._current_file_index = 0
        notification = self._get_highlighted_notification()
        self._display_file(notification)
