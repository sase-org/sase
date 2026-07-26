"""Always-visible description banner for selected AXE configuration rows."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.widgets import Static

_LUMBERJACK_ACCENT = "bold #FFD700"
_CHOP_ACCENT = "#D7AF87"
_DESCRIPTION_STYLE = "italic #D7D7AF"
_TARGET_STYLE = "dim #B87333"
_FALLBACK = "No description configured"


class AxeDescriptionBanner(Static):
    """Render the selected lumberjack or chop description."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the banner hidden until a configuration row is selected."""
        super().__init__("", **kwargs)
        self._description_renderable = Text(overflow="ellipsis")
        self.display = False

    def render(self) -> Text:
        """Return the current description without requiring an app mount."""
        return self._description_renderable

    def show_lumberjack(self, name: str, description: str) -> None:
        """Show a lumberjack description using the top-level AXE accent."""
        del name
        self._show(description, accent_style=_LUMBERJACK_ACCENT)

    def show_chop(
        self,
        chop_name: str,
        description: str,
        *,
        generated: bool = False,
        target_key: str | None = None,
    ) -> None:
        """Show a chop description and optional generated-target chip."""
        del chop_name
        text = self._description_text(description, accent_style=_CHOP_ACCENT)
        if generated and target_key:
            text.append(f"  · {target_key}", style=_TARGET_STYLE)
        self.display = True
        self._set_description(text)

    def hide(self) -> None:
        """Remove the banner from layouts without a selected AXE config row."""
        self.display = False

    def _show(self, description: str, *, accent_style: str) -> None:
        self.display = True
        self._set_description(
            self._description_text(description, accent_style=accent_style)
        )

    def _set_description(self, text: Text) -> None:
        self._description_renderable = text
        if self.is_attached:
            self.refresh(layout=True)

    @staticmethod
    def _description_text(description: str, *, accent_style: str) -> Text:
        text = Text(overflow="ellipsis")
        text.append("▌ ", style=accent_style)
        if description.strip():
            text.append(description, style=_DESCRIPTION_STYLE)
        else:
            text.append(_FALLBACK, style="dim italic")
        return text
