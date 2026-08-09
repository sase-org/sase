"""Workflow context adapter for TUI handlers."""

from rich.console import Console


class WorkflowContext:
    """Minimal context for workflow handlers when running from TUI.

    This provides the `console` attribute that handlers expect from AceWorkflow.
    """

    def __init__(self) -> None:
        """Initialize the workflow context."""
        self.console = Console()

    def _reload_and_reposition(self, patches: list, patch: object) -> tuple[list, int]:
        """Stub for reload - TUI handles this separately."""
        # Import here to avoid circular imports
        from ..patch import find_all_patches

        return find_all_patches(), 0
