"""Custom model input modal for entering a freeform provider/model string."""

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Label

from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea


class _ModelInput(SingleLineVimTextArea):
    """Single-line vim editor for custom model identifiers."""


class CustomModelInputModal(ModalScreen[str | None]):
    """Modal for entering a custom provider/model string.

    Args:
        title: Heading shown above the input.
        hint: Format hint shown below the heading.
        placeholder: Input placeholder text.
        initial: Initial input text, e.g. an existing alias value to edit in
            place. Empty by default, which preserves the placeholder.
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(
        self,
        *,
        title: str = "Enter Custom Model",
        hint: str = "Format: provider/model  or  model",
        placeholder: str = "e.g. opencode/anthropic/claude-sonnet-4-5",
        initial: str = "",
    ) -> None:
        super().__init__()
        self._title = title
        self._hint = hint
        self._placeholder = placeholder
        self._initial = initial

    def compose(self) -> ComposeResult:
        with Container(id="custom-model-container"):
            yield Label(
                f"[bold cyan]{self._title}[/bold cyan]",
                id="custom-model-title",
            )
            yield Label(
                self._hint,
                id="custom-model-hint",
            )
            yield _ModelInput(
                self._initial,
                placeholder=self._placeholder,
                id="custom-model-input",
            )
            yield Label(
                "[green]enter[/green]=Confirm  [dim]esc esc[/dim]=Cancel",
                id="custom-model-footer",
            )

    def on_mount(self) -> None:
        input_widget = self.query_one("#custom-model-input", _ModelInput)
        input_widget.focus()
        if self._initial:
            input_widget.cursor_location = input_widget.document.end
        input_widget._update_vim_mode_display()

    def on_single_line_vim_text_area_submitted(
        self, event: SingleLineVimTextArea.Submitted
    ) -> None:
        value = event.value.strip()
        if value:
            self.dismiss(value)
        else:
            self.notify("Please enter a model name", severity="error")

    def action_cancel(self) -> None:
        self.dismiss(None)
