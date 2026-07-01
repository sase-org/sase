"""Persistent updates-available indicator widget for the ace TUI."""

from typing import Any

from rich.text import Text
from textual.widgets import Static

_UPDATES_ACCENT = "#AF87FF"
_UPDATE_GLYPH = "↑"


class UpdatesAvailableIndicator(Static):
    """Top-bar badge showing known SASE core/plugin updates."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(self._build_content(0), **kwargs)
        self._count = 0
        self.tooltip = self._build_tooltip(0)

    @property
    def count(self) -> int:
        """Number of available updates currently shown."""
        return self._count

    def set_available(self, count: int) -> None:
        """Update the displayed updates count, hiding the badge at zero."""
        count = max(0, count)
        if self._count == count:
            return
        self._count = count
        self.tooltip = self._build_tooltip(count)
        if self.is_mounted:
            self.update(self._build_content(count))

    async def on_click(self) -> None:
        """Open the Admin Center's Updates tab."""
        await self.app.run_action("open_updates_panel")

    @staticmethod
    def _build_content(count: int) -> Text:
        """Build the badge text."""
        if count > 0:
            return Text(
                f" {_UPDATE_GLYPH} {count} ",
                style=f"bold #1a1a1a on {_UPDATES_ACCENT}",
            )
        return Text("")

    @staticmethod
    def _build_tooltip(count: int) -> str:
        """Build the hover tooltip describing the update count."""
        if count <= 0:
            return "No updates available"
        noun = "update" if count == 1 else "updates"
        return (
            f"{count} {noun} available - click to open Updates, "
            "or press ,U to update sase, core & plugins"
        )
