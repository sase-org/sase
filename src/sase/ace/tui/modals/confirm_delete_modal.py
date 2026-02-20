"""Confirm delete modal for the ace TUI."""

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Label


class ConfirmDeleteModal(ModalScreen[bool]):
    """Modal for confirming project file deletion."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("q", "cancel", "Cancel"),
        ("y", "confirm", "Yes"),
        ("n", "cancel", "No"),
    ]

    def __init__(self, project_name: str) -> None:
        """Initialize the confirm delete modal.

        Args:
            project_name: Name of the project to delete
        """
        super().__init__()
        self.project_name = project_name

    def compose(self) -> ComposeResult:
        """Compose the modal layout."""
        with Container():
            yield Label("Confirm Delete Project", id="modal-title")
            yield Label(
                f"Delete project file for '{self.project_name}'? This cannot be undone.",
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
