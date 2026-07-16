"""Add xprompt modal for creating new xprompt files."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Label

from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea


class _AddXPromptInput(SingleLineVimTextArea):
    """Single-line vim editor for new xprompt paths."""


class AddXPromptModal(ModalScreen[str | None]):
    """Modal for entering path for a new xprompt file."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, default_path: str = "sase/xprompts/") -> None:
        super().__init__()
        self._default_path = default_path

    def compose(self) -> ComposeResult:
        with Container(id="add-xprompt-container"):
            yield Label("Add New XPrompt", id="modal-title")
            yield Label(
                "Enter path for new xprompt (.md file):",
                id="add-xprompt-hint",
            )
            yield _AddXPromptInput(
                value=self._default_path,
                placeholder=f"{self._default_path}my_prompt.md",
                id="add-xprompt-input",
            )

    def on_mount(self) -> None:
        inp = self.query_one("#add-xprompt-input", _AddXPromptInput)
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
