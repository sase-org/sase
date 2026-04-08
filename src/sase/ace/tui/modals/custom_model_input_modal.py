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
    """Modal for entering a custom provider/model string."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def compose(self) -> ComposeResult:
        with Container(id="custom-model-container"):
            yield Label(
                "[bold cyan]Enter Custom Model[/bold cyan]",
                id="custom-model-title",
            )
            yield Label(
                "Format: provider/model  or  model",
                id="custom-model-hint",
            )
            yield _ModelInput(
                placeholder="e.g. codex/o3-preview",
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
