"""Shared confirmation dialog foundation for the ace TUI."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, Horizontal
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
                self._subject_text(),
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
        button_id = "#confirm-btn" if self._default == "confirm" else "#cancel-btn"
        self.query_one(button_id, Button).focus()

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
        widget.update(self._subject_text())
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
        dialog.border_subtitle = "y confirm · n/esc cancel"

    def _build_border_title(self) -> Text:
        title = Text()
        style = "bold red" if self._kind is ConfirmKind.DANGER else "bold cyan"
        title.append(self._icon or _DEFAULT_ICONS[self._kind], style=style)
        title.append("  ")
        title.append(self._title, style="bold")
        return title

    def _message_text(self) -> Text:
        return Text(self._message)

    def _subject_text(self) -> Text:
        text = Text()
        if self._subject is not None:
            text.append(self._subject)
        return text

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
