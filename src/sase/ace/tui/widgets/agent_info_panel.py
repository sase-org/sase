"""Agent info panel widget for the ace TUI."""

from typing import Any

from rich.text import Text
from textual.widgets import Static

from ..keymaps import KeymapRegistry, key_display_name, load_keymap_registry


class AgentInfoPanel(Static):
    """Top bar showing agent metrics and auto-refresh countdown."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the info panel."""
        super().__init__(**kwargs)
        self._position = 0
        self._total = 0
        self._unread_count = 0
        self._asking_count = 0
        self._running_count = 0
        self._waiting_count = 0
        self._failed_count = 0
        self._read_count = 0
        self._visible_agent_count = 0
        self._countdown = 0
        self._interval = 0
        self._view_mode: str = ""
        self._grouping_mode: str = ""
        self._search_query: str = ""
        self._loading: bool = False
        self._registry = load_keymap_registry({})

    def set_keymap_registry(self, registry: KeymapRegistry) -> None:
        """Override the keymap registry and refresh display."""
        self._registry = registry
        self._update_display()

    def set_loading(self, loading: bool) -> None:
        """Show or hide the startup-loading ellipsis.

        While True, the count line renders ``Agents: …`` (dim italic) to
        signal that agent data has not yet loaded, rather than falsely
        claiming the list is empty.
        """
        if self._loading != loading:
            self._loading = loading
            self._update_display()

    def update_position(self, position: int, total: int) -> None:
        """Store the current position for compatibility with existing callers.

        Args:
            position: Current position (1-based for display).
            total: Total number of agents.
        """
        self._position = position
        self._total = total
        self._update_display()

    def update_agent_counts(
        self,
        unread: int,
        asking: int,
        running: int,
        waiting: int,
        failed: int,
        read: int,
        total: int,
    ) -> None:
        """Update the visible top-level agent metric strip.

        Args:
            unread: Visible unread completed agent count.
            asking: Visible agent count paused for human input.
            running: Visible active agent count, excluding waiting agents.
            waiting: Visible waiting agent count.
            failed: Visible failed agent count.
            read: Visible completed agent count that has already been read.
            total: Visible top-level agent count.
        """
        self._unread_count = unread
        self._asking_count = asking
        self._running_count = running
        self._waiting_count = waiting
        self._failed_count = failed
        self._read_count = read
        self._visible_agent_count = total
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

    def update_grouping_mode(self, label: str) -> None:
        """Update the active grouping-strategy label.

        Args:
            label: Human-readable label for the active grouping strategy
                (``"by project"``, ``"by date"``, ``"by status"``).  The
                badge is always rendered, so an empty string is treated
                as ``"by project"``.
        """
        self._grouping_mode = label
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

    _GROUPING_MODE_STYLES: dict[str, str] = {
        "by project": "bold #5FAFFF",
        "by date": "bold #87D7FF",
        "by status": "bold #FFAF87",
    }

    _COUNT_STYLES: dict[str, str] = {
        "total": "bold #5FAFFF",
        "asking": "bold #FFAF00",
        "running": "bold #00D7AF",
        "waiting": "bold #AF87FF",
        "failed": "bold #FF5F5F",
        "unread": "bold #FFAF5F",
        "read": "bold #BCBCBC",
    }

    def _metric_counts(self) -> list[tuple[str, int]]:
        return [
            ("asking", self._asking_count),
            ("running", self._running_count),
            ("waiting", self._waiting_count),
            ("failed", self._failed_count),
            ("unread", self._unread_count),
            ("read", self._read_count),
        ]

    def _append_metric_strip(self, text: Text) -> None:
        metrics = [(label, count) for label, count in self._metric_counts() if count]
        if not metrics:
            return
        text.append(" [", style="dim")
        for index, (label, count) in enumerate(metrics):
            if index:
                text.append(" · ", style="dim")
            text.append(f"{count}", style=self._COUNT_STYLES[label])
            text.append(f" {label}", style="dim")
        text.append("]", style="dim")

    def _update_display(self) -> None:
        """Refresh the displayed text."""
        text = Text()
        if self._loading:
            text.append("Agents", style="bold #87D7FF")
            text.append(": ", style="bold #87D7FF")
            text.append("…", style="dim italic")
            self.update(text)
            return
        text.append(f"{self._visible_agent_count}", style=self._COUNT_STYLES["total"])
        text.append(" Agents", style="bold #87D7FF")
        self._append_metric_strip(text)
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
        grouping_label = self._grouping_mode or "by project"
        text.append("   ")
        text.append("[", style="dim")
        text.append("group: ", style="dim")
        text.append(
            grouping_label,
            style=self._GROUPING_MODE_STYLES.get(grouping_label, "dim"),
        )
        key = key_display_name(self._registry.app.cycle_grouping_mode)
        text.append(f" ({key})", style="dim")
        text.append("]", style="dim")
        if self._interval > 0:
            text.append("   ")
            text.append("(auto-refresh in ", style="dim")
            text.append(f"{self._countdown}s", style="bold #FFD700")
            text.append(")", style="dim")
        self.update(text)
