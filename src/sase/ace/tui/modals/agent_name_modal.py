"""Agent name modal for the ace TUI."""

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Input, Label


class _NameInput(Input):
    """Custom Input with readline-style key bindings."""

    BINDINGS = [
        ("ctrl+f", "cursor_right", "Forward"),
        ("ctrl+b", "cursor_left", "Backward"),
        ("ctrl+a", "home", "Home"),
        ("ctrl+e", "end", "End"),
    ]


class AgentNameModal(ModalScreen[str | None]):
    """Modal for entering or editing an agent name."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, current_name: str | None = None) -> None:
        """Initialize the agent name modal.

        Args:
            current_name: Current agent name to pre-fill, or None.
        """
        super().__init__()
        self._current_name = current_name

    def compose(self) -> ComposeResult:
        """Compose the modal layout."""
        with Container():
            yield Label("Name Agent", id="modal-title")
            yield Label(
                "Enter a name for this agent. Press Enter to save.",
                id="command-hint",
            )
            yield _NameInput(
                value=self._current_name or "",
                placeholder="e.g., builder",
                id="name-input",
            )

    def on_mount(self) -> None:
        """Focus the input on mount."""
        name_input = self.query_one("#name-input", _NameInput)
        name_input.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in input."""
        name = event.value.strip()
        if name:
            self.dismiss(name)
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        """Cancel the modal."""
        self.dismiss(None)
