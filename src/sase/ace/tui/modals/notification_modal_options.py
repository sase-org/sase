"""Option rendering and jump-mode behavior for the notification modal."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual import events
from textual.widgets import Label
from textual.widgets.option_list import Option

from sase.ace.tui.actions.navigation.jump_hints import (
    build_jump_hint_maps,
    normalize_jump_key,
)
from sase.notifications import (
    Notification,
    format_relative_time,
    format_relative_until,
    is_priority,
)

from .notification_modal_constants import (
    ACTION_BADGES,
    DEFAULT_HINT_TEXT,
    HEADER_ID_PREFIX,
    SECTIONS,
)


class NotificationOptionMixin:
    """Build sectioned notification options and handle row jump mode."""

    def _create_styled_label(
        self: Any, notification: Notification, *, hint_char: str | None = None
    ) -> Text:
        """Create styled text for a notification option."""
        text = Text()

        if hint_char is not None:
            text.append("[", style="dim")
            text.append(hint_char, style="bold #FFFF00")
            text.append("] ", style="dim")

        if notification.muted:
            text.append("~ ", style="dim")
        elif not notification.read:
            text.append("* ", style="bold #FFD700")
        else:
            text.append("  ", style="")

        body_style = "dim" if notification.muted else ""
        bold_style = "dim" if notification.muted else "bold"

        text.append(f"[{notification.sender}]", style=bold_style)
        text.append(" ", style="")

        if notification.notes:
            note = notification.notes[0]
            if len(note) > 50:
                note = note[:47] + "..."
            text.append(note, style=body_style)
        else:
            text.append("(no message)", style="dim italic")

        text.append(f"  {format_relative_time(notification.timestamp)}", style="dim")

        badge = ACTION_BADGES.get(notification.action, "")
        if badge:
            badge_style = "dim" if notification.muted else "bold #00D7FF"
            text.append(f"  {badge}", style=badge_style)

        if notification.files:
            count = len(notification.files)
            text.append(
                f"  {count} file{'s' if count != 1 else ''}",
                style="dim",
            )

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
        label, color = next((lbl, c) for k, lbl, c in SECTIONS if k == key)
        text = Text()
        accent = f"bold {color}"
        text.append("▌ ", style=accent)
        text.append(label, style=accent)
        text.append(f" · {count}", style=accent)
        return text

    def _create_sectioned_options(
        self: Any, *, jump_hints: dict[int, str] | None = None
    ) -> list[Option]:
        """Create options grouped by section, with disabled header rows."""
        groups: dict[str, list[tuple[int, Notification]]] = {
            key: [] for key, _, _ in SECTIONS
        }
        for i, n in enumerate(self._notifications):
            groups[self._section_for(n)].append((i, n))

        options: list[Option] = []
        for key, _, _ in SECTIONS:
            items = groups[key]
            if not items:
                continue
            options.append(
                Option(
                    self._build_header_text(key, len(items)),
                    id=f"{HEADER_ID_PREFIX}{key}",
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

    def _visual_notification_index_order(self: Any) -> list[int]:
        """Return notification indexes in the order displayed to the user."""
        indexes: list[int] = []
        for option in self._create_sectioned_options():
            option_id = option.id
            if (
                option.disabled
                or option_id is None
                or option_id.startswith(HEADER_ID_PREFIX)
            ):
                continue
            indexes.append(int(option_id))
        return indexes

    def _jump_candidate_indices(self: Any) -> list[int]:
        """Return selectable notification indexes in visual order."""
        return self._visual_notification_index_order()

    def action_jump_to_entry(self: Any) -> None:
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

    def _clear_entry_jump_hints(self: Any) -> None:
        """Clear transient jump hint maps."""
        self._entry_jump_mode_active = False
        self._entry_jump_hint_to_index = {}
        self._entry_jump_index_to_hint = {}

    def _exit_entry_jump_mode(self: Any) -> None:
        """Cancel jump mode and remove hint markers."""
        highlight_index = self._get_selected_index()
        self._clear_entry_jump_hints()
        self._update_hint_footer()
        self._rebuild_list(highlight_index=highlight_index)

    def _handle_entry_jump_key(self: Any, key: str) -> bool:
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
                return self._jump_to_notification_index(last_target)
            key = "1"

        hint_target = self._entry_jump_hint_to_index.get(key)
        if hint_target is None:
            self._exit_entry_jump_mode()
            return True

        current = self._get_selected_index()
        if current is not None:
            self._entry_jump_last_index = current
        return self._jump_to_notification_index(hint_target)

    def _jump_to_notification_index(self: Any, notification_idx: int) -> bool:
        """Highlight the given notification index without activating it."""
        if not 0 <= notification_idx < len(self._notifications):
            self._exit_entry_jump_mode()
            return True

        self._clear_entry_jump_hints()
        self._update_hint_footer()
        self._rebuild_list(highlight_index=notification_idx)
        return True

    def _update_hint_footer(self: Any) -> None:
        """Update the modal help line for normal or jump mode."""
        try:
            footer = self.query_one("#notification-hints", Label)
        except Exception:
            return

        if self._entry_jump_mode_active:
            action = "back" if self._entry_jump_last_index is not None else "first"
            footer.update(f"JUMP ' {action}  <esc> cancel")
        else:
            footer.update(DEFAULT_HINT_TEXT)

    def on_key(self: Any, event: events.Key) -> None:
        """Intercept jump-mode keypresses before modal bindings run."""
        if not self._entry_jump_mode_active:
            return

        key = normalize_jump_key(event.key, event.character)
        if self._handle_entry_jump_key(key):
            event.prevent_default()
            event.stop()
