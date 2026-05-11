"""Tab bar widget for switching between views."""

from typing import Any, Literal

from rich.text import Text
from textual.events import Click
from textual.message import Message
from textual.widgets import Static

from ..keymaps import KeymapRegistry, load_keymap_registry

TabName = Literal["changespecs", "agents", "axe"]

_TAB_COLORS: dict[TabName, str] = {
    "changespecs": "#00D7AF",
    "agents": "#87D7FF",
    "axe": "#FF5F5F",
}

_TAB_LABELS: list[tuple[TabName, str]] = [
    ("changespecs", "CLs"),
    ("agents", "Agents"),
    ("axe", "AXE"),
]

_TAB_ALERT_STYLE = "bold #FFAF00"


class TabBar(Static):
    """Horizontal tab bar showing available tabs with selection indicator."""

    class TabClicked(Message):
        """Message sent when a tab is clicked."""

        def __init__(self, tab: TabName) -> None:
            super().__init__()
            self.tab = tab

    def __init__(self, **kwargs: Any) -> None:
        self._registry = load_keymap_registry({})
        self._current_tab: TabName = "changespecs"
        self._tab_ranges: dict[TabName, tuple[int, int]] = {
            "changespecs": (0, 0),
            "agents": (0, 0),
            "axe": (0, 0),
        }
        self._tab_badges: dict[TabName, int] = {
            "changespecs": 0,
            "agents": 0,
            "axe": 0,
        }
        super().__init__(self._build_content(), **kwargs)

    def set_keymap_registry(self, registry: KeymapRegistry) -> None:
        """Override the keymap registry and refresh display."""
        self._registry = registry
        self._refresh_content()

    def update_tab(self, tab: TabName) -> None:
        """Update the displayed active tab."""
        self._current_tab = tab
        self._refresh_content()

    def set_tab_badge(self, tab: TabName, count: int) -> None:
        """Set the unread badge count for a tab.

        A count of 0 (or negative) clears the badge. When the tab is inactive
        and the count is positive, the label renders as ``Name(count)`` in the
        alert style; the focused tab always suppresses its badge rendering.
        """
        normalized = count if count > 0 else 0
        if self._tab_badges[tab] == normalized:
            return
        self._tab_badges[tab] = normalized
        self._refresh_content()

    def _build_content(self) -> Text:
        """Build the tab bar content."""
        text = Text()
        for i, (tab, name) in enumerate(_TAB_LABELS):
            if i > 0:
                text.append(" │ ", style="#444444")
            is_active = self._current_tab == tab
            badge = self._tab_badges[tab]
            show_badge = not is_active and badge > 0
            label = f"{name}({badge})" if show_badge else name
            if is_active:
                style = f"bold {_TAB_COLORS[tab]}"
            elif show_badge:
                style = _TAB_ALERT_STYLE
            else:
                style = "#888888"
            start = len(text.plain)
            text.append(f" {label} ", style=style)
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
