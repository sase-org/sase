"""Custom model input modal for entering a freeform provider/model string."""

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Input, Label


class _ModelInput(Input):
    """Custom Input with readline-style key bindings."""

    BINDINGS = [
        ("ctrl+f", "cursor_right", "Forward"),
        ("ctrl+b", "cursor_left", "Backward"),
        ("ctrl+a", "home", "Home"),
        ("ctrl+e", "end", "End"),
    ]


class CustomModelInputModal(ModalScreen[str | None]):
    """Modal for entering a custom provider/model string.

    Args:
        title: Heading shown above the input.
        hint: Format hint shown below the heading.
        placeholder: Input placeholder text.
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
    ) -> None:
        super().__init__()
        self._title = title
        self._hint = hint
        self._placeholder = placeholder

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
                placeholder=self._placeholder,
                id="custom-model-input",
            )
            yield Label(
                "[green]enter[/green]=Confirm  [dim]esc[/dim]=Cancel",
                id="custom-model-footer",
            )

    def on_mount(self) -> None:
        self.query_one("#custom-model-input", _ModelInput).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        if value:
            self.dismiss(value)
        else:
            self.notify("Please enter a model name", severity="error")

    def action_cancel(self) -> None:
        self.dismiss(None)
