"""Add xprompt modal for creating new xprompt files."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Input, Label


class _AddXPromptInput(Input):
    """Custom Input with readline-style key bindings."""

    BINDINGS = [
        ("ctrl+f", "cursor_right", "Forward"),
        ("ctrl+b", "cursor_left", "Backward"),
    ]


class AddXPromptModal(ModalScreen[str | None]):
    """Modal for entering path for a new xprompt file."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def compose(self) -> ComposeResult:
        with Container(id="add-xprompt-container"):
            yield Label("Add New XPrompt", id="modal-title")
            yield Label(
                "Enter path for new xprompt (.md file):",
                id="add-xprompt-hint",
            )
            yield _AddXPromptInput(
                value=".xprompts/",
                placeholder=".xprompts/my_prompt.md",
                id="add-xprompt-input",
            )

    def on_mount(self) -> None:
        inp = self.query_one("#add-xprompt-input", _AddXPromptInput)
        inp.focus()
        inp.cursor_position = len(inp.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        if not value:
            self.dismiss(None)
            return
        if not value.endswith(".md"):
            value += ".md"
        self.dismiss(value)

    def action_cancel(self) -> None:
        self.dismiss(None)
