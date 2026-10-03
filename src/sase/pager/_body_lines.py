"""Line index and styled line extraction for the virtual pager body.

Textual-free. The layout (``_body_layout``) keeps only integer arrays per
section; when it needs a line's styled content — counting wrapped rows at
layout time, painting a row at paint time — it slices the section's labeled
:class:`~rich.text.Text` here in O(log spans + spans touching the line).

Slicing matches :meth:`rich.text.Text.split` exactly (same plain, same
clipped spans, same base attributes); the parity suite proves it on fixed
random inputs.
"""

from __future__ import annotations

from array import array
from dataclasses import dataclass
from typing import Any

from rich.console import Console
from rich.text import Text


def logical_line_starts(plain: str) -> array:
    """Return the start offset of each logical line of *plain*.

    Mirrors the line split :func:`sase.pager._gutter.apply_gutter` lays out:
    a phantom trailing newline is dropped (``"a\\n"`` is one line) while
    ``""`` has zero lines and ``"\\n"`` has one empty line.
    """
    if not plain:
        return array("Q")
    pieces = plain.split("\n")
    if plain.endswith("\n"):
        pieces.pop()
    starts = array("Q")
    offset = 0
    for piece in pieces:
        starts.append(offset)
        offset += len(piece) + 1
    return starts


def logical_line_end(starts: array, index: int, plain: str) -> int:
    """Return the exclusive end offset of logical line *index*.

    Middle lines exclude their terminating newline; the last line also
    drops the phantom trailing newline, so ``"three\\n"`` slices as
    ``"three"`` exactly like :meth:`rich.text.Text.split` yields it.
    """
    if index + 1 < len(starts):
        return starts[index + 1] - 1
    if plain.endswith("\n"):
        return len(plain) - 1
    return len(plain)


@dataclass(frozen=True, slots=True)
class SpanIndex:
    """Centered interval tree over one source text's spans.

    Each node holds the spans containing its center; the left subtree
    holds spans ending at or before the center and the right subtree
    holds spans starting after it. A line query visits O(log n) nodes
    plus the spans touching the line.
    """

    center: int
    middle: tuple[tuple[int, int, Any, int], ...]
    left: SpanIndex | None
    right: SpanIndex | None


def build_span_index(source: Text) -> SpanIndex:
    """Index ``source.spans`` once so every line slice is sublinear."""
    items = [
        (span.start, span.end, span.style, position)
        for position, span in enumerate(source.spans)
    ]
    return _build_span_index(items)


def _build_span_index(
    items: list[tuple[int, int, Any, int]],
) -> SpanIndex:
    if not items:
        return SpanIndex(center=0, middle=(), left=None, right=None)
    endpoints = sorted({point for item in items for point in (item[0], item[1])})
    center = endpoints[len(endpoints) // 2]
    # Inclusive middle always claims the spans touching the center
    # endpoint itself, so both subtrees strictly shrink and terminate.
    left_items = [item for item in items if item[1] < center]
    right_items = [item for item in items if item[0] > center]
    return SpanIndex(
        center=center,
        middle=tuple(item for item in items if item[0] <= center <= item[1]),
        left=_build_span_index(left_items) if left_items else None,
        right=_build_span_index(right_items) if right_items else None,
    )


def _query_span_index(
    index: SpanIndex | None,
    start: int,
    end: int,
    out: list[tuple[int, int, Any, int]],
) -> None:
    if index is None:
        return
    for item in index.middle:
        if item[0] < end and item[1] > start:
            out.append(item)
    if start < index.center:
        _query_span_index(index.left, start, end, out)
    if end > index.center:
        _query_span_index(index.right, start, end, out)


def slice_styled_line(
    source: Text,
    start: int,
    end: int,
    *,
    index: SpanIndex,
) -> Text:
    """Return ``source.plain[start:end]`` with exactly the overlapping spans.

    Spans crossing the boundaries are clipped, matching what
    :meth:`rich.text.Text.split` produces for the same line — including
    the original span order, which style resolution depends on.
    """
    out = Text(source.plain[start:end])
    out.style = source.style
    out.justify = source.justify
    out.overflow = source.overflow
    out.no_wrap = source.no_wrap
    out.tab_size = source.tab_size
    matched: list[tuple[int, int, Any, int]] = []
    _query_span_index(index, start, end, matched)
    matched.sort(key=lambda item: item[3])
    for span_start, span_end, style, _original in matched:
        out.stylize(style, max(span_start, start) - start, min(span_end, end) - start)
    return out


def make_wrap_console(width: int) -> Console:
    """Build a wrap console with exactly ``apply_gutter``'s parameters."""
    return Console(
        width=max(width, 1),
        color_system=None,
        force_terminal=False,
        highlight=False,
        markup=False,
        emoji=False,
    )


def wrap_line_pieces(line: Text, width: int, console: Console) -> tuple[Text, ...]:
    """Wrap one logical line with exactly ``apply_gutter``'s semantics."""
    if not line.plain:
        return (Text(),)
    copied = line.copy()
    copied.overflow = "fold"
    copied.no_wrap = False
    wrapped = tuple(copied.wrap(console, width, overflow="fold"))
    return wrapped if wrapped else (Text(),)


__all__ = [
    "SpanIndex",
    "build_span_index",
    "logical_line_end",
    "logical_line_starts",
    "make_wrap_console",
    "slice_styled_line",
    "wrap_line_pieces",
]
