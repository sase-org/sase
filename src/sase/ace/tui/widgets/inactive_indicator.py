"""Idle indicator widget for the ace TUI."""

from typing import Any

from rich.text import Text
from textual.widgets import Static


class InactiveIndicator(Static):
    """Shows an IDLE badge in the top-bar when the user is inactive."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(self._build_content(False), **kwargs)
        self._idle = False

    def set_idle(self, idle: bool) -> None:
        """Update the idle state.

        Args:
            idle: Whether the user is considered idle.
        """
        if self._idle != idle:
            self._idle = idle
            if self.is_mounted:
                self.update(self._build_content(idle))

    @staticmethod
    def _build_content(idle: bool) -> Text:
        """Build the indicator text."""
        if idle:
            return Text(" IDLE ", style="bold #1a1a1a on #FF8C00")
        return Text("")
