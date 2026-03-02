"""Agent info panel widget for the ace TUI."""

from typing import Any

from rich.text import Text
from textual.widgets import Static


class AgentInfoPanel(Static):
    """Top bar showing agent count and auto-refresh countdown."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the info panel."""
        super().__init__(**kwargs)
        self._position = 0
        self._total = 0
        self._countdown = 0
        self._interval = 0
        self._view_mode: str = ""
        self._search_query: str = ""

    def update_position(self, position: int, total: int) -> None:
        """Update the position display.

        Args:
            position: Current position (1-based for display).
            total: Total number of agents.
        """
        self._position = position
        self._total = total
        self._update_display()

    def update_countdown(self, countdown: int, interval: int) -> None:
        """Update the countdown display.

        Args:
            countdown: Seconds remaining until auto-refresh.
            interval: Total refresh interval in seconds.
        """
        self._countdown = countdown
        self._interval = interval
        self._update_display()

    def update_view_mode(self, mode: str) -> None:
        """Update the panel view mode indicator.

        Args:
            mode: The current view mode label (``"file"``, ``"thinking"``,
                or ``"collapsed"``). Empty string hides the indicator.
        """
        self._view_mode = mode
        self._update_display()

    def update_search_query(self, query: str) -> None:
        """Update the search query filter display.

        Args:
            query: The current search query string. Empty string hides the filter.
        """
        self._search_query = query
        self._update_display()

    _VIEW_MODE_STYLES: dict[str, str] = {
        "file": "bold green",
        "thinking": "bold #af87d7",
        "collapsed": "dim italic",
    }

    def _update_display(self) -> None:
        """Refresh the displayed text."""
        text = Text()
        text.append("Agents: ", style="bold #87D7FF")
        text.append(f"{self._position}/{self._total}", style="#00D7AF")
        if self._search_query:
            text.append("   ")
            text.append("filter: ", style="dim italic")
            text.append(self._search_query, style="bold #FFD700")
        if self._view_mode:
            text.append("   ")
            text.append("[", style="dim")
            text.append("view: ", style="dim")
            style = self._VIEW_MODE_STYLES.get(self._view_mode, "dim")
            text.append(self._view_mode, style=style)
            text.append("]", style="dim")
        if self._interval > 0:
            text.append("   ")
            text.append("(auto-refresh in ", style="dim")
            text.append(f"{self._countdown}s", style="bold #FFD700")
            text.append(")", style="dim")
        self.update(text)
