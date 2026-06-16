"""Persistent stashed-prompts indicator widget for the ace TUI."""

from typing import Any

from rich.text import Text
from textual.widgets import Static


class StashedPromptsIndicator(Static):
    """Top-bar badge showing how many prompt drafts are stashed.

    Mirrors :class:`TaskIndicator`: visible only when at least one prompt is
    stashed, hidden (empty) otherwise so it never adds clutter when the stash
    is empty.  The snowflake glyph + violet accent reads as "set aside, frozen
    for later" (git-stash for prompts) and is visually distinct from the
    task (cyan) and notification (orange/gold) badges.  Hovering shows the
    exact count via tooltip.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(self._build_content(0), **kwargs)
        self._count = 0
        self.tooltip = self._build_tooltip(0)

    def set_count(self, count: int) -> None:
        """Update the displayed stashed-prompt count.

        Args:
            count: Number of restorable stashed prompts on disk. Negative
                values are clamped to zero.
        """
        count = max(0, count)
        if self._count == count:
            return
        self._count = count
        self.tooltip = self._build_tooltip(count)
        if self.is_mounted:
            self.update(self._build_content(count))

    @staticmethod
    def _build_content(count: int) -> Text:
        """Build the badge text; empty (hidden) when nothing is stashed."""
        if count > 0:
            return Text(f" ❄ {count} ", style="bold #1a1a1a on #AF87FF")
        return Text("")

    @staticmethod
    def _build_tooltip(count: int) -> str:
        """Build the hover tooltip describing the stash size."""
        if count <= 0:
            return "No stashed prompts"
        if count == 1:
            return "1 stashed prompt"
        return f"{count} stashed prompts"
