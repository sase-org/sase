"""Persistent updates-available indicator widget for the ace TUI."""

from typing import Any

from rich.text import Text
from textual.widgets import Static

_UPDATES_ACCENT = "#AF87FF"
_CORE_UPDATE_ACCENT = "#FFAF5F"
_UPDATE_GLYPH = "↑"
_CORE_UPDATE_GLYPH = "*"


class UpdatesAvailableIndicator(Static):
    """Top-bar badge showing known SASE core/plugin updates."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(self._build_content(0, core=False), **kwargs)
        self._count = 0
        self._core = False
        self.tooltip = self._build_tooltip(0, core=False)

    @property
    def count(self) -> int:
        """Number of available updates currently shown."""
        return self._count

    @property
    def core(self) -> bool:
        """Whether the current badge signals a pending core rebuild."""
        return self._core

    def set_available(self, count: int, *, core: bool = False) -> None:
        """Update the badge count and rebuild signal, hiding it at zero."""
        count = max(0, count)
        core = bool(core and count > 0)
        if self._count == count and self._core == core:
            return
        self._count = count
        self._core = core
        self.tooltip = self._build_tooltip(count, core=core)
        if self.is_mounted:
            self.update(self._build_content(count, core=core))

    async def on_click(self) -> None:
        """Open the Admin Center's Updates tab."""
        await self.app.run_action("open_updates_panel")

    @staticmethod
    def _build_content(count: int, *, core: bool = False) -> Text:
        """Build the badge text."""
        if count > 0:
            suffix = f" {_CORE_UPDATE_GLYPH}" if core else ""
            accent = _CORE_UPDATE_ACCENT if core else _UPDATES_ACCENT
            return Text(
                f" {_UPDATE_GLYPH} {count}{suffix} ",
                style=f"bold #1a1a1a on {accent}",
            )
        return Text("")

    @staticmethod
    def _build_tooltip(count: int, *, core: bool = False) -> str:
        """Build the hover tooltip describing the update count."""
        if count <= 0:
            return "No updates available"
        noun = "update" if count == 1 else "updates"
        if core:
            return (
                f"{count} {noun} available — includes sase-core "
                "(Rust rebuild, expect a slower update). Click to open Updates, "
                "or press ,U to update sase, core & plugins"
            )
        return (
            f"{count} {noun} available - click to open Updates, "
            "or press ,U to update sase, core & plugins"
        )
