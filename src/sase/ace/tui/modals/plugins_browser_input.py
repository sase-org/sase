"""Filter input for the Config Center Updates plugin browser."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual import events
from textual.widgets import Input

if TYPE_CHECKING:
    from .plugins_browser_pane import PluginsBrowserPane


class PluginsFilterInput(Input):
    """Filter input with pane-local escape handling.

    Brackets cycle the pane-local sub-tabs even while the filter owns focus;
    ``escape`` returns focus to the list without leaving a stale filter applied.
    The Admin Center's priority ``Tab`` / ``Shift+Tab`` bindings handle main-tab
    navigation.
    """

    def on_key(self, event: events.Key) -> None:
        pane = self._pane()
        if pane is None:
            return
        if event.key == "escape":
            event.stop()
            event.prevent_default()
            pane.cancel_input()
        elif event.key in ("left_square_bracket", "right_square_bracket"):
            event.stop()
            event.prevent_default()
            if event.key == "left_square_bracket":
                pane.action_cycle_subtab_reverse()
            else:
                pane.action_cycle_subtab()

    def _pane(self) -> PluginsBrowserPane | None:
        from .plugins_browser_pane import PluginsBrowserPane

        node: object | None = self.parent
        while node is not None:
            if isinstance(node, PluginsBrowserPane):
                return node
            node = getattr(node, "parent", None)
        return None


_PluginsFilterInput = PluginsFilterInput
