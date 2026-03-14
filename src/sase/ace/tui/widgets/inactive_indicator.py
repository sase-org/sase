"""Idle indicator widget for the ace TUI."""

from typing import Any

from rich.text import Text
from textual.widgets import Static


class InactiveIndicator(Static):
    """Shows an IDLE badge in the top-bar when the user is inactive."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(self._build_content(False, False), **kwargs)
        self._idle = False
        self._pinned = False

    def set_idle(self, idle: bool, *, pinned: bool = False) -> None:
        """Update the idle state.

        Args:
            idle: Whether the user is considered idle.
            pinned: Whether idle is pinned (only clearable by explicit toggle).
        """
        if self._idle != idle or self._pinned != pinned:
            self._idle = idle
            self._pinned = pinned
            if self.is_mounted:
                self.update(self._build_content(idle, pinned))

    @staticmethod
    def _build_content(idle: bool, pinned: bool) -> Text:
        """Build the indicator text."""
        if idle:
            if pinned:
                return Text(" \u25a0 IDLE ", style="bold #1a1a1a on #CC3333")
            return Text(" IDLE ", style="bold #1a1a1a on #FF8C00")
        return Text("")
