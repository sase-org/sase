"""Slim node-panel affordance shown while the node list is collapsed."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.message import Message
from textual.widgets import Static

_TRACK_GLYPH = "│"
_THUMB_GLYPH = "┃"
_AFFORDANCE_GLYPH = "»"


def spine_geometry(track_rows: int, index: int, total: int) -> tuple[int, int]:
    """Return ``(thumb_start, thumb_size)`` for a ``track_rows``-tall track.

    The thumb is positioned and sized in proportion to ``index`` among
    ``total`` navigation stops, like a minimap scrollbar. Both values are
    clamped into the track; an empty track yields ``(0, 0)``.
    """
    if track_rows <= 0 or total <= 0:
        return (0, 0)
    size = max(1, round(track_rows / total))
    size = min(size, track_rows)
    if total <= 1:
        return (0, size)
    clamped = max(0, min(total - 1, index))
    start = round((track_rows - size) * clamped / (total - 1))
    return (start, size)


class NodeSpineExpandRequested(Message):
    """A click on the collapsed node spine asked to expand the node panel."""


class NodeSpine(Static):
    """Two-cell-wide collapsed node-panel indicator with a scroll thumb."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the spine with an empty selection."""
        super().__init__(**kwargs)
        self._index = 0
        self._total = 0

    @property
    def position(self) -> tuple[int, int]:
        """Return the ``(index, total)`` selection the spine renders."""
        return (self._index, self._total)

    def update_position(self, index: int, total: int) -> None:
        """Render the thumb for ``index`` among ``total`` stops."""
        self._index = max(0, index)
        self._total = max(0, total)
        self._render_spine()
        self._refresh_tooltip()

    def on_mount(self) -> None:
        """Render the initial spine and tooltip."""
        self._render_spine()
        self._refresh_tooltip()

    def on_click(self, _event: object) -> None:
        """Ask to expand the node panel without stealing widget focus."""
        try:
            self.post_message(NodeSpineExpandRequested())
        except Exception:
            pass

    def _collapse_key_text(self) -> str:
        try:
            from ...keymaps import key_display_name
        except Exception:
            return "Ctrl+S"
        try:
            registry = getattr(getattr(self, "app", None), "_keymap_registry", None)
            if registry is None:
                return "Ctrl+S"
            return key_display_name(
                str(getattr(getattr(registry, "app", None), "toggle_node_panel", ""))
            )
        except Exception:
            return "Ctrl+S"

    def _refresh_tooltip(self) -> None:
        try:
            self.tooltip = f"Expand node panel ({self._collapse_key_text()})"
        except Exception:
            pass

    def _render_spine(self) -> None:
        try:
            height = int(self.size.height)
        except Exception:
            height = 0
        if height <= 0:
            height = 8
        text = Text()
        text.append(_AFFORDANCE_GLYPH, style="bold #FFD700")
        track_rows = max(0, height - 1)
        start, size = spine_geometry(track_rows, self._index, self._total)
        for row in range(track_rows):
            text.append("\n", style="")
            if start <= row < start + size:
                text.append(_THUMB_GLYPH, style="bold #FFD700")
            else:
                text.append(_TRACK_GLYPH, style="dim")
        try:
            self.update(text)
        except Exception:
            pass
