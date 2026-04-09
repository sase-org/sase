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

    def __init__(self, agent_description: str) -> None:
        """Initialize the confirm dismiss-all modal.

        Args:
            agent_description: Description of the agents to dismiss.
        """
        super().__init__()
        self.agent_description = agent_description

    def compose(self) -> ComposeResult:
        """Compose the modal layout."""
        with Container():
            yield Label("Confirm Dismiss All", id="modal-title")
            yield Label(
                f"Are you sure you want to dismiss these agents?\n\n{self.agent_description}",
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


class ConfirmKillAllModal(ModalScreen[bool]):
    """Modal for confirming kill & dismiss of all agents (double-confirmation).

    First ``y`` press transitions the modal to a "FINAL CONFIRMATION" state
    with a red border and updated message.  Second ``y`` performs the action.
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("q", "cancel", "Cancel"),
        ("y", "confirm", "Yes"),
        ("n", "cancel", "No"),
    ]

    def __init__(self, agent_description: str) -> None:
        super().__init__()
        self.agent_description = agent_description
        self._confirmed_once = False

    def compose(self) -> ComposeResult:
        with Container(id="kill-all-container"):
            yield Label("Confirm Kill & Dismiss All", id="modal-title")
            yield Label(
                f"Are you sure you want to kill & dismiss these agents?\n\n{self.agent_description}",
                id="confirm-message",
            )
            with Horizontal():
                yield Button("Yes (y)", id="confirm-btn", variant="error")
                yield Button("No (n)", id="cancel-btn", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm-btn":
            self.action_confirm()
        else:
            self.dismiss(False)

    def action_cancel(self) -> None:
        self.dismiss(False)

    def action_confirm(self) -> None:
        if not self._confirmed_once:
            self._confirmed_once = True
            container = self.query_one("#kill-all-container", Container)
            container.add_class("confirmed-once")
            self.query_one("#modal-title", Label).update("\u26a0 FINAL CONFIRMATION")
            self.query_one("#confirm-message", Label).update(
                "This will KILL running agents and dismiss completed agents.\n\n"
                "This action is irreversible. Press y again to confirm."
            )
            self.query_one("#confirm-btn", Button).label = "Confirm (y)"
        else:
            self.dismiss(True)
