"""Reusable clickable one-line tab strip for modal panels."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from rich.cells import cell_len
from rich.text import Text
from textual.events import Click, Resize
from textual.message import Message
from textual.widgets import Static


@dataclass(frozen=True)
class PanelTab:
    """A tab entry rendered by :class:`PanelTabStrip`."""

    id: str
    label: str
    accent_color: str
    compact_label: str | None = None
    micro_label: str | None = None
    shortcut: str | None = None
    icon: str = ""


_PanelTabTier = Literal["full", "compact", "micro"]


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
        active_tab: str | None,
        *,
        show_numbers: bool = False,
        uppercase_active: bool = False,
        compact_below: int | None = None,
        compact_separator: str = " │ ",
        micro_below: int | None = None,
        micro_separator: str = "│",
        reflow_to_fit: bool = False,
        **kwargs: Any,
    ) -> None:
        self._tabs = tuple(tabs)
        self._active_tab = active_tab
        self._show_numbers = show_numbers
        self._uppercase_active = uppercase_active
        self._compact_below = compact_below
        self._compact_separator = compact_separator
        self._micro_below = micro_below
        self._micro_separator = micro_separator
        self._reflow_to_fit = reflow_to_fit
        self._tier: _PanelTabTier = "full"
        self._tab_ranges: dict[str, tuple[int, int]] = {}
        self._line_width = 0
        super().__init__(self._build_content(), **kwargs)

    def set_active_tab(self, active_tab: str | None) -> None:
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

    def _build_content(self, tier: _PanelTabTier | None = None) -> Text:
        """Render one tier, recording click ranges in terminal cells.

        ``event.x`` in :meth:`on_click` is in cells, so ranges built from
        character counts silently shift onto the wrong tab once any fragment
        (a two-cell icon, say) is wider than one cell. ``tier`` lets callers
        probe a candidate tier's rendered width without disturbing
        ``self._tier`` first; the caller that ultimately keeps a tier is the
        last one to call this, so ``self._tab_ranges``/``self._line_width``
        always end up matching whatever was actually rendered.
        """
        active_tier = self._tier if tier is None else tier
        text = Text()
        tab_ranges: dict[str, tuple[int, int]] = {}
        column = 0

        def append(fragment: str, style: str | None = None) -> None:
            nonlocal column
            text.append(fragment, style=style)
            column += cell_len(fragment)

        # Dropping inactive labels only reads as "narrow tabs" when every tab
        # still carries an icon to identify it; otherwise fall back to the
        # existing shortened-label behavior so a tab never renders blank.
        hide_inactive_labels = active_tier == "micro" and all(
            tab.icon for tab in self._tabs
        )

        for index, tab in enumerate(self._tabs):
            if index > 0:
                separator = {
                    "full": " │ ",
                    "compact": self._compact_separator,
                    "micro": self._micro_separator,
                }[active_tier]
                append(separator, "#444444")
            is_active = tab.id == self._active_tab
            label_style = f"bold {tab.accent_color}" if is_active else "#888888"
            start = column
            if self._show_numbers:
                number_style = tab.accent_color if is_active else "#666666"
                shortcut = tab.shortcut or str(index + 1)
                number = f" {shortcut} " if active_tier == "full" else f"{shortcut} "
                append(number, number_style)
            elif active_tier == "full":
                append(" ")
            if tab.icon:
                icon_style = tab.accent_color if is_active else "#666666"
                append(tab.icon, icon_style)
            if hide_inactive_labels and not is_active:
                source_label = ""
            elif active_tier == "micro":
                source_label = tab.micro_label or tab.compact_label or tab.label
            elif active_tier == "compact":
                source_label = tab.compact_label or tab.label
            else:
                source_label = tab.label
            label = (
                source_label.upper()
                if self._uppercase_active and is_active
                else source_label
            )
            if label:
                prefix = " " if tab.icon else ""
                suffix = " " if active_tier == "full" else ""
                append(f"{prefix}{label}{suffix}", label_style)
            tab_ranges[tab.id] = (start, column)

        self._tab_ranges = tab_ranges
        self._line_width = column
        return text

    def on_resize(self, _event: Resize) -> None:
        """Reflow strips that opt into compact/micro thresholds or a fit ladder."""
        if (
            self._compact_below is None
            and self._micro_below is None
            and not self._reflow_to_fit
        ):
            return
        width = int(_event.size.width)
        if self._compact_below is not None or self._micro_below is not None:
            if self._micro_below is not None and 0 < width < self._micro_below:
                tier: _PanelTabTier = "micro"
            elif self._compact_below is not None and 0 < width < self._compact_below:
                tier = "compact"
            else:
                tier = "full"
        else:
            tier = self._reflow_tier_for_width(width)
        if tier == self._tier:
            return
        self._tier = tier
        self.update(self._build_content())

    def _reflow_tier_for_width(self, width: int) -> _PanelTabTier:
        """Pick the widest tier whose render fits ``width`` cells.

        Falls back to ``micro`` when nothing fits, and leaves the tier
        unchanged when ``width`` is not yet known (0 or negative), matching
        the pre-mount default of rendering ``full``.
        """
        if width <= 0:
            return self._tier
        tiers: tuple[_PanelTabTier, ...] = ("full", "compact", "micro")
        for candidate in tiers:
            if cell_len(self._build_content(candidate).plain) <= width:
                return candidate
        return "micro"

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
