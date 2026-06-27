"""Confirm re-run modal for done background commands on the AXE tab."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Static


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
        self.add_class("confirm-dialog")
        self.command_description = command_description

    def compose(self) -> ComposeResult:
        """Compose the modal layout."""
        dialog = Container(
            id="rerun-confirm-container",
            classes="confirm-dialog-panel confirm-dialog--neutral",
        )
        title = Text()
        title.append("↻", style="bold cyan")
        title.append("  Re-run Command", style="bold")
        dialog.border_title = title
        dialog.border_subtitle = "y dismiss original · n keep original · esc cancel"
        with dialog:
            yield Static(
                "Dismiss the original entry before re-running?",
                id="confirm-message",
                classes="confirm-dialog-message",
            )
            yield Static(
                Text(self.command_description),
                id="confirm-subject",
                classes="confirm-dialog-subject",
            )
            with Horizontal(id="confirm-buttons", classes="confirm-dialog-buttons"):
                yield Button(
                    "Dismiss original (y)",
                    id="confirm-btn",
                    variant="primary",
                )
                yield Button("Keep original (n)", id="keep-btn")

    def on_mount(self) -> None:
        """Default focus to the less destructive re-run mode."""
        self.query_one("#keep-btn", Button).focus()

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


__all__ = ["ConfirmRerunModal"]
