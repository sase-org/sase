"""Shared confirmation dialog foundation for the ace TUI."""

from __future__ import annotations

import re
from enum import Enum
from typing import Literal

from rich.style import Style
from rich.text import Text
from textual._context import NoActiveAppError
from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class ConfirmKind(Enum):
    """Visual severity for a confirmation dialog."""

    NEUTRAL = "neutral"
    DANGER = "danger"


ConfirmDefault = Literal["confirm", "cancel"]
ButtonVariant = Literal["default", "primary", "success", "warning", "error"]

_DEFAULT_ICONS = {
    ConfirmKind.NEUTRAL: "?",
    ConfirmKind.DANGER: "!",
}

_SUBJECT_HEADER_RE = re.compile(r"^(?P<label>[^:\n]+:)(?P<rest>.*)$")
_SUBJECT_COUNT_RE = re.compile(
    r"^(?P<prefix>\s*)(?P<count>\d+)(?P<units>(?:\s+\S.*)?)$"
)
_SUBJECT_ENTRY_RE = re.compile(
    r"^\s{2,}(?P<name>\S+)(?:(?P<gap>\s+)(?P<sigil>@)(?P<handle>\S+))?\s*$"
)

_FALLBACK_THEME_COLORS = {
    "accent": "cyan",
    "error": "red",
    "foreground": "white",
    "primary": "cyan",
    "success": "green",
    "warning": "yellow",
}

_PALETTE_THEME_ATTRS = {
    ConfirmKind.NEUTRAL: {
        "message": "foreground",
        "plain_subject": "accent",
        "subject_bullet": "primary",
        "subject_count": "accent",
        "subject_handle": "accent",
        "subject_header_label": "primary",
        "subject_name": "success",
        "subject_sigil": "foreground",
        "subject_units": "foreground",
        "subtitle_cancel_key": "foreground",
        "subtitle_confirm_key": "accent",
        "subtitle_text": "foreground",
        "title_icon": "accent",
        "title_text": "foreground",
    },
    ConfirmKind.DANGER: {
        "message": "foreground",
        "plain_subject": "warning",
        "subject_bullet": "error",
        "subject_count": "error",
        "subject_handle": "accent",
        "subject_header_label": "warning",
        "subject_name": "success",
        "subject_sigil": "foreground",
        "subject_units": "foreground",
        "subtitle_cancel_key": "foreground",
        "subtitle_confirm_key": "error",
        "subtitle_text": "foreground",
        "title_icon": "error",
        "title_text": "foreground",
    },
}

_PALETTE_BOLD_ROLES = frozenset(
    {
        "message",
        "subject_count",
        "subject_handle",
        "subject_header_label",
        "subject_name",
        "subtitle_confirm_key",
        "title_icon",
        "title_text",
    }
)
_PALETTE_DIM_ROLES = frozenset(
    {
        "subject_sigil",
        "subject_units",
        "subtitle_cancel_key",
        "subtitle_text",
    }
)


