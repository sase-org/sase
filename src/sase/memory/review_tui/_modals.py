"""Modal screens used by the memory review TUI."""

from __future__ import annotations

from collections.abc import Callable

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Label

from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea


class TextInputModal(ModalScreen[str | None]):
    """Small input modal used for filter, reject reason, and target edits."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(
        self,
        title: str,
        *,
        value: str = "",
        placeholder: str = "",
        submit_label: str = "Apply",
        validator: Callable[[str], str | None] | None = None,
    ) -> None:
        super().__init__()
        self._title = title
        self._value = value
        self._placeholder = placeholder
        self._submit_label = submit_label
        self._validator = validator

    def compose(self) -> ComposeResult:
        with Container(id="memory-review-input-modal"):
            yield Label(self._title, id="memory-review-input-title")
            yield SingleLineVimTextArea(
                value=self._value,
                placeholder=self._placeholder,
                id="memory-review-input",
            )
            error = Label("", id="memory-review-input-error")
            error.display = False
            yield error
            with Horizontal(id="memory-review-input-buttons"):
                yield Button(self._submit_label, id="apply", variant="primary")
                yield Button("Cancel", id="cancel", variant="default")

    def on_mount(self) -> None:
        field = self.query_one("#memory-review-input", SingleLineVimTextArea)
        field.focus()
        field.select_all()
        field._update_vim_mode_display()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "apply":
            self._submit()
            return
        self.dismiss(None)

    def on_single_line_vim_text_area_submitted(
        self, _event: SingleLineVimTextArea.Submitted
    ) -> None:
        self._submit()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _submit(self) -> None:
        value = self.query_one("#memory-review-input", SingleLineVimTextArea).text
        if self._validator is not None:
            error = self._validator(value)
            if error:
                self._show_error(error)
                return
        self.dismiss(value)

    def _show_error(self, message: str) -> None:
        error = self.query_one("#memory-review-input-error", Label)
        error.update(message)
        error.display = True
