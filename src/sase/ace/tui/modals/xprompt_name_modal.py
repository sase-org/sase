"""XPrompt name input modal for saving a draft as a new xprompt."""

from __future__ import annotations

import re
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Label, TextArea

from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea


class _NameInput(SingleLineVimTextArea):
    """Single-line vim editor for xprompt names."""


class XPromptNameModal(ModalScreen[str | None]):
    """Modal for entering an xprompt name."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(
        self,
        *,
        location_label: str,
        location_path: str,
        existing_names: set[str] | None = None,
    ) -> None:
        super().__init__()
        self._location_label = location_label
        self._location_path = location_path
        self._existing_names = existing_names or set()

    def compose(self) -> ComposeResult:
        display_path = self._display_path(self._location_path)
        with Container(id="xprompt-name-container"):
            yield Label("Name XPrompt", id="xprompt-name-title")
            yield Label(
                f"{self._location_label}: {display_path}",
                id="xprompt-name-location",
            )
            yield Label("Enter xprompt name:", id="xprompt-name-hint")
            yield _NameInput(placeholder="my_prompt", id="xprompt-name-input")
            yield Label("", id="xprompt-name-note")
            yield Label("", id="xprompt-name-error")

    def on_mount(self) -> None:
        editor = self.query_one("#xprompt-name-input", _NameInput)
        editor.focus()
        editor._update_vim_mode_display()

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id == "xprompt-name-input":
            self._update_feedback(event.text_area.text)

    def on_single_line_vim_text_area_submitted(
        self, event: SingleLineVimTextArea.Submitted
    ) -> None:
        value = event.value.strip()
        error = self._validation_error(value)
        if error is not None:
            self.query_one("#xprompt-name-error", Label).update(error)
            return
        self.dismiss(value)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _update_feedback(self, raw_value: str) -> None:
        value = raw_value.strip()
        error_label = self.query_one("#xprompt-name-error", Label)
        note_label = self.query_one("#xprompt-name-note", Label)

        error = self._validation_error(value, allow_empty=True)
        error_label.update(error or "")
        if value and self._name_exists(value):
            note_label.update("Already exists - saving will overwrite it.")
        else:
            note_label.update("")

    def _validation_error(
        self,
        value: str,
        *,
        allow_empty: bool = False,
    ) -> str | None:
        if not value:
            return None if allow_empty else "Name is required"
        if re.search(r"\s", value):
            return "Name cannot contain spaces"
        return None

    def _name_exists(self, value: str) -> bool:
        filename_stem = value.replace("/", "_")
        return value in self._existing_names or filename_stem in self._existing_names

    @staticmethod
    def _display_path(path: str) -> str:
        home = str(Path.home())
        if path.startswith(home + "/"):
            return "~" + path[len(home) :]
        return path


__all__ = ["XPromptNameModal"]