class ConfirmDialog(ModalScreen[bool]):
    """Canonical binary yes/no confirmation dialog."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("q", "cancel", "Cancel"),
        ("y", "confirm", "Yes"),
        ("n", "cancel", "No"),
    ]

    def __init__(
        self,
        title: str,
        message: str,
        *,
        subject: str | None = None,
        kind: ConfirmKind = ConfirmKind.NEUTRAL,
        icon: str | None = None,
        confirm_label: str = "Yes",
        cancel_label: str = "No",
        default: ConfirmDefault = "cancel",
    ) -> None:
        super().__init__()
        self.add_class("confirm-dialog")
        self._title = title
        self._message = message
        self._subject = subject
        self._kind = kind
        self._icon = icon
        self._confirm_label = confirm_label
        self._cancel_label = cancel_label
        self._default = default

    def compose(self) -> ComposeResult:
        """Compose the shared confirmation panel."""
        dialog = Container(
            id="confirm-dialog-container",
            classes=self._dialog_classes(),
        )
        self._apply_dialog_frame(dialog)
        with dialog:
            yield Static(
                self._message_text(),
                id="confirm-message",
                classes="confirm-dialog-message",
            )
            yield Static(
                self._styled_subject_text(),
                id="confirm-subject",
                classes=self._subject_classes(),
            )
            with Horizontal(id="confirm-buttons", classes="confirm-dialog-buttons"):
                yield Button(
                    self._button_label(self._confirm_label, "y"),
                    id="confirm-btn",
                    variant=self._confirm_button_variant(),
                )
                yield Button(
                    self._button_label(self._cancel_label, "n"),
                    id="cancel-btn",
                    variant=self._cancel_button_variant(),
                )

    def on_mount(self) -> None:
        """Focus the configured default button."""
        self.call_after_refresh(self._focus_default_button)

    def _focus_default_button(self) -> None:
        """Focus the default button after Textual finishes mounting children."""
        button_id = "#confirm-btn" if self._default == "confirm" else "#cancel-btn"
        try:
            self.query_one(button_id, Button).focus()
        except (NoMatches, LookupError):
            return

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm-btn":
            self.dismiss(True)
        else:
            self.dismiss(False)

    def action_cancel(self) -> None:
        self.dismiss(False)

    def action_confirm(self) -> None:
        self.dismiss(True)

    def _set_kind(self, kind: ConfirmKind, *, icon: str | None = None) -> None:
        """Update the severity styling for dialogs with staged confirmations."""
        self._kind = kind
        self._icon = icon
        dialog = self.query_one("#confirm-dialog-container", Container)
        dialog.set_class(kind is ConfirmKind.NEUTRAL, "confirm-dialog--neutral")
        dialog.set_class(kind is ConfirmKind.DANGER, "confirm-dialog--danger")
        self._apply_dialog_frame(dialog)
        self.query_one("#confirm-message", Static).update(self._message_text())
        self.query_one("#confirm-subject", Static).update(self._styled_subject_text())
        self.query_one("#confirm-btn", Button).variant = self._confirm_button_variant()
        self.query_one("#cancel-btn", Button).variant = self._cancel_button_variant()

    def _set_title(self, title: str, *, icon: str | None = None) -> None:
        """Update the border title."""
        self._title = title
        if icon is not None:
            self._icon = icon
        self._apply_dialog_frame(self.query_one("#confirm-dialog-container", Container))

    def _set_message(self, message: str) -> None:
        """Update the body message."""
        self._message = message
        self.query_one("#confirm-message", Static).update(self._message_text())

    def _set_subject(self, subject: str | None) -> None:
        """Update the emphasized subject line."""
        self._subject = subject
        widget = self.query_one("#confirm-subject", Static)
        widget.update(self._styled_subject_text())
        widget.set_class(subject is None, "is-empty")

    def _set_confirm_label(self, label: str) -> None:
        self._confirm_label = label
        self.query_one("#confirm-btn", Button).label = self._button_label(label, "y")

    def _dialog_classes(self) -> str:
        return f"confirm-dialog-panel confirm-dialog--{self._kind.value}"

    def _subject_classes(self) -> str:
        classes = ["confirm-dialog-subject"]
        if self._subject is None:
            classes.append("is-empty")
        return " ".join(classes)

    def _apply_dialog_frame(self, dialog: Container) -> None:
        dialog.border_title = self._build_border_title()
        dialog.border_subtitle = self._build_border_subtitle()

    def _build_border_title(self) -> Text:
        palette = self._resolve_palette()
        title = Text()
        title.append(
            self._icon or _DEFAULT_ICONS[self._kind],
            style=palette["title_icon"],
        )
        title.append("  ")
        title.append(self._title, style=palette["title_text"])
        return title

    def _build_border_subtitle(self) -> Text:
        palette = self._resolve_palette()
        subtitle = Text()
        subtitle.append("y", style=palette["subtitle_confirm_key"])
        subtitle.append(" confirm ", style=palette["subtitle_text"])
        subtitle.append("·", style=palette["subtitle_text"])
        subtitle.append(" ", style=palette["subtitle_text"])
        subtitle.append("n/esc", style=palette["subtitle_cancel_key"])
        subtitle.append(" cancel", style=palette["subtitle_text"])
        return subtitle

    def _message_text(self) -> Text:
        return Text(self._message, style=self._resolve_palette()["message"])

    def _styled_subject_text(self) -> Text:
        text = Text()
        if self._subject is None:
            return text
        palette = self._resolve_palette()
        for index, line in enumerate(self._subject.splitlines()):
            if index:
                text.append("\n")
            self._append_styled_subject_line(text, line, palette)
        return text

    def _append_styled_subject_line(
        self,
        text: Text,
        line: str,
        palette: dict[str, Style],
    ) -> None:
        if line.startswith("  "):
            self._append_styled_subject_entry(text, line, palette)
            return

        header_match = _SUBJECT_HEADER_RE.match(line)
        if header_match is not None:
            self._append_styled_subject_header(text, header_match, palette)
            return

        text.append(line, style=palette["plain_subject"])

    def _append_styled_subject_header(
        self,
        text: Text,
        header_match: re.Match[str],
        palette: dict[str, Style],
    ) -> None:
        text.append(
            header_match.group("label"),
            style=palette["subject_header_label"],
        )
        rest = header_match.group("rest")
        count_match = _SUBJECT_COUNT_RE.match(rest)
        if count_match is None:
            text.append(rest, style=palette["plain_subject"])
            return
        text.append(count_match.group("prefix"))
        text.append(count_match.group("count"), style=palette["subject_count"])
        units = count_match.group("units")
        if units:
            text.append(units, style=palette["subject_units"])

    def _append_styled_subject_entry(
        self,
        text: Text,
        line: str,
        palette: dict[str, Style],
    ) -> None:
        entry_match = _SUBJECT_ENTRY_RE.match(line)
        text.append("› ", style=palette["subject_bullet"])
        if entry_match is None:
            text.append(line.strip(), style=palette["plain_subject"])
            return
        text.append(entry_match.group("name"), style=palette["subject_name"])
        handle = entry_match.group("handle")
        if handle is None:
            return
        text.append(" ", style=palette["subject_sigil"])
        text.append(entry_match.group("sigil"), style=palette["subject_sigil"])
        text.append(handle, style=palette["subject_handle"])

    def _resolve_palette(self) -> dict[str, Style]:
        theme = self._resolve_current_theme()
        palette: dict[str, Style] = {}
        for role, theme_attr in _PALETTE_THEME_ATTRS[self._kind].items():
            color = self._resolve_theme_color(theme, theme_attr)
            palette[role] = Style(
                color=color,
                bold=True if role in _PALETTE_BOLD_ROLES else None,
                dim=True if role in _PALETTE_DIM_ROLES else None,
            )
        return palette

    def _resolve_current_theme(self) -> object | None:
        try:
            return self.app.current_theme
        except NoActiveAppError:
            return None

    @staticmethod
    def _resolve_theme_color(theme: object | None, theme_attr: str) -> str:
        if theme is not None:
            color = getattr(theme, theme_attr, None)
            if color:
                return str(color)
        return _FALLBACK_THEME_COLORS[theme_attr]

    def _app_theme_changed(self) -> None:
        super_changed = getattr(super(), "_app_theme_changed", None)
        if callable(super_changed):
            super_changed()
        if not self.is_mounted:
            return
        dialog = self.query_one("#confirm-dialog-container", Container)
        self._apply_dialog_frame(dialog)
        self.query_one("#confirm-message", Static).update(self._message_text())
        self.query_one("#confirm-subject", Static).update(self._styled_subject_text())

    def _confirm_button_variant(self) -> ButtonVariant:
        return "error" if self._kind is ConfirmKind.DANGER else "primary"

    def _cancel_button_variant(self) -> ButtonVariant:
        return "primary" if self._kind is ConfirmKind.DANGER else "default"

    @staticmethod
    def _button_label(label: str, key: str) -> str:
        suffix = f"({key})"
        if suffix in label:
            return label
        return f"{label} {suffix}"


__all__ = ["ButtonVariant", "ConfirmDefault", "ConfirmDialog", "ConfirmKind"]
