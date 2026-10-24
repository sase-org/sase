"""Textual-free number, duration, and bar primitives for Statistics."""

from __future__ import annotations

import math
from collections.abc import Sequence

from rich.text import Text

from sase.telemetry.render import format_duration as _format_duration

_BAR_FILL = "#FF87D7"
_BAR_EMPTY = "#444444"
_UNICODE_FILL = "█"
_UNICODE_EMPTY = "░"
_ASCII_FILL = "#"
_ASCII_EMPTY = "."
_STACKED_UNICODE = ("█", "▓", "▒", "░")
_STACKED_ASCII = ("#", "%", "=", "-")
_FINE_UNICODE = ("", "▏", "▎", "▍", "▌", "▋", "▊", "▉")


def percent(value: float) -> str:
    """Format ``value`` in ``0.0–1.0`` as a one-decimal percentage."""
    return f"{value * 100:.1f}%"


def share_bar(
    value: float,
    maximum: float,
    *,
    width: int = 14,
    fill_style: str = _BAR_FILL,
    empty_style: str = _BAR_EMPTY,
    ascii_fallback: bool = False,
) -> Text:
    """Render a single filled track of ``width`` cells.

    The default glyphs and colors match the Statistics pane's previous
    in-mixin bars so existing views stay byte-identical.
    """
    ratio = min(1.0, max(0.0, float(value) / float(maximum))) if maximum else 0.0
    filled = round(ratio * width)
    fill_glyph = _ASCII_FILL if ascii_fallback else _UNICODE_FILL
    empty_glyph = _ASCII_EMPTY if ascii_fallback else _UNICODE_EMPTY
    text = Text()
    text.append(fill_glyph * filled, style=fill_style)
    text.append(empty_glyph * (width - filled), style=empty_style)
    return text


def fine_bar(
    value: float,
    maximum: float,
    *,
    width: int,
    style: str,
    ascii_fallback: bool = False,
) -> Text:
    """Render an untracked bar, using eighth-cell glyphs when Unicode is available."""
    width = max(0, width)
    if value <= 0 or width == 0:
        return Text(" " * width)
    ratio = min(1.0, float(value) / float(maximum)) if maximum > 0 else 1.0
    text = Text()
    if ascii_fallback:
        cells = ratio * width
        full = int(cells)
        partial = cells > full
        if full == 0:
            partial = True
        glyphs = "#" * full + ("|" if partial and full < width else "")
        text.append(glyphs, style=style)
        text.append(" " * max(0, width - len(glyphs)))
        return text

    eighths = round(ratio * width * 8)
    if eighths == 0:
        eighths = 1
    eighths = min(width * 8, max(0, eighths))
    full_eighths, partial_eighths = divmod(eighths, 8)
    glyphs = "█" * full_eighths + _FINE_UNICODE[partial_eighths]
    text.append(glyphs, style=style)
    text.append(" " * max(0, width - full_eighths - bool(partial_eighths)))
    return text


def stacked_bar(
    parts: Sequence[tuple[float, str]],
    *,
    width: int = 24,
    ascii_fallback: bool = False,
) -> Text:
    """Render a stacked share bar of ``width`` cells.

    ``parts`` is ``(share, style)`` where each share is a fraction of 1.0.
    Integer cell counts use the largest-remainder method so they sum to
    ``width`` when the shares themselves sum to 1. Remaining width is the
    unfilled track.
    """
    glyphs = _STACKED_ASCII if ascii_fallback else _STACKED_UNICODE
    empty_glyph = _ASCII_EMPTY if ascii_fallback else _UNICODE_EMPTY
    shares = [max(0.0, float(share)) for share, _style in parts]
    total = sum(shares)
    if width <= 0 or total <= 0:
        text = Text()
        text.append(empty_glyph * max(0, width), style=_BAR_EMPTY)
        return text
    if total > 1.0:
        shares = [share / total for share in shares]
    raw = [share * width for share in shares]
    counts = [int(value) for value in raw]
    remainder = min(width, int(round(sum(raw)))) - sum(counts)
    leftovers = sorted(
        range(len(raw)),
        key=lambda index: (raw[index] - counts[index], -index),
        reverse=True,
    )
    if remainder > 0:
        for index in leftovers[:remainder]:
            counts[index] += 1
    text = Text()
    for index, (_share, style) in enumerate(parts):
        count = counts[index]
        if count:
            glyph = glyphs[index % len(glyphs)]
            text.append(glyph * count, style=style)
    filled = sum(counts)
    if filled < width:
        text.append(empty_glyph * (width - filled), style=_BAR_EMPTY)
    return text


def format_count(value: float) -> str:
    """Format a whole-number count with thousands separators."""
    if not math.isfinite(value):
        return "—"
    return f"{int(round(value)):,}"


def format_compact(value: float) -> str:
    """Format a magnitude as a compact count such as ``3.1M``."""
    if not math.isfinite(value):
        return "—"
    if value == 0:
        return "0"
    sign = "-" if value < 0 else ""
    scaled = abs(value)
    suffixes = ("", "k", "M", "B", "T")
    suffix_index = 0
    while scaled >= 1000 and suffix_index < len(suffixes) - 1:
        scaled /= 1000
        suffix_index += 1
    if suffix_index == 0:
        if scaled < 0.01:
            return f"{value:.2e}"
        if scaled < 10:
            return f"{sign}{scaled:.2f}".rstrip("0").rstrip(".")
        if scaled < 100:
            return f"{sign}{scaled:.1f}".rstrip("0").rstrip(".")
        return f"{sign}{scaled:.0f}"
    precision = 1 if scaled < 10 else 0
    return f"{sign}{scaled:.{precision}f}{suffixes[suffix_index]}"


def format_duration(seconds: float) -> str:
    """Return a compact duration matching the telemetry formatter."""
    return _format_duration(seconds)


def format_relative_age(seconds: float) -> str:
    """Format an elapsed span as a friendly age such as ``4 min ago``."""
    age = max(0.0, seconds)
    if age < 60:
        return "just now"
    minutes = int(age // 60)
    if minutes < 60:
        return f"{minutes} min ago"
    hours = int(minutes // 60)
    if hours < 24:
        return f"{hours} h ago"
    days = int(hours // 24)
    if days < 45:
        return f"{days} d ago"
    months = int(days / 30.4375)
    if months < 18:
        return f"{months} mo ago"
    years = max(1, int(round(months / 12)))
    return f"{years} yr ago"


__all__ = [
    "format_compact",
    "format_count",
    "format_duration",
    "format_relative_age",
    "fine_bar",
    "percent",
    "share_bar",
    "stacked_bar",
]
