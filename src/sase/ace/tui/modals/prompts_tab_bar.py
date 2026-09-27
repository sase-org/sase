"""Split-button Stash tab bar for the Prompts overlay.

Two top-level tabs (Stash, History) in a polished pill-style bar. Trash is
a view inside the Stash tab, opened with ``t`` or a trash chip. The bar is
one content row plus a hairline rule (CSS), laid out left-aligned from
column 0:

Stash list view (stash 3, trash 2 of 100):
`` ≡ Stash 3 `` (pink pill) + `` 🗑️ 2 `` (quiet secondary) + 3 spaces +
`` ↺ History `` (flat) + right-aligned hints ``t trash · [ ] tabs``

Trash view moves the fill to the trash segment (amber) and expands its
label to ``🗑️ Trash N/LIMIT``. History active renders both Stash segments
flat with no background.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from rich.cells import cell_len
from rich.text import Text
from textual import events
from textual.message import Message
from textual.widget import Widget

from .prompt_stash_row import TRASH_GLYPH

STASH_GLYPH = "≡"
HISTORY_GLYPH = "↺"

STASH_ACCENT = "#FF87D7"
HISTORY_ACCENT = "#5FD7FF"
TRASH_ACCENT = "#EBC04F"

_DARK_FG = "#1a1a1a"
_SECONDARY_BG = "#303030"
_SECONDARY_FG = "#bcbcbc"
_FLAT_FG = "#8a8a8a"
_MUTED_FG = "#6c6c6c"
_SEPARATOR_FG = "#4e4e4e"
_HOVER_FG = "#d0d0d0"
_FULL_RED = "#FF5F5F"

SurfaceId = Literal["stash", "trash", "history"]
TierId = Literal["full", "compact", "micro"]


@dataclass(frozen=True, slots=True)
class PromptsTabBarState:
    """Counts driving the tab bar render."""

    surface: str
    stash_count: int = 0
    trash_count: int = 0
    trash_limit: int = 100


@dataclass(frozen=True, slots=True)
class _PromptsTabBarLayout:
    """Pure layout result: rendered text, tier, and click hits."""

    text: Text
    tier: str
    hits: tuple[tuple[int, int, str], ...]


def _stash_label(stash_count: int, tier: str) -> str:
    if tier == "micro":
        return f"{STASH_GLYPH} {stash_count}"
    return f"{STASH_GLYPH} Stash {stash_count}"


def _trash_inactive_label(trash_count: int, trash_limit: int) -> str:
    if trash_limit == 0:
        return f"{TRASH_GLYPH} off"
    if trash_count == 0:
        return f"{TRASH_GLYPH}"
    return f"{TRASH_GLYPH} {trash_count}"


def _trash_active_label(trash_count: int, trash_limit: int, tier: str) -> str:
    if trash_limit == 0:
        if tier == "micro":
            return f"{TRASH_GLYPH} off"
        return f"{TRASH_GLYPH} Trash off"
    if tier == "micro":
        return f"{TRASH_GLYPH} {trash_count}/{trash_limit}"
    return f"{TRASH_GLYPH} Trash {trash_count}/{trash_limit}"


def _history_label(tier: str) -> str:
    if tier == "micro":
        return HISTORY_GLYPH
    return f"{HISTORY_GLYPH} History"


def _hints_parts(surface: str) -> list[tuple[str, str]]:
    if surface == "stash":
        return [
            ("t", "#bcbcbc"),
            (" trash ", "#6c6c6c"),
            ("·", "#4e4e4e"),
            (" ", ""),
            ("[ ]", "#bcbcbc"),
            (" tabs", "#6c6c6c"),
        ]
    if surface == "trash":
        return [
            ("t/esc", "#bcbcbc"),
            (" back ", "#6c6c6c"),
            ("·", "#4e4e4e"),
            (" ", ""),
            ("[ ]", "#bcbcbc"),
            (" tabs", "#6c6c6c"),
        ]
    return [
        ("[ ]", "#bcbcbc"),
        (" tabs", "#6c6c6c"),
    ]


def _hints_len(surface: str) -> int:
    return sum(cell_len(fragment) for fragment, _ in _hints_parts(surface))


def _tooltip_for_surface(
    surface: str,
    *,
    stash_count: int,
    trash_count: int,
    trash_limit: int,
) -> str:
    """Return the hover tooltip for one bar segment."""
    if surface == "stash":
        return f"Stash — {stash_count} stashed drafts"
    if surface == "trash":
        if trash_limit == 0:
            return "Trash recovery is off (ace.prompt_stash.trash_limit: 0)"
        if trash_count >= trash_limit:
            return (
                "Trash is full — the next discard permanently deletes "
                "the oldest draft · t"
            )
        return f"Trash — {trash_count} of {trash_limit} discarded drafts kept · t"
    return "History — submitted prompts"


def _is_trash_full(trash_count: int, trash_limit: int) -> bool:
    return trash_limit > 0 and trash_count >= trash_limit


def _layout_prompts_tab_bar(
    state: PromptsTabBarState,
    width: int,
    *,
    hover: str | None = None,
) -> _PromptsTabBarLayout:
    """Lay out the tab bar for *state* at *width* cells.

    Picks the widest tier whose rendered ``cell_len`` fits: ``full``
    (segments plus hints, gap of at least 2 cells before the hints),
    ``compact`` (segments only), ``micro`` (words dropped). Until the width
    is known (``width <= 0``), renders ``full`` with a minimal 2-cell gap.
    Every fragment is measured with ``rich.cells.cell_len`` because the
    trash emoji is two cells.
    """
    surface = state.surface
    stash_count = state.stash_count
    trash_count = state.trash_count
    trash_limit = state.trash_limit

    # -- segment labels per tier -------------------------------------------
    def _labels(tier: str) -> tuple[str, str, str]:
        if surface == "trash":
            trash_label = _trash_active_label(trash_count, trash_limit, tier)
        else:
            trash_label = _trash_inactive_label(trash_count, trash_limit)
        return (
            _stash_label(stash_count, tier),
            trash_label,
            _history_label(tier),
        )

    def _segments_len(tier: str) -> int:
        stash_label, trash_label, history_label = _labels(tier)
        # Each segment has one space padding inside on both sides.
        stash_len = cell_len(f" {stash_label} ")
        trash_len = cell_len(f" {trash_label} ")
        history_len = cell_len(f" {history_label} ")
        gap = 1 if tier == "micro" else 3
        if tier == "micro":
            # 1-space gaps between every segment.
            return stash_len + 1 + trash_len + 1 + history_len
        return stash_len + trash_len + gap + history_len

    # -- tier selection ------------------------------------------------------
    if width <= 0:
        tier: str = "full"
    else:
        hints_len = _hints_len(surface)
        full_segments = _segments_len("full")
        if full_segments + 2 + hints_len <= width:
            tier = "full"
        elif _segments_len("compact") <= width:
            tier = "compact"
        else:
            tier = "micro"

    stash_label, trash_label, history_label = _labels(tier)

    text = Text()
    hits: list[tuple[int, int, str]] = []
    column = 0

    def _append(fragment: str, style: str | None) -> None:
        nonlocal column
        text.append(fragment, style=style or None)
        column += cell_len(fragment)

    def _append_spaces(count: int) -> None:
        if count > 0:
            _append(" " * count, None)

    # -- segment styles ------------------------------------------------------
    if surface == "stash":
        if hover == "stash":
            stash_style: str | None = f"bold {_HOVER_FG} on {STASH_ACCENT}"
        else:
            stash_style = f"bold {_DARK_FG} on {STASH_ACCENT}"
    elif surface == "trash":
        if hover == "stash":
            stash_style = f"bold {_HOVER_FG} on {_SECONDARY_BG}"
        else:
            stash_style = f"bold {STASH_ACCENT} on {_SECONDARY_BG}"
    else:
        if hover == "stash":
            stash_style = _HOVER_FG
        else:
            stash_style = _FLAT_FG

    if surface == "trash":
        if hover == "trash":
            trash_style: str | None = f"bold {_HOVER_FG} on {TRASH_ACCENT}"
        else:
            trash_style = f"bold {_DARK_FG} on {TRASH_ACCENT}"
        trash_count_style: str | None = trash_style
    elif surface == "history":
        if hover == "trash":
            trash_style = _HOVER_FG
        else:
            trash_style = _FLAT_FG
        trash_count_style = trash_style
    else:
        # Inactive trash secondary on the Stash surface.
        if hover == "trash":
            trash_style = f"{_HOVER_FG} on {_SECONDARY_BG}"
            trash_count_style = trash_style
        elif trash_limit == 0:
            trash_style = f"{_SECONDARY_FG} on {_SECONDARY_BG}"
            trash_count_style = f"{_MUTED_FG} on {_SECONDARY_BG}"
        elif trash_count == 0:
            trash_style = f"{_SECONDARY_FG} on {_SECONDARY_BG}"
            trash_count_style = trash_style
        elif _is_trash_full(trash_count, trash_limit):
            trash_style = f"{_SECONDARY_FG} on {_SECONDARY_BG}"
            trash_count_style = f"bold {_FULL_RED} on {_SECONDARY_BG}"
        else:
            trash_style = f"{_SECONDARY_FG} on {_SECONDARY_BG}"
            trash_count_style = f"{TRASH_ACCENT} on {_SECONDARY_BG}"

    if surface == "history":
        if hover == "history":
            history_style: str | None = f"bold {_HOVER_FG} on {HISTORY_ACCENT}"
        else:
            history_style = f"bold {_DARK_FG} on {HISTORY_ACCENT}"
    else:
        if hover == "history":
            history_style = _HOVER_FG
        else:
            history_style = _FLAT_FG

    # -- render segments -----------------------------------------------------
    # Stash segment: " <label> " with a single style.
    start = column
    _append(f" {stash_label} ", stash_style)
    hits.append((start, column, "stash"))

    if tier == "micro":
        _append_spaces(1)

    # Trash segment: split icon/badge so the count carries its own color.
    # The label is either icon-alone, "icon off", "icon N", or the active
    # "icon Trash N/LIMIT" / "icon Trash off" / micro "icon N/LIMIT".
    start = column
    if surface == "trash" or surface == "history":
        # Single style for the whole active/flat segment.
        _append(f" {trash_label} ", trash_style)
    else:
        # Inactive secondary: leading space + icon share the base style,
        # the trailing count/off badge carries its own foreground.
        if trash_limit == 0:
            # f"{TRASH_GLYPH} off" -> icon + " off".
            _append(f" {TRASH_GLYPH} ", trash_style)
            _append("off", trash_count_style)
            _append(" ", trash_style)
        elif trash_count == 0:
            _append(f" {trash_label} ", trash_style)
        else:
            # f"{TRASH_GLYPH} {N}" -> icon + count.
            _append(f" {TRASH_GLYPH} ", trash_style)
            _append(str(trash_count), trash_count_style)
            _append(" ", trash_style)
    hits.append((start, column, "trash"))

    if tier == "micro":
        _append_spaces(1)
    else:
        _append_spaces(3)

    start = column
    _append(f" {history_label} ", history_style)
    hits.append((start, column, "history"))

    # -- hints (full tier only, right-aligned) --------------------------------
    if tier == "full":
        hints_len = _hints_len(surface)
        segments_len = column
        if width <= 0:
            gap = 2
        else:
            gap = max(2, width - segments_len - hints_len)
        _append_spaces(gap)
        for fragment, style in _hints_parts(surface):
            _append(fragment, style or None)

    return _PromptsTabBarLayout(text=text, tier=tier, hits=tuple(hits))


class PromptsTabBar(Widget):
    """Clickable split-button tab bar for the Prompts overlay."""

    class SurfaceClicked(Message):
        """Posted when a non-active bar segment is clicked."""

        def __init__(self, surface: str) -> None:
            super().__init__()
            self.surface = surface

    def __init__(
        self,
        state: PromptsTabBarState,
        *children: Widget,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
        disabled: bool = False,
        markup: bool = True,
    ) -> None:
        super().__init__(
            *children,
            name=name,
            id=id,
            classes=classes,
            disabled=disabled,
            markup=markup,
        )
        self._state = state
        self._hover: str | None = None
        self._hits: tuple[tuple[int, int, str], ...] = ()

    def set_state(self, state: PromptsTabBarState) -> None:
        """Push new counts/surface and refresh."""
        self._state = state
        self.refresh()

    @property
    def state(self) -> PromptsTabBarState:
        """Return the last state pushed via :meth:`set_state`."""
        return self._state

    def render(self) -> Text:
        """Render the widest tier fitting the laid-out width."""
        try:
            width = int(self.size.width)
        except Exception:
            width = 0
        layout = _layout_prompts_tab_bar(self._state, width, hover=self._hover)
        self._hits = layout.hits
        return layout.text

    def _surface_at(self, x: int) -> str | None:
        for start, end, surface in self._hits:
            if start <= x < end:
                return surface
        return None

    async def on_click(self, event: events.Click) -> None:
        """Post :class:`SurfaceClicked` for a non-active segment."""
        surface = self._surface_at(event.x)
        if surface is not None and surface != self._state.surface:
            self.post_message(PromptsTabBar.SurfaceClicked(surface))

    async def on_mouse_move(self, event: events.MouseMove) -> None:
        """Brighten the hovered segment and show its tooltip."""
        surface = self._surface_at(event.x)
        if surface != self._hover:
            self._hover = surface
            if surface is None:
                self.tooltip = None
            else:
                self.tooltip = _tooltip_for_surface(
                    surface,
                    stash_count=self._state.stash_count,
                    trash_count=self._state.trash_count,
                    trash_limit=self._state.trash_limit,
                )
            self.refresh()

    async def on_leave(self, _event: events.Leave) -> None:
        """Clear hover and tooltip once the pointer leaves the bar."""
        if self._hover is not None or self.tooltip:
            self._hover = None
            self.tooltip = None
            self.refresh()


__all__ = [
    "HISTORY_ACCENT",
    "HISTORY_GLYPH",
    "STASH_ACCENT",
    "STASH_GLYPH",
    "PromptsTabBar",
    "_PromptsTabBarLayout",
    "PromptsTabBarState",
    "TRASH_ACCENT",
    "_layout_prompts_tab_bar",
    "_tooltip_for_surface",
]
