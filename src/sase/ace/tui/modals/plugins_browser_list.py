"""OptionList widget for the Config Center Updates plugin browser."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual import events
from textual.widgets import OptionList

if TYPE_CHECKING:
    from .plugins_browser_pane import PluginsBrowserPane


class PluginsBrowserList(OptionList):
    """Plugin list that reserves vim top/bottom keys for the detail pane."""

    BINDINGS = [
        ("ctrl+d", "scroll_detail_down", "Scroll Down"),
        ("ctrl+u", "scroll_detail_up", "Scroll Up"),
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
        pane = self._pane()
        # ``g`` and ``G`` are ordinary hint characters while the pane paints
        # jump hints, so the pane's jump handler gets them instead of the
        # detail scroller.
        if pane is not None and pane.jump_mode_active:
            return False
        character = getattr(event, "character", None)
        if event.key in ("G", "shift+g") or character == "G":
            event.prevent_default()
            event.stop()
            if pane is not None:
                pane.action_scroll_to_bottom()
            return True
        if event.key == "g":
            event.prevent_default()
            event.stop()
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

    def action_scroll_detail_down(self) -> None:
        pane = self._pane()
        if pane is not None:
            pane.action_scroll_detail_down()

    def action_scroll_detail_up(self) -> None:
        pane = self._pane()
        if pane is not None:
            pane.action_scroll_detail_up()

    def _pane(self) -> PluginsBrowserPane | None:
        from .plugins_browser_pane import PluginsBrowserPane

        node: object | None = self.parent
        while node is not None:
            if isinstance(node, PluginsBrowserPane):
                return node
            node = getattr(node, "parent", None)
        return None


_PluginList = PluginsBrowserList
