"""Tab bar widget for switching between views."""

from typing import Any

from rich.text import Text
from textual.events import Click
from textual.message import Message
from textual.widgets import Static

from ..keymaps import KeymapRegistry, load_keymap_registry
from ..tab_order import TAB_ORDER, TabName

_TAB_COLORS: dict[TabName, str] = {
    "changespecs": "#00D7AF",
    "agents": "#87D7FF",
    "axe": "#FF5F5F",
}

_TAB_DISPLAY_NAMES: dict[TabName, str] = {
    "changespecs": "Artifacts",
    "agents": "Agents",
    "axe": "AXE",
}

# Rendered left-to-right in TAB_ORDER so the visible labels track the
# shared tab order used by keyboard cycling.
_TAB_LABELS: list[tuple[TabName, str]] = [
    (tab, _TAB_DISPLAY_NAMES[tab]) for tab in TAB_ORDER
]


class TabBar(Static):
    """Horizontal tab bar showing available tabs with selection indicator."""

    class TabClicked(Message):
        """Message sent when a tab is clicked."""

        def __init__(self, tab: TabName) -> None:
            super().__init__()
            self.tab = tab

    def __init__(self, **kwargs: Any) -> None:
        self._registry = load_keymap_registry({})
        self._current_tab: TabName = TAB_ORDER[0]
        self._tab_ranges: dict[TabName, tuple[int, int]] = dict.fromkeys(
            TAB_ORDER, (0, 0)
        )
        super().__init__(self._build_content(), **kwargs)

    def set_keymap_registry(self, registry: KeymapRegistry) -> None:
        """Override the keymap registry and refresh display."""
        self._registry = registry
        self._refresh_content()

    def update_tab(self, tab: TabName) -> None:
        """Update the displayed active tab."""
        self._current_tab = tab
        self._refresh_content()

    def _build_content(self) -> Text:
        """Build the tab bar content."""
        text = Text()
        for i, (tab, name) in enumerate(_TAB_LABELS):
            if i > 0:
                text.append(" │ ", style="#444444")
            is_active = self._current_tab == tab
            style = f"bold {_TAB_COLORS[tab]}" if is_active else "#888888"
            start = len(text.plain)
            text.append(f" {name} ", style=style)
            self._tab_ranges[tab] = (start, len(text.plain))
        return text

    def _refresh_content(self) -> None:
        """Refresh the tab bar display."""
        if self.is_mounted:
            self.update(self._build_content())

    def on_click(self, event: Click) -> None:
        """Handle click events to switch tabs."""
        x = event.x
        for tab, (start, end) in self._tab_ranges.items():
            if start <= x < end:
                if self._current_tab != tab:
                    self.post_message(self.TabClicked(tab))
                return
