"""Pure formatting helpers for prompt search match-count readouts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
import unicodedata

from rich.cells import cell_len
from rich.color import Color as RichColor
from rich.color import ColorSystem
from rich.style import Style
from rich.text import Text
from textual.color import Color

from sase.ace.tui.widgets._vim_search import SearchDirection

_FALLBACK_COLORS: dict[str, str] = {
    "surface": "#1E1E1E",
    "foreground": "#E0E0E0",
    "background": "#121212",
    "accent": "#6B4FBB",
    "warning": "#FFA62B",
}
_THEME_VAR_NAMES = ("surface", "foreground", "background", "accent", "warning")
_QUERY_CHIP_RAISE = 0.20
_INK_MIN_CONTRAST = 4.5
_SIGIL_MIN_CONTRAST = 3.0
_NEUTRAL_INKS = ("#121212", "#FAFAFA")
# Base16 terminal palettes repurpose these xterm-256 slots as accent colors.
_BASE16_REPURPOSED_INDICES = range(16, 22)
_ELLIPSIS = "…"


@dataclass(frozen=True)
class PromptSearchReadout:
    """Search match-count state derived from a pane's current highlights."""

    query: str
    direction: SearchDirection
    whole_word: bool
    ordinal: int | None
    total: int
    pane_text: str = field(compare=False, repr=False)


@dataclass(frozen=True)
class _SearchReadoutPalette:
    query: Style
    sigil: Style
    ordinal: Style
    total: Style


def _readout_sigil(direction: SearchDirection, whole_word: bool) -> str:
    """Return the visible search sigil for *direction* and whole-word mode."""
    if whole_word:
        return "*" if direction == "forward" else "#"
    return "/" if direction == "forward" else "?"


def _display_query(query: str, max_cells: int = 24) -> str:
    """Sanitize and end-elide *query* to at most *max_cells* terminal cells."""
    sanitized = "".join(_display_query_char(char) for char in query)
    if max_cells <= 0:
        return ""
    if cell_len(sanitized) <= max_cells:
        return sanitized
    if max_cells <= cell_len(_ELLIPSIS):
        return _ELLIPSIS[:max_cells]

    budget = max_cells - cell_len(_ELLIPSIS)
    used = 0
    kept: list[str] = []
    for char in sanitized:
        width = max(0, cell_len(char))
        if used + width > budget:
            break
        kept.append(char)
        used += width
    return f"{''.join(kept)}{_ELLIPSIS}"


def stack_match_position(
    counts_by_pane: Sequence[int],
    origin_position: int,
    local_index: int | None,
) -> tuple[int | None, int]:
    """Convert a pane-local match index into a 1-based stack-global position."""
    total = sum(max(0, count) for count in counts_by_pane)
    if (
        local_index is None
        or origin_position < 0
        or origin_position >= len(counts_by_pane)
        or local_index < 0
        or local_index >= counts_by_pane[origin_position]
    ):
        return None, total
    prior = sum(max(0, count) for count in counts_by_pane[:origin_position])
    return prior + local_index + 1, total


def _search_readout_palette(
    variables: Mapping[str, str] | None,
) -> _SearchReadoutPalette:
    """Return prompt-search readout styles for resolved app theme variables.

    The roles mirror ``SearchHighlightMixin``'s ``search.match`` (accent) and
    ``search.current`` (warning) overlay styles so palette changes stay paired.
    """
    return _search_readout_palette_cached(_theme_var_cache_key(variables))


@lru_cache(maxsize=8)
def _search_readout_palette_cached(
    raw_values: tuple[str | None, ...],
) -> _SearchReadoutPalette:
    variables = {
        name: value
        for name, value in zip(_THEME_VAR_NAMES, raw_values, strict=True)
        if value is not None
    }
    surface = _theme_var(variables, "surface")
    foreground = _theme_var(variables, "foreground")
    accent = _theme_var(variables, "accent")
    warning = _theme_var(variables, "warning")

    query_bg = _terminal_safe(surface.blend(foreground, _QUERY_CHIP_RAISE))
    query_fg = _ink_for(query_bg, variables)
    sigil_fg = _terminal_safe(_ensure_contrast(accent, query_bg, _SIGIL_MIN_CONTRAST))
    count_bg = _terminal_safe(warning)
    count_fg = _ink_for(count_bg, variables)

    return _SearchReadoutPalette(
        query=Style(color=query_fg.hex, bgcolor=query_bg.hex, bold=True),
        sigil=Style(color=sigil_fg.hex, bgcolor=query_bg.hex, bold=True),
        ordinal=Style(color=count_fg.hex, bgcolor=count_bg.hex, bold=True),
        total=Style(color=count_fg.hex, bgcolor=count_bg.hex),
    )


