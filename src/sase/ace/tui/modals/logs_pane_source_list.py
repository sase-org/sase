"""Source-list widget for the Admin Center Logs pane."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual import events
from textual.widgets import OptionList

if TYPE_CHECKING:
    from .logs_pane import LogsPane


class LogSourceList(OptionList):
    """Source list that reserves vim top/bottom keys for the detail pane."""

    BINDINGS = [
        ("g", "scroll_detail_top", "Top"),
        ("G", "scroll_detail_bottom", "Bottom"),
        ("shift+g", "scroll_detail_bottom", "Bottom"),
        *OptionList.BINDINGS,
    ]

    async def handle_key(self, event: events.Key) -> bool:
        if self._handle_detail_scroll_key(event):
            return True
        return await super().handle_key(event)

    def on_key(self, event: events.Key) -> None:
        self._handle_detail_scroll_key(event)

    def _handle_detail_scroll_key(self, event: events.Key) -> bool:
        character = getattr(event, "character", None)
        if event.key in ("G", "shift+g") or character == "G":
            event.prevent_default()
            event.stop()
            pane = self._pane()
            if pane is not None:
                pane.action_scroll_to_bottom()
            return True
        if event.key == "g":
            event.prevent_default()
            event.stop()
            pane = self._pane()
            if pane is not None:
                pane.action_scroll_to_top()
            return True
        return False

    def action_scroll_detail_top(self) -> None:
        pane = self._pane()
        if pane is not None:
            pane.action_scroll_to_top()

    def action_scroll_detail_bottom(self) -> None:
        pane = self._pane()
        if pane is not None:
            pane.action_scroll_to_bottom()

    def _pane(self) -> LogsPane | None:
        # Import lazily to avoid a module cycle while LogsPane composes this widget.
        from .logs_pane import LogsPane

        node: object | None = self.parent
        while node is not None:
            if isinstance(node, LogsPane):
                return node
            node = getattr(node, "parent", None)
        return None


__all__ = ["LogSourceList"]
