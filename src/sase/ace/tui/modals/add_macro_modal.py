"""Add macro modal for creating new macro files."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Label

from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea


class _AddMacroInput(SingleLineVimTextArea):
    """Single-line vim editor for new macro paths."""


class AddMacroModal(ModalScreen[str | None]):
    """Modal for entering path for a new macro file."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, default_path: str = "sase/macros/") -> None:
        super().__init__()
        self._default_path = default_path

    def compose(self) -> ComposeResult:
        with Container(id="add-macro-container"):
            yield Label("Add New Macro", id="modal-title")
            yield Label(
                "Enter path for new macro (.md file):",
                id="add-macro-hint",
            )
            yield _AddMacroInput(
                value=self._default_path,
                placeholder=f"{self._default_path}my_prompt.md",
                id="add-macro-input",
            )

    def on_mount(self) -> None:
        inp = self.query_one("#add-macro-input", _AddMacroInput)
        inp.focus()
        inp.cursor_position = len(inp.text)
        inp._update_vim_mode_display()

    def on_single_line_vim_text_area_submitted(
        self, event: SingleLineVimTextArea.Submitted
    ) -> None:
        value = event.value.strip()
        if not value:
            self.dismiss(None)
            return
        if not value.endswith(".md"):
            value += ".md"
        self.dismiss(value)

    def action_cancel(self) -> None:
        self.dismiss(None)
