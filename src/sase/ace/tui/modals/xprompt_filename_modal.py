"""XPrompt filename input modal for entering a filename when creating xprompts."""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Label

from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea


class _FilenameInput(SingleLineVimTextArea):
    """Single-line vim editor for xprompt filenames."""


class XPromptFilenameModal(ModalScreen[str | None]):
    """Modal for entering a filename for a new xprompt.

    Shows the selected directory and validates that the filename
    ends with ``.md`` or ``.yml``.  Dismisses with the full path
    (directory + filename) or ``None`` on cancel.
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, directory: str) -> None:
        super().__init__()
        self._directory = directory

    def compose(self) -> ComposeResult:
        home = str(Path.home())
        display_dir = self._directory.replace(home, "~")
        if not display_dir.endswith("/"):
            display_dir += "/"
        with Container(id="filename-container"):
            yield Label("New XPrompt", id="modal-title")
            yield Label(
                f"Directory: {display_dir}",
                id="filename-dir-label",
            )
            yield Label(
                "Enter filename (.md or .yml):",
                id="filename-hint",
            )
            yield _FilenameInput(
                placeholder="my_prompt.md",
                id="filename-input",
            )
            yield Label("", id="filename-error")

    def on_mount(self) -> None:
        inp = self.query_one("#filename-input", _FilenameInput)
        inp.focus()
        inp._update_vim_mode_display()

    def on_single_line_vim_text_area_submitted(
        self, event: SingleLineVimTextArea.Submitted
    ) -> None:
        value = event.value.strip()
        if not value:
            self.dismiss(None)
            return

        if not value.endswith(".md") and not value.endswith(".yml"):
            error_label = self.query_one("#filename-error", Label)
            error_label.update("Filename must end with .md or .yml")
            return

        directory = self._directory
        if not directory.endswith("/"):
            directory += "/"
        full_path = directory + value
        self.dismiss(full_path)

    def action_cancel(self) -> None:
        self.dismiss(None)