def _theme_var_cache_key(
    variables: Mapping[str, str] | None,
) -> tuple[str | None, ...]:
    if variables is None:
        return tuple(None for _name in _THEME_VAR_NAMES)
    return tuple(
        None if variables.get(name) is None else str(variables.get(name))
        for name in _THEME_VAR_NAMES
    )


def _theme_var(variables: Mapping[str, str] | None, name: str) -> Color:
    fallback = _FALLBACK_COLORS[name]
    if variables is None:
        return Color.parse(fallback)
    value = variables.get(name)
    if value:
        try:
            color = Color.parse(str(value))
        except Exception:
            color = None
        if color is not None and color.a >= 1 and color.ansi is None:
            return color
    return Color.parse(fallback)


def _relative_luminance(color: Color) -> float:
    def channel(value: int) -> float:
        normalized = value / 255
        if normalized <= 0.03928:
            return normalized / 12.92
        return ((normalized + 0.055) / 1.055) ** 2.4

    return (
        0.2126 * channel(color.r)
        + 0.7152 * channel(color.g)
        + 0.0722 * channel(color.b)
    )


def _contrast_ratio(a: Color, b: Color) -> float:
    first = _relative_luminance(a)
    second = _relative_luminance(b)
    lighter = max(first, second)
    darker = min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def _terminal_safe(color: Color) -> Color:
    if (color.r, color.g, color.b) == (0, 0, 0):
        return Color.parse("#121212")
    if (color.r, color.g, color.b) == (255, 255, 255):
        return Color.parse("#FAFAFA")

    current = color
    for _step in range(12):
        if (
            RichColor.from_rgb(current.r, current.g, current.b)
            .downgrade(ColorSystem.EIGHT_BIT)
            .number
            not in _BASE16_REPURPOSED_INDICES
        ):
            return current
        current = current.lighten(0.03)
    return current


def _ink_for(bg: Color, variables: Mapping[str, str] | None) -> Color:
    candidates = [
        _theme_var(variables, "foreground"),
        _theme_var(variables, "background"),
    ]
    best = max(candidates, key=lambda color: _contrast_ratio(color, bg))
    if _contrast_ratio(best, bg) < _INK_MIN_CONTRAST:
        candidates.extend(Color.parse(hex_color) for hex_color in _NEUTRAL_INKS)
        best = max(candidates, key=lambda color: _contrast_ratio(color, bg))
    return _terminal_safe(best)


def _ensure_contrast(color: Color, bg: Color, minimum: float) -> Color:
    current = color
    adjust = Color.lighten if _relative_luminance(bg) < 0.18 else Color.darken
    for _step in range(10):
        if _contrast_ratio(current, bg) >= minimum:
            return current
        current = adjust(current, 0.06)
    return current


def format_search_count_segment(
    ordinal: int | None,
    total: int,
    *,
    variables: Mapping[str, str] | None,
) -> Text:
    """Format the count-only segment, e.g. `` 2/3 ``."""
    if ordinal is None or total <= 0:
        return Text(no_wrap=True)
    palette = _search_readout_palette(variables)
    result = Text(no_wrap=True)
    result.append(f" {ordinal}", palette.ordinal)
    result.append(f"/{total} ", palette.total)
    return result


def format_search_readout(
    readout: PromptSearchReadout,
    *,
    variables: Mapping[str, str] | None,
    include_query: bool = True,
) -> Text:
    """Format a full or count-only prompt search readout."""
    count = format_search_count_segment(
        readout.ordinal,
        readout.total,
        variables=variables,
    )
    if not include_query:
        return count
    palette = _search_readout_palette(variables)
    result = Text(no_wrap=True)
    result.append(" ", palette.query)
    result.append(_readout_sigil(readout.direction, readout.whole_word), palette.sigil)
    result.append(f"{_display_query(readout.query)} ", palette.query)
    if count.plain:
        result.append_text(count)
    return result


def _display_query_char(char: str) -> str:
    if char == "\n":
        return "↵"
    if char == "\t":
        return "⇥"
    if unicodedata.category(char)[0] == "C":
        return "·"
    return char
