"""Unwait modal for the ace TUI."""

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Input, Label


class _UnwaitInput(Input):
    """Custom Input with readline-style key bindings."""

    BINDINGS = [
        ("ctrl+f", "cursor_right", "Forward"),
        ("ctrl+b", "cursor_left", "Backward"),
        ("ctrl+a", "home", "Home"),
        ("ctrl+e", "end", "End"),
    ]


class UnwaitModal(ModalScreen[str | None]):
    """Modal for changing which agent a WAITING agent waits for.

    Returns:
        str (non-empty) - agent name to wait for
        "" (empty string) - unwait now (run immediately)
        None - cancelled (escape)
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, current_waiting_for: list[str] | None = None) -> None:
        """Initialize the unwait modal.

        Args:
            current_waiting_for: Current list of agent names being waited on.
        """
        super().__init__()
        self._current_waiting_for = current_waiting_for or []

    def compose(self) -> ComposeResult:
        """Compose the modal layout."""
        prefill = ", ".join(self._current_waiting_for)
        with Container():
            yield Label("Unwait Agent", id="modal-title")
            yield Label(
                "Enter agent name to wait for, or press Enter to run now.",
                id="command-hint",
            )
            yield _UnwaitInput(
                value=prefill,
                placeholder="leave empty to run now",
                id="name-input",
            )

    def on_mount(self) -> None:
        """Focus the input on mount."""
        name_input = self.query_one("#name-input", _UnwaitInput)
        name_input.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in input."""
        self.dismiss(event.value.strip())

    def action_cancel(self) -> None:
        """Cancel the modal."""
        self.dismiss(None)
