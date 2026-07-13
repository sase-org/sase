"""Filter input for the Config Center Updates plugin browser."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual import events
from textual.widgets import Input

if TYPE_CHECKING:
    from .plugins_browser_pane import PluginsBrowserPane


class PluginsFilterInput(Input):
    """Filter input with pane-local escape handling.

    Brackets remain ordinary filter text; ``escape`` returns focus to the list
    without leaving a stale filter applied. The Admin Center's priority
    ``Tab`` / ``Shift+Tab`` bindings handle main-tab navigation.
    """

    def on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            pane = self._pane()
            if pane is not None:
                event.stop()
                event.prevent_default()
                pane.cancel_input()

    def _pane(self) -> PluginsBrowserPane | None:
        from .plugins_browser_pane import PluginsBrowserPane

        node: object | None = self.parent
        while node is not None:
            if isinstance(node, PluginsBrowserPane):
                return node
            node = getattr(node, "parent", None)
        return None


_PluginsFilterInput = PluginsFilterInput
