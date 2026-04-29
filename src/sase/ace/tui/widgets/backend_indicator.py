"""Core backend indicator widget for the ace TUI."""

from typing import Any

from rich.text import Text
from textual.widgets import Static

from sase.core.backend import BackendDisplay, get_backend_display


class BackendIndicator(Static):
    """Shows the selected sase.core backend mode in the top-bar."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(self._build_content(get_backend_display()), **kwargs)

    @staticmethod
    def _build_content(display: BackendDisplay | None = None) -> Text:
        """Build the indicator text."""
        display = display or get_backend_display()
        return Text(f" {display.label} ", style=display.style)
