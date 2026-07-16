"""Edit a bead title and description from the Artifacts Plans pane."""

from __future__ import annotations

from dataclasses import dataclass

from textual import on
from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, TextArea


@dataclass(frozen=True)
class BeadEditResult:
    """Validated bead fields returned by :class:`BeadEditModal`."""

    title: str
    description: str


class BeadEditModal(ModalScreen[BeadEditResult | None]):
    """Small two-field editor that keeps bead writes outside the modal."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("ctrl+s", "save", "Save"),
    ]

    def __init__(self, bead_id: str, title: str, description: str) -> None:
        super().__init__()
        self._bead_id = bead_id
        self._title = title
        self._description = description

    def compose(self) -> ComposeResult:
        with Container(id="bead-edit-container"):
            yield Label(f"Edit bead {self._bead_id}", id="bead-edit-title")
            yield Label("Title", classes="bead-edit-label")
            yield Input(value=self._title, id="bead-edit-title-input")
            yield Label("Description", classes="bead-edit-label")
            yield TextArea(self._description, id="bead-edit-description-input")
            with Horizontal(id="bead-edit-buttons"):
                yield Button("Save  Ctrl+S", id="bead-edit-save", variant="primary")
                yield Button("Cancel  Esc", id="bead-edit-cancel")

    def on_mount(self) -> None:
        self.query_one("#bead-edit-title-input", Input).focus()

    @on(Input.Submitted, "#bead-edit-title-input")
    def _on_title_submitted(self, _event: Input.Submitted) -> None:
        self.query_one("#bead-edit-description-input", TextArea).focus()

    @on(Button.Pressed)
    def _on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "bead-edit-save":
            self.action_save()
        else:
            self.action_cancel()

    def action_save(self) -> None:
        title = self.query_one("#bead-edit-title-input", Input).value.strip()
        if not title:
            self.notify("Bead title cannot be empty", severity="error")
            self.query_one("#bead-edit-title-input", Input).focus()
            return
        description = self.query_one(
            "#bead-edit-description-input", TextArea
        ).text.strip()
        self.dismiss(BeadEditResult(title=title, description=description))

    def action_cancel(self) -> None:
        self.dismiss(None)


__all__ = ["BeadEditModal", "BeadEditResult"]
