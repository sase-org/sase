"""Pure fitting of a highlighted xprompt into the collapsed agent-header preview.

The collapsed :class:`AgentHeaderPanel` shows a dense preview of the selected
agent's xprompt below its two chip rows. This module turns the highlighted,
humanized xprompt ``Text`` into that preview: it reflows the source
Markdown-style (soft line breaks join with a space, hard breaks become a dim
``¶``), wraps the result to a width, and keeps at most a row budget of rows
behind a quote bar. :func:`preview_card` then sets the fitted rows apart from
the metadata chips as a card: an ``XPROMPT`` tab row above rows padded to a
uniform Monokai surface. It touches no widget and does no I/O.
"""

from __future__ import annotations

import io
import math
import re
import sys
from bisect import bisect_right
from dataclasses import dataclass

from rich.cells import cell_len
from rich.console import Console
from rich.text import Text

PREVIEW_BAR_GLYPH = "▎"
PREVIEW_BAR_STYLE = "#AF87FF"
PREVIEW_BREAK_GLYPH = "¶"
PREVIEW_DIM_STYLE = "dim"
# Must match the Monokai surface ``highlight_prompt_text`` paints under tokens.
PREVIEW_CARD_STYLE = "on #272822"
PREVIEW_TAB_LABEL = "XPROMPT"
PREVIEW_TAB_LABEL_STYLE = "bold #AF87FF"
PREVIEW_TAB_ROWS = 1

_ELLIPSIS = "…"
_GUTTER = f"{PREVIEW_BAR_GLYPH} "
_GUTTER_CELLS = 2
_PENDING_GLYPH = "⋯"
_PENDING_GLYPH_STYLE = "dim"
# Below this many cells rows would degenerate (a wide glyph may not fit at
# all), so narrower requests are widened rather than crashing the wrap.
_MIN_WIDTH = 6
_TAB_SIZE = 4
_MIN_PREFIX_CHARS = 512
# Reserved by the header chrome: two border rows, two chip rows, and the
# XPROMPT tab row.
_CHROME_ROWS = 4 + PREVIEW_TAB_ROWS
_NEVER = sys.maxsize

_WRAP_CONSOLE = Console(file=io.StringIO(), width=80, color_system=None)

_BLOCK_START = re.compile(r"[-*+] |\d{1,9}[.)] |#{1,6} |> |\|")
_THEMATIC_BREAK = re.compile(r"(?:-\s*){3,}|(?:\*\s*){3,}|(?:_\s*){3,}")
_WORD = re.compile(r"\S+")


@dataclass(frozen=True, slots=True)
class XpromptPreviewFit:
    """A fitted preview: quote-barred rows plus what was left out."""

    text: Text
    rows: int
    truncated: bool
    hidden_lines: int


def preview_row_budget(column_rows: int, share: float) -> int:
    """Return how many preview rows the collapsed header may show.

    The collapsed header is capped at ``floor(column_rows * share)`` rows in
    total; the preview gets that cap minus the border, chip, and ``XPROMPT``
    tab rows, but at least one row whenever ``share`` is positive. A
    non-positive ``share`` or ``column_rows`` turns the preview off (``0``).
    """
    if share <= 0 or column_rows <= 0:
        return 0
    cap = math.floor(column_rows * share + 1e-9)
    return max(1, cap - _CHROME_ROWS)


