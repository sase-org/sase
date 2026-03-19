"""Background task indicator widget for the ace TUI."""

from typing import Any

from rich.text import Text
from textual.widgets import Static


class TaskIndicator(Static):
    """Shows the count of running background tasks in the top-bar.

    Visible only when at least one task is running; hides itself
    otherwise to avoid clutter.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(self._build_content(0), **kwargs)
        self._count = 0

    def set_count(self, count: int) -> None:
        """Update the displayed running task count.

        Args:
            count: Number of currently running background tasks.
        """
        if self._count != count:
            self._count = count
            if self.is_mounted:
                self.update(self._build_content(count))

    @staticmethod
    def _build_content(count: int) -> Text:
        """Build the indicator text."""
        if count > 0:
            return Text(f" \u2699 {count} ", style="bold #1a1a1a on #48CAE4")
        return Text("")
