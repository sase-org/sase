"""Agent interrupt modal for the ace TUI."""

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Input, Label


class _InterruptInput(Input):
    """Custom Input with readline-style key bindings."""

    BINDINGS = [
        ("ctrl+f", "cursor_right", "Forward"),
        ("ctrl+b", "cursor_left", "Backward"),
        ("ctrl+a", "home", "Home"),
        ("ctrl+e", "end", "End"),
    ]


class AgentInterruptModal(ModalScreen[str | None]):
    """Modal for sending a message to a running agent."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, agent_name: str, cl_name: str | None = None) -> None:
        """Initialize the agent interrupt modal.

        Args:
            agent_name: Display name of the agent.
            cl_name: CL name of the agent, shown as subtitle.
        """
        super().__init__()
        self._agent_name = agent_name
        self._cl_name = cl_name

    def compose(self) -> ComposeResult:
        """Compose the modal layout."""
        subtitle = self._cl_name or ""
        with Container():
            yield Label("Send Message to Agent", id="modal-title")
            yield Label(
                f"{self._agent_name} {subtitle}".strip(),
                id="command-hint",
            )
            yield _InterruptInput(
                placeholder="Type a message to send to the agent...",
                id="interrupt-input",
            )

    def on_mount(self) -> None:
        """Focus the input on mount."""
        interrupt_input = self.query_one("#interrupt-input", _InterruptInput)
        interrupt_input.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in input."""
        message = event.value.strip()
        if message:
            self.dismiss(message)
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        """Cancel the modal."""
        self.dismiss(None)