def fit_xprompt_preview(
    source: Text, *, width: int, max_rows: int
) -> XpromptPreviewFit:
    """Reflow ``source`` and fit it into at most ``max_rows`` rows.

    Every row starts with the styled ``▎ `` gutter and is at most ``width``
    cells wide. The fit shows ``min(rows needed, max_rows)`` rows. On
    overflow the last row ends in ``…`` right after the last whole word that
    fits and ``hidden_lines`` counts the source lines not fully shown.
    ``source`` is never mutated, and only a prefix large enough to fill the
    budget is reflowed, so huge sources stay cheap.
    """
    if max_rows <= 0:
        return _empty_fit()
    plain = source.plain
    last = len(plain.rstrip())
    if last == 0:
        return _empty_fit()
    first = len(plain) - len(plain.lstrip())
    start = plain.rfind("\n", 0, first) + 1
    total_lines = plain.count("\n", start, last) + 1
    content_width = max(width, _MIN_WIDTH) - _GUTTER_CELLS

    target = max(_MIN_PREFIX_CHARS, (max_rows + 2) * content_width * 2)
    while True:
        cut = plain.find("\n", start + target, last)
        complete = cut < 0
        if complete:
            cut = last
        flow, line_ends = _reflow(source[start:cut])
        rows = _wrap_rows(flow, content_width)
        # Rows before the final one are settled once a later row exists.
        if complete or len(rows) > max_rows + 1:
            break
        target *= 2

    truncated = not complete or len(rows) > max_rows
    shown = rows[:max_rows]
    hidden_lines = 0
    if truncated:
        shown_starts = _row_starts(flow.plain, shown)
        shown[-1], kept = _ellipsize(shown[-1], content_width)
        visible = bisect_right(line_ends, shown_starts[-1] + kept)
        hidden_lines = total_lines - visible
    return XpromptPreviewFit(
        text=_with_gutters(shown),
        rows=len(shown),
        truncated=truncated,
        hidden_lines=hidden_lines,
    )


def pending_preview_rows(rows: int) -> Text:
    """Return ``rows`` quote-barred placeholder rows with a dim mark on row one."""
    out = Text(no_wrap=True, overflow="ellipsis")
    for index in range(rows):
        if index:
            out.append("\n")
        out.append(_GUTTER, style=PREVIEW_BAR_STYLE)
        if index == 0:
            out.append(_PENDING_GLYPH, style=_PENDING_GLYPH_STYLE)
    return out


def preview_card(body: Text, *, width: int) -> Text:
    """Return ``body``'s rows as a card: an ``XPROMPT`` tab row, then the rows.

    Every body row is put on the card surface and padded with spaces to exactly
    ``width`` cells (widened to the minimum row width like the fit), so the
    card is a clean rectangle. The base style sits under the rows' own spans,
    so token styles win while joins, ``¶``, ``…`` and padding get the surface.
    The tab row covers only its label and is cropped, never wrapped, when the
    panel is narrower than it.
    """
    card_width = max(width, _MIN_WIDTH)
    tab = Text(style=PREVIEW_CARD_STYLE, no_wrap=True, overflow="crop")
    tab.append(PREVIEW_BAR_GLYPH, style=PREVIEW_BAR_STYLE)
    tab.append(" ")
    tab.append(PREVIEW_TAB_LABEL, style=PREVIEW_TAB_LABEL_STYLE)
    tab.append("  ")
    tab.truncate(card_width, overflow="crop")

    out = Text(no_wrap=True, overflow="ellipsis")
    out.append_text(tab)
    for line in body.split("\n", allow_blank=True):
        row = Text(style=PREVIEW_CARD_STYLE)
        row.append_text(line)
        row.append(" " * max(0, card_width - cell_len(row.plain)))
        out.append("\n")
        out.append_text(row)
    return out


def _empty_fit() -> XpromptPreviewFit:
    return XpromptPreviewFit(text=Text(), rows=0, truncated=False, hidden_lines=0)


def _with_gutters(rows: list[Text]) -> Text:
    out = Text(no_wrap=True, overflow="ellipsis")
    for index, row in enumerate(rows):
        if index:
            out.append("\n")
        out.append(_GUTTER, style=PREVIEW_BAR_STYLE)
        out.append_text(row)
    return out


