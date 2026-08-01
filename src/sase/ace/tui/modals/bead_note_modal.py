"""Append-only bead note modal."""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Label, TextArea


class BeadNoteModal(ModalScreen[str | None]):
    """Collect one non-empty note without exposing replacement semantics."""

    BINDINGS = [("escape", "cancel", "Cancel"), ("ctrl+s", "save", "Add note")]

    def __init__(self, bead_id: str) -> None:
        super().__init__()
        self.bead_id = bead_id

    def compose(self) -> ComposeResult:
        with Container(id="bead-note-container", classes="bead-modal-container small"):
            yield Label(f"Add note · {self.bead_id}", classes="bead-modal-title")
            yield TextArea("", id="bead-note-text")
            with Horizontal(classes="bead-modal-buttons"):
                yield Button("Add note  Ctrl+S", id="bead-note-save", variant="primary")
                yield Button("Cancel  Esc", id="bead-note-cancel")

    def on_mount(self) -> None:
        self.query_one("#bead-note-text", TextArea).focus()

    @on(Button.Pressed)
    def _on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "bead-note-save":
            self.action_save()
        else:
            self.action_cancel()

    def action_save(self) -> None:
        note = self.query_one("#bead-note-text", TextArea).text.strip()
        if not note:
            self.notify("Note cannot be empty", severity="error")
            return
        self.dismiss(note)

    def action_cancel(self) -> None:
        self.dismiss(None)


__all__ = ["BeadNoteModal"]
