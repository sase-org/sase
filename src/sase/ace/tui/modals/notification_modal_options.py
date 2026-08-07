"""Option rendering and jump-mode behavior for the notification modal."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual import events
from textual.widgets import Label
from textual.widgets.option_list import Option

from sase.ace.tui.actions.navigation.jump_hints import normalize_jump_key
from sase.notification_gates import PRIVILEGED_GATE_ACTIONS
from sase.notifications import (
    Notification,
    format_relative_time,
    format_relative_until,
)
from sase.notifications.sort import activity_sort_key
from sase.project_display_names import (
    humanize_cl_names_in_text,
    humanize_vcs_refs_in_text,
)

from .notification_modal_constants import (
    ACTION_BADGES,
    DEFAULT_HINT_TEXT,
    GATE_HINT_TEXT,
    QUESTION_HINT_TEXT,
    notification_icon,
)

from .notification_modal_tags import (
    notification_display_tags,
    notification_matches_tag_tab,
    shorten_notification_tag,
)
from .pane_entry_jump import KeyedPaneEntryJumpMixin

_GATE_HINT_ACTIONS = PRIVILEGED_GATE_ACTIONS - {"UserQuestion"}
_REDUNDANT_AGENT_SENDERS = frozenset({"user-agent", "user-workflow"})


class NotificationOptionMixin(KeyedPaneEntryJumpMixin[int]):
    """Build notification row options and handle row jump mode.

    Rows are keyed by their index into the modal's unsorted notification list,
    which is what every other selection path here speaks, so the shared jump
    machinery sees those indexes through the keyed adapter.
    """

    @staticmethod
    def _show_sender_label(notification: Notification) -> bool:
        """Return whether the sender prefix adds useful row context."""
        return not (
            notification.action == "JumpToAgent"
            and notification.sender in _REDUNDANT_AGENT_SENDERS
        )

    def _create_styled_label(
        self: Any,
        notification: Notification,
        *,
        hint_char: str | None = None,
        is_marked: bool = False,
    ) -> Text:
        """Create styled text for a notification option."""
        text = Text()

        if is_marked:
            text.append("▶ ", style="bold #FFFF00")

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

        text.append(f"{notification_icon(notification.action, notification.icon)} ")

        body_style = "dim" if notification.muted else ""
        bold_style = "dim" if notification.muted else "bold"

        if self._show_sender_label(notification):
            text.append(f"[{notification.sender}]", style=bold_style)
            text.append(" ", style="")

        if notification.notes:
            note = _humanize_notification_text(notification.notes[0])
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

        tags = notification_display_tags(notification)
        if tags:
            visible_tags = tags[:3]
            for tag in visible_tags:
                text.append(
                    f"  #{shorten_notification_tag(tag, max_width=14)}",
                    style="dim #87D7FF",
                )
            remaining = len(tags) - len(visible_tags)
            if remaining > 0:
                text.append(f"  +{remaining}", style="dim #87D7FF")

        return text

    def _create_notification_options(
        self: Any, *, jump_hints: dict[int, str] | None = None
    ) -> list[Option]:
        """Create a flat, activity-sorted option list for the active tab.

        Rows are ordered by ``resurfaced_at ?? timestamp`` so a resurfaced
        snooze is recent activity rather than staying buried at its original
        creation time.
        """
        active_tag: str | None = getattr(self, "_active_notification_tag", None)
        tab_keys: dict[str, str | None] = getattr(self, "_notification_tab_keys", {})
        rows: list[tuple[int, Notification]] = []
        for i, n in enumerate(self._notifications):
            if n.id in tab_keys:
                if tab_keys[n.id] != active_tag:
                    continue
            elif not notification_matches_tag_tab(n, active_tag):
                continue
            rows.append((i, n))
        rows.sort(key=lambda pair: activity_sort_key(pair[1]), reverse=True)

        options: list[Option] = []
        marked_ids: set[str] = getattr(self, "_marked_notification_ids", set())
        for idx, n in rows:
            options.append(
                Option(
                    self._create_styled_label(
                        n,
                        hint_char=None if jump_hints is None else jump_hints.get(idx),
                        is_marked=n.id in marked_ids,
                    ),
                    id=str(idx),
                )
            )
        return options

    def _create_sectioned_options(
        self: Any, *, jump_hints: dict[int, str] | None = None
    ) -> list[Option]:
        """Compatibility wrapper for the former sectioned option builder."""
        return self._create_notification_options(jump_hints=jump_hints)

    def _visual_notification_index_order(self: Any) -> list[int]:
        """Return notification indexes in the order displayed to the user."""
        indexes: list[int] = []
        for option in self._create_notification_options():
            option_id = option.id
            if option.disabled or option_id is None:
                continue
            indexes.append(int(option_id))
        return indexes

    # -- jump host hooks ----------------------------------------------------

    def _jump_target_keys(self: Any) -> list[int]:
        """Return selectable notification indexes in visual order."""
        return self._visual_notification_index_order()

    def _jump_current_key(self: Any) -> int | None:
        return self._get_selected_index()

    def _jump_select_key(self: Any, key: int) -> None:
        # ``_rebuild_list`` without ``show_jump_hints`` drops the hint markers
        # and refreshes the footer on its way to moving the highlight.
        self._rebuild_list(highlight_index=key)

    def _jump_repaint(self: Any) -> None:
        highlight_index = self._get_selected_index()
        self._update_hint_footer()
        self._rebuild_list(
            highlight_index=highlight_index,
            show_jump_hints=self.jump_mode_active,
        )

    def _update_hint_footer(self: Any) -> None:
        """Update the modal help line for normal or jump mode."""
        try:
            footer = self.query_one("#notification-hints", Label)
        except Exception:
            return

        if self.jump_mode_active:
            action = "back" if self.jump_back_stack else "first"
            footer.update(f"JUMP ' {action}  <esc> cancel")
        elif (
            notification := self._get_highlighted_notification()
        ) is not None and notification.action == "UserQuestion":
            footer.update(QUESTION_HINT_TEXT)
        elif notification is not None and notification.action in _GATE_HINT_ACTIONS:
            footer.update(GATE_HINT_TEXT)
        else:
            footer.update(DEFAULT_HINT_TEXT)

    def on_key(self: Any, event: events.Key) -> None:
        """Intercept jump-mode keypresses before modal bindings run."""
        if not self.jump_mode_active:
            return

        key = normalize_jump_key(event.key, event.character)
        if self.handle_jump_key(key):
            event.prevent_default()
            event.stop()


def _humanize_notification_text(text: str) -> str:
    return humanize_cl_names_in_text(humanize_vcs_refs_in_text(text))
