"""Color-coded footer describing the opener key's in-tab alternate jump."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from rich.text import Text
from textual.events import Click
from textual.widgets import Static

from ..keymaps import key_display_name
from .config_center_catalog import CenterTab, _TAB_BY_ID

_ARROW_GLYPH = "↔"
_ENABLED_ARROW_STYLE = "#666666"
_ENABLED_COPY_STYLE = "#777777"
_DISABLED_CHIP_STYLE = "bold reverse #585858"
_DISABLED_ARROW_STYLE = "#444444"
_DISABLED_COPY_STYLE = "#666666"
_DISABLED_COPY_ROOMY = "no earlier section yet"
_DISABLED_COPY_COMPACT = "none yet"


def _footer_text(
    alternate: CenterTab | None,
    opener_binding: str,
    *,
    compact: bool,
) -> Text:
    """Render the footer's roomy or compact, color-coded destination copy."""
    key = key_display_name(opener_binding)
    text = Text()
    if alternate is None:
        text.append(f" {key} ", style=_DISABLED_CHIP_STYLE)
        text.append(f"  {_ARROW_GLYPH}  ", style=_DISABLED_ARROW_STYLE)
        text.append(
            _DISABLED_COPY_COMPACT if compact else _DISABLED_COPY_ROOMY,
            style=_DISABLED_COPY_STYLE,
        )
        return text

    spec = _TAB_BY_ID[alternate]
    text.append(f" {key} ", style=f"bold reverse {spec.accent}")
    text.append(f"  {_ARROW_GLYPH}  ", style=_ENABLED_ARROW_STYLE)
    text.append(spec.label, style=f"bold {spec.accent}")
    if not compact:
        text.append("  ·  press again to return here", style=_ENABLED_COPY_STYLE)
    return text


class AdminCenterFooter(Static):
    """Clickable, width-aware footer naming the opener's alternate jump."""

    def __init__(self, on_select: Callable[[CenterTab], None], **kwargs: Any) -> None:
        super().__init__("", **kwargs)
        self._on_select = on_select
        self._alternate: CenterTab | None = None
        self._opener_binding = "number_sign"

    def update_state(self, alternate: CenterTab | None, opener_binding: str) -> None:
        """Repaint after the active section or the alternate slot changes."""
        self._alternate = alternate
        self._opener_binding = opener_binding
        self.refresh()

    def render(self) -> Text:
        width = max(0, int(self.size.width))
        roomy = _footer_text(self._alternate, self._opener_binding, compact=False)
        if width <= 0 or roomy.cell_len <= width:
            return roomy
        return _footer_text(self._alternate, self._opener_binding, compact=True)

    def on_click(self, event: Click) -> None:
        """Jump to the alternate section, mirroring a landing row click."""
        event.stop()
        if self._alternate is not None:
            self._on_select(self._alternate)


__all__ = ["AdminCenterFooter"]
