"""Confirm delete modal for the ace TUI."""

from __future__ import annotations

from .confirm_dialog import ConfirmDialog, ConfirmKind


class ConfirmDeleteModal(ConfirmDialog):
    """Modal for confirming project file deletion."""

    def __init__(self, project_name: str) -> None:
        """Initialize the confirm delete modal.

        Args:
            project_name: Name of the project to delete.
        """
        self.project_name = project_name
        super().__init__(
            "Delete Project",
            "Delete this project file? This cannot be undone.",
            subject=project_name,
            kind=ConfirmKind.DANGER,
            confirm_label="Delete",
            cancel_label="Keep",
            default="cancel",
        )


__all__ = ["ConfirmDeleteModal"]