def _reflow(region: Text) -> tuple[Text, list[int]]:
    """Join ``region``'s lines into one flow with dim hard-break marks.

    Returns the flow and, per source line, the flow offset at which that line
    is fully shown. Blank lines share the offset of the mark that stands for
    them; blank lines with no mark yet (the region's tail) never show.
    """
    flow = Text()
    line_ends: list[int] = []
    unmarked_blanks: list[int] = []
    hard_break_due = False
    in_fence = False
    for line in region.split("\n", allow_blank=True):
        line.expand_tabs(_TAB_SIZE)
        line = _strip_line(line)
        stripped = line.plain
        if not stripped:
            hard_break_due = True
            unmarked_blanks.append(len(line_ends))
            line_ends.append(_NEVER)
            continue
        thematic = False
        if stripped.startswith("```"):
            breaks_before = True
            after_break = True
            in_fence = not in_fence
        elif in_fence:
            breaks_before = True
            after_break = False
        else:
            thematic = _THEMATIC_BREAK.fullmatch(stripped) is not None
            breaks_before = not thematic and _BLOCK_START.match(stripped) is not None
            after_break = thematic
        if len(flow):
            flow.append(" ")
            if hard_break_due or breaks_before:
                flow.append(PREVIEW_BREAK_GLYPH, style=PREVIEW_DIM_STYLE)
                for index in unmarked_blanks:
                    line_ends[index] = len(flow)
                unmarked_blanks.clear()
                flow.append(" ")
        hard_break_due = after_break
        flow.append_text(line)
        line_ends.append(len(flow))
    return flow, line_ends


def _strip_line(line: Text) -> Text:
    """Drop trailing whitespace and leading indentation, keeping spans."""
    line.rstrip()
    plain = line.plain
    indent = len(plain) - len(plain.lstrip())
    return line[indent:] if indent else line


def _wrap_rows(flow: Text, width: int) -> list[Text]:
    """Wrap ``flow`` to ``width`` cells, folding tokens too long for a row."""
    rows = flow.wrap(_WRAP_CONSOLE, width, overflow="fold", no_wrap=False)
    kept: list[Text] = []
    for row in rows:
        row.rstrip()
        if row.plain:
            kept.append(row)
    return kept


def _row_starts(flow_plain: str, rows: list[Text]) -> list[int]:
    """Return each wrapped row's start offset within the flow.

    Wrapping only trims whitespace between rows, so a row starts at the first
    non-space character after the previous row's content.
    """
    starts: list[int] = []
    pos = 0
    size = len(flow_plain)
    for row in rows:
        while pos < size and flow_plain[pos].isspace():
            pos += 1
        starts.append(pos)
        pos += len(row.plain)
    return starts


def _ellipsize(row: Text, width: int) -> tuple[Text, int]:
    """End ``row`` in ``…`` after its last whole word that fits ``width``.

    Returns the new row and how many characters of the original it kept.
    """
    plain = row.plain
    if cell_len(plain) + 1 <= width:
        keep = len(plain)
    else:
        keep = _longest_fit(plain, width - 1)
    kept = row[:keep] if keep < len(plain) else row
    kept.append(_ELLIPSIS, style=PREVIEW_DIM_STYLE)
    return kept, keep


def _longest_fit(plain: str, budget: int) -> int:
    """Return the length of the longest whole-word prefix within ``budget``.

    Falls back to cutting inside the first token when not even one word fits.
    """
    for match in reversed(list(_WORD.finditer(plain))):
        if cell_len(plain[: match.end()]) <= budget:
            return match.end()
    keep = len(plain)
    while keep and cell_len(plain[:keep]) > budget:
        keep -= 1
    return keep


__all__ = [
    "PREVIEW_BAR_GLYPH",
    "PREVIEW_BAR_STYLE",
    "PREVIEW_BREAK_GLYPH",
    "PREVIEW_CARD_STYLE",
    "PREVIEW_DIM_STYLE",
    "PREVIEW_TAB_LABEL",
    "PREVIEW_TAB_LABEL_STYLE",
    "PREVIEW_TAB_ROWS",
    "XpromptPreviewFit",
    "fit_xprompt_preview",
    "pending_preview_rows",
    "preview_card",
    "preview_row_budget",
]
