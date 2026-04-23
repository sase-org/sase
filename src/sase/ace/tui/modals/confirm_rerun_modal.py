"""Confirm re-run modal for done background commands on the AXE tab."""

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Label


class ConfirmRerunModal(ModalScreen[bool | None]):
    """Modal for confirming re-run of a done background command.

    Three outcomes:
        - True: dismiss the original entry before re-running.
        - False: keep the original entry; re-run in a new slot.
        - None: cancel (no re-run, no dismiss).
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("q", "cancel", "Cancel"),
        ("y", "confirm_dismiss", "Yes"),
        ("n", "confirm_keep", "No"),
    ]

    def __init__(self, command_description: str) -> None:
        """Initialize the confirm re-run modal.

        Args:
            command_description: Description of the command being re-run.
        """
        super().__init__()
        self.command_description = command_description

    def compose(self) -> ComposeResult:
        """Compose the modal layout."""
        with Container():
            yield Label("Confirm Re-run", id="modal-title")
            yield Label(
                f"Dismiss original entry before re-running?\n\n{self.command_description}",
                id="confirm-message",
            )
            with Horizontal():
                yield Button("Yes (y)", id="confirm-btn", variant="error")
                yield Button("No (n)", id="keep-btn", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press."""
        if event.button.id == "confirm-btn":
            self.dismiss(True)
        elif event.button.id == "keep-btn":
            self.dismiss(False)
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        """Cancel the modal (no re-run)."""
        self.dismiss(None)

    def action_confirm_dismiss(self) -> None:
        """Dismiss original before re-running."""
        self.dismiss(True)

    def action_confirm_keep(self) -> None:
        """Keep original and re-run in a new slot."""
        self.dismiss(False)
