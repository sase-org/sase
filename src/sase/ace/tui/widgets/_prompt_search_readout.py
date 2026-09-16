"""Pure formatting helpers for prompt search match-count readouts."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
import unicodedata

from rich.cells import cell_len
from rich.style import Style
from rich.text import Text
from textual.color import Color

from sase.ace.tui.widgets._vim_search import SearchDirection

_ACCENT_FALLBACK = "#6B4FBB"
_WARNING_FALLBACK = "#FFA62B"
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


def _search_readout_colors(theme: object | None) -> tuple[Style, Style, Style]:
    """Return query, sigil, and count styles for the current app theme.

    The roles mirror ``SearchHighlightMixin``'s ``search.match`` (accent) and
    ``search.current`` (warning) overlay styles so palette changes stay paired.
    """
    accent = _theme_color(theme, "accent", _ACCENT_FALLBACK).darken(0.25)
    warning = _theme_color(theme, "warning", _WARNING_FALLBACK)

    query_foreground = accent.get_contrast_text(1.0)
    count_foreground = warning.get_contrast_text(1.0)
    query_style = Style(color=query_foreground.hex, bgcolor=accent.hex)
    sigil_style = Style(color=query_foreground.hex, bgcolor=accent.hex, bold=True)
    count_style = Style(
        color=count_foreground.hex,
        bgcolor=warning.hex,
        bold=True,
    )
    return query_style, sigil_style, count_style


def format_search_count_segment(
    ordinal: int | None,
    total: int,
    *,
    theme: object | None,
) -> Text:
    """Format the count-only segment, e.g. ``2/3``."""
    if ordinal is None or total <= 0:
        return Text(no_wrap=True)
    _query_style, _sigil_style, count_style = _search_readout_colors(theme)
    return Text(f"{ordinal}/{total}", style=count_style, no_wrap=True)


def format_search_readout(
    readout: PromptSearchReadout,
    *,
    theme: object | None,
    include_query: bool = True,
) -> Text:
    """Format a full or count-only prompt search readout."""
    count = format_search_count_segment(
        readout.ordinal,
        readout.total,
        theme=theme,
    )
    if not include_query:
        return count
    query_style, sigil_style, count_style = _search_readout_colors(theme)
    result = Text(no_wrap=True)
    result.append(_readout_sigil(readout.direction, readout.whole_word), sigil_style)
    result.append(_display_query(readout.query), query_style)
    result.append(" ", query_style)
    if count.plain:
        result.append(" ", count_style)
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


def _theme_color(theme: object | None, attr: str, fallback: str) -> Color:
    if theme is not None:
        value = getattr(theme, attr, None)
        if isinstance(value, Color):
            return value
        if value:
            try:
                return Color.parse(str(value))
            except Exception:
                pass
    return Color.parse(fallback)
