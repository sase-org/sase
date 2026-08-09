"""Rename Patch modal for the ace TUI."""

from sase.ace.patch.project_spec_path import project_spec_basename
from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Label

from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea


class _RenameInput(SingleLineVimTextArea):
    """Single-line vim editor for Patch names."""


class RenamePatchModal(ModalScreen[str | None]):
    """Modal for renaming a Patch.

    Returns the new name if valid, None if cancelled.
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(
        self,
        current_name: str,
        project_file_path: str,
        status: str,
    ) -> None:
        """Initialize the rename modal.

        Args:
            current_name: The current Patch name.
            project_file_path: Path to the project spec file.
            status: The Patch's current status (for suffix validation).
        """
        super().__init__()
        self._current_name = current_name
        self._project_file_path = project_file_path
        self._status = status
        self._project_name = project_spec_basename(project_file_path)

    def compose(self) -> ComposeResult:
        """Compose the modal layout."""
        with Container():
            yield Label("Rename Patch", id="modal-title")
            yield Label(
                f"Current: {self._current_name}",
                id="modal-instructions",
            )
            yield _RenameInput(
                value=self._current_name, placeholder="new_name", id="rename-input"
            )
            with Horizontal(id="button-row"):
                yield Button("Rename", id="apply", variant="primary")
                yield Button("Cancel", id="cancel", variant="default")

    def on_mount(self) -> None:
        """Focus the input and select all text on mount."""
        rename_input = self.query_one("#rename-input", _RenameInput)
        rename_input.focus()
        rename_input.select_all()
        rename_input._update_vim_mode_display()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "apply":
            self._submit_value()
        else:
            self.dismiss(None)

    def on_single_line_vim_text_area_submitted(
        self, _event: SingleLineVimTextArea.Submitted
    ) -> None:
        """Handle Enter key in input."""
        self._submit_value()

    def _submit_value(self) -> None:
        """Validate and submit the new name."""
        from sase.workflows.commit.patch_queries import patch_exists
        from sase.core.patch import has_suffix

        rename_input = self.query_one("#rename-input", _RenameInput)
        new_name = rename_input.text.strip()

        # Check empty
        if not new_name:
            self.notify("Name cannot be empty", severity="error")
            return

        # Check unchanged
        if new_name == self._current_name:
            self.dismiss(None)
            return

        # Check exact duplicate
        if patch_exists(self._project_name, new_name):
            self.notify(
                f"Name '{new_name}' already exists in project",
                severity="error",
            )
            return

        # Check WIP/Draft/Reverted suffix requirements
        if self._status in ("WIP", "Draft", "Reverted") and has_suffix(
            self._current_name
        ):
            if not has_suffix(new_name):
                self.notify(
                    "WIP/Draft/Reverted Patches with __<N> suffix must keep suffix",
                    severity="error",
                )
                return

        self.dismiss(new_name)

    def action_cancel(self) -> None:
        """Cancel the modal."""
        self.dismiss(None)
