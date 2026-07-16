"""Reusable clickable one-line tab strip for modal panels."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from rich.text import Text
from textual.events import Click
from textual.message import Message
from textual.widgets import Static


@dataclass(frozen=True)
class PanelTab:
    """A tab entry rendered by :class:`PanelTabStrip`."""

    id: str
    label: str
    accent_color: str


class PanelTabStrip(Static):
    """Clickable centered tab strip used by tabbed modal panels."""

    class TabClicked(Message):
        """Message emitted when a tab is clicked."""

        def __init__(self, tab_id: str) -> None:
            super().__init__()
            self.tab_id = tab_id

    def __init__(
        self,
        tabs: Sequence[PanelTab],
        active_tab: str,
        *,
        show_numbers: bool = False,
        uppercase_active: bool = False,
        **kwargs: Any,
    ) -> None:
        self._tabs = tuple(tabs)
        self._active_tab = active_tab
        self._show_numbers = show_numbers
        self._uppercase_active = uppercase_active
        self._tab_ranges: dict[str, tuple[int, int]] = {}
        self._line_width = 0
        super().__init__(self._build_content(), **kwargs)

    def set_active_tab(self, active_tab: str) -> None:
        """Refresh the active tab indicator."""
        self._active_tab = active_tab
        self.update(self._build_content())

    def set_tabs(
        self,
        tabs: Sequence[PanelTab],
        *,
        active_tab: str | None = None,
    ) -> None:
        """Replace the rendered tab entries and refresh."""
        self._tabs = tuple(tabs)
        if active_tab is not None:
            self._active_tab = active_tab
        self.update(self._build_content())

    def _build_content(self) -> Text:
        text = Text()
        self._tab_ranges.clear()
        for index, tab in enumerate(self._tabs):
            if index > 0:
                text.append(" │ ", style="#444444")
            is_active = tab.id == self._active_tab
            label_style = f"bold {tab.accent_color}" if is_active else "#888888"
            start = len(text.plain)
            if self._show_numbers:
                number_style = tab.accent_color if is_active else "#666666"
                text.append(f" {index + 1} ", style=number_style)
            else:
                text.append(" ")
            label = (
                tab.label.upper() if self._uppercase_active and is_active else tab.label
            )
            text.append(f"{label} ", style=label_style)
            self._tab_ranges[tab.id] = (start, len(text.plain))
        self._line_width = len(text.plain)
        return text

    def on_click(self, event: Click) -> None:
        """Post :class:`TabClicked` when the user clicks a tab label."""
        content_width = max(0, int(self.size.width))
        center_pad = max(0, (content_width - self._line_width) // 2)
        x = event.x - center_pad
        for tab_id, (start, end) in self._tab_ranges.items():
            if start <= x < end:
                if tab_id != self._active_tab:
                    self.post_message(self.TabClicked(tab_id))
                return
