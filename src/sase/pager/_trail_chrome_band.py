"""Renderers for the active trail band (orientation, compact, and path rows)."""

from __future__ import annotations

from typing import Literal

from rich.cells import cell_len
from rich.text import Text

from sase.pager._trail_chrome_model import MUTED_STYLE as _MUTED_STYLE
from sase.pager._trail_chrome_model import PagerTrailSnapshot
from sase.pager._trail_chrome_path import render_current_only as _render_current_only
from sase.pager._trail_chrome_path import (
    render_trail_path_row as _render_trail_path_row,
)
from sase.pager._trail_chrome_text import fit_text as _fit_text


def trail_band_row_count(*, visible: bool, screen_height: int) -> int:
    """Return the fixed row count for the active band layout."""

    if not visible:
        return 0
    return 1 if screen_height <= 12 else 2


def render_trail_band(
    snapshot: PagerTrailSnapshot,
    *,
    width: int,
    screen_height: int,
) -> Text:
    """Render the active breadcrumb band, clipped to *width* cells per row."""

    width = max(0, int(width))
    compact = (
        trail_band_row_count(
            visible=snapshot.visible,
            screen_height=screen_height,
        )
        == 1
    )
    if compact:
        return _render_compact_trail_row(snapshot, width=width)
    text = Text(no_wrap=True, overflow="crop")
    text.append_text(_render_trail_orientation_row(snapshot, width=width))
    text.append("\n")
    text.append_text(_render_trail_path_row(snapshot, width=width))
    return text


def _render_trail_orientation_row(
    snapshot: PagerTrailSnapshot,
    *,
    width: int,
) -> Text:
    """Render the upper orientation row with position and direction counts."""

    width = max(0, int(width))
    if width == 0:
        return Text(no_wrap=True, overflow="crop")

    help_options = ("? trail", "?", "")
    direction_options = (
        _direction_text(snapshot, mode="full"),
        _direction_text(snapshot, mode="compact"),
        Text(),
    )
    for direction in direction_options:
        for help_text in help_options:
            left = _orientation_left(snapshot, direction)
            right = Text(help_text, style="bold") if help_text else Text()
            row = join_left_right(left, right, width=width)
            if row is not None:
                return row

    fallback = _orientation_left(snapshot, Text("? ", style="bold"))
    return _plain_fallback(fallback.plain, width)


def _render_compact_trail_row(
    snapshot: PagerTrailSnapshot,
    *,
    width: int,
) -> Text:
    """Render the short-height one-line trail layout."""

    width = max(0, int(width))
    if width == 0:
        return Text(no_wrap=True, overflow="crop")

    current = _render_current_only(snapshot.current, width=width)
    direction = _compact_inline_direction(snapshot, current)
    directionless = current
    for middle in (direction, directionless):
        for help_text in ("? trail", "?", ""):
            left = _orientation_left(snapshot, Text(" "))
            if middle.plain:
                left.append_text(middle)
            right = Text(help_text, style="bold") if help_text else Text()
            row = join_left_right(left, right, width=width)
            if row is not None:
                return row

    return _render_current_only(snapshot.current, width=width)


def _orientation_left(snapshot: PagerTrailSnapshot, suffix: Text) -> Text:
    current = snapshot.current
    text = Text(no_wrap=True, overflow="crop")
    text.append("TRAIL", style=f"bold {current.accent}")
    text.append(" ")
    text.append(f"{snapshot.position}/{snapshot.total}", style="bold reverse")
    text.append_text(suffix)
    return text


def _direction_text(
    snapshot: PagerTrailSnapshot,
    *,
    mode: Literal["full", "compact"],
) -> Text:
    parts: list[tuple[str, str]] = []
    if snapshot.back_count:
        if mode == "full":
            parts.append(("^O", f" back {snapshot.back_count}"))
        else:
            parts.append(("‹", str(snapshot.back_count)))
    if snapshot.forward_count:
        if mode == "full":
            parts.append(("<tab>", f" forward {snapshot.forward_count}"))
        else:
            parts.append((str(snapshot.forward_count), "›"))
    if not parts:
        return Text()

    text = Text("    " if mode == "full" else "  ", no_wrap=True, overflow="crop")
    if mode == "compact":
        text.append("‹", style="bold")
        if snapshot.back_count:
            text.append(str(snapshot.back_count))
        if snapshot.back_count and snapshot.forward_count:
            text.append(" ")
        if snapshot.forward_count:
            text.append(str(snapshot.forward_count))
        text.append("›", style="bold")
        return text

    for index, (key, label) in enumerate(parts):
        if index:
            text.append(" · ", style=_MUTED_STYLE)
        text.append(key, style="bold")
        text.append(label)
    return text


def _compact_inline_direction(snapshot: PagerTrailSnapshot, current: Text) -> Text:
    text = Text(no_wrap=True, overflow="crop")
    if snapshot.back_count:
        text.append(f"‹{snapshot.back_count} ", style="bold")
    text.append_text(current)
    if snapshot.forward_count:
        text.append(f" {snapshot.forward_count}›", style="bold")
    return text


def join_left_right(left: Text, right: Text, *, width: int) -> Text | None:
    left_width = cell_len(left.plain)
    right_width = cell_len(right.plain)
    if not right.plain:
        if left_width <= width:
            return left
        return None
    if left_width + right_width > width:
        return None
    row = Text(no_wrap=True, overflow="crop")
    row.append_text(left)
    row.append(" " * max(width - left_width - right_width, 0))
    row.append_text(right)
    return row


def _plain_fallback(plain: str, width: int) -> Text:
    return Text(_fit_text(plain, width), no_wrap=True, overflow="crop")
