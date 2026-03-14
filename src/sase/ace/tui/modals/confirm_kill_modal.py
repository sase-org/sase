"""Confirm kill / dismiss-all modals for the ace TUI."""

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Label


class ConfirmDismissAllModal(ModalScreen[bool]):
    """Modal for confirming bulk dismissal of all completed agents."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("q", "cancel", "Cancel"),
        ("y", "confirm", "Yes"),
        ("n", "cancel", "No"),
    ]

    def __init__(self, count: int) -> None:
        """Initialize the confirm dismiss-all modal.

        Args:
            count: Number of agents that will be dismissed.
        """
        super().__init__()
        self.count = count

    def compose(self) -> ComposeResult:
        """Compose the modal layout."""
        s = "s" if self.count != 1 else ""
        with Container():
            yield Label("Dismiss All Agents", id="modal-title")
            yield Label(
                f"Dismiss {self.count} completed agent{s}?",
                id="confirm-message",
            )
            with Horizontal():
                yield Button("Yes (y)", id="confirm-btn", variant="error")
                yield Button("No (n)", id="cancel-btn", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press."""
        if event.button.id == "confirm-btn":
            self.dismiss(True)
        else:
            self.dismiss(False)

    def action_cancel(self) -> None:
        """Cancel the modal."""
        self.dismiss(False)

    def action_confirm(self) -> None:
        """Confirm the action."""
        self.dismiss(True)


class ConfirmKillModal(ModalScreen[bool]):
    """Modal for confirming agent termination."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("q", "cancel", "Cancel"),
        ("y", "confirm", "Yes"),
        ("n", "cancel", "No"),
    ]

    def __init__(self, agent_description: str) -> None:
        """Initialize the confirm kill modal.

        Args:
            agent_description: Description of the agent to kill
        """
        super().__init__()
        self.agent_description = agent_description

    def compose(self) -> ComposeResult:
        """Compose the modal layout."""
        with Container():
            yield Label("Confirm Kill Agent", id="modal-title")
            yield Label(
                f"Are you sure you want to kill this agent?\n\n{self.agent_description}",
                id="confirm-message",
            )
            with Horizontal():
                yield Button("Yes (y)", id="confirm-btn", variant="error")
                yield Button("No (n)", id="cancel-btn", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press."""
        if event.button.id == "confirm-btn":
            self.dismiss(True)
        else:
            self.dismiss(False)

    def action_cancel(self) -> None:
        """Cancel the modal."""
        self.dismiss(False)

    def action_confirm(self) -> None:
        """Confirm the action."""
        self.dismiss(True)
