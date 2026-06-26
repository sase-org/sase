"""Filter input for the Config Center Updates plugin browser."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual import events
from textual.widgets import Input

if TYPE_CHECKING:
    from .plugins_browser_pane import PluginsBrowserPane


class PluginsFilterInput(Input):
    """Filter input that yields ``[`` / ``]`` to the host tab strip.

    Like the other Config Center panes, ``[`` / ``]`` must reach the host
    modal so tab switching works while typing; ``escape`` returns focus to
    the list without leaving a stale filter applied.
    """

    def on_key(self, event: events.Key) -> None:
        if event.key in ("left_square_bracket", "right_square_bracket"):
            host = self.screen
            prev_tab = getattr(host, "action_prev_center_tab", None)
            next_tab = getattr(host, "action_next_center_tab", None)
            if callable(prev_tab) and callable(next_tab):
                event.stop()
                event.prevent_default()
                (prev_tab if event.key == "left_square_bracket" else next_tab)()
        elif event.key == "escape":
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
