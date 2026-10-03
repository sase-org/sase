"""Note-rail rows and width for the Memory panel shell.

Split of :mod:`sase.ace.tui.modals.memory_panel_rendering`: this module
owns tree-row text and the width ``#memory-panel-notes`` should take.
"""

from __future__ import annotations

from rich.cells import cell_len
from rich.text import Text

from sase.ace.tui.memory_panel_catalog import MemoryRailNode
from sase.memory.notes import collapse_description

from ._memory_panel_rendering_shared import note_is_invalid

_CORE_MARK = "●"  # ●
_REFERENCE_MARK = "○"  # ○
_WEB_MARK = "◆"  # ◆
_CHILD_INDENT = "└ "  # └
_WEB_COLLAPSED_MARK = "▸"  # ▸
_WEB_EXPANDED_MARK = "▾"  # ▾
_STRAND_MARK = "•"  # •
_GENERATED_MARK = "⚙"  # ⚙
_INVALID_MARK = "⚠"  # ⚠

# The note rail is sized to fit its widest row. Chrome is everything in
# ``#memory-panel-notes`` that is not text: the 1-cell ``solid`` border on
# each side, ``OptionList``'s default ``padding: 0 1``, and the 2-cell
# vertical scrollbar held open by ``scrollbar-gutter: stable``.
_NOTE_RAIL_CHROME = 6
# Never narrower than the historical fixed width, and never wide enough to
# crowd the note card. Mirrored by the ``min-width`` / ``max-width``
# backstops on ``#memory-panel-notes`` in ``styles.tcss``.
_NOTE_RAIL_MIN_WIDTH = 32
_NOTE_RAIL_MAX_WIDTH = 52
# Cells the note card keeps for itself, chrome included; 56 leaves it ~50
# columns of prose, the narrowest comfortable measure for a note.
_NOTE_RAIL_DETAIL_RESERVED = 56


def build_note_row_text(
    node: MemoryRailNode,
    *,
    generated_paths: frozenset[str],
    glance: str = "",
    glance_glyph: str = "",
    glance_promoted: bool = False,
    content_width: int = 0,
) -> Text:
    """Build one note-rail row: tree indent, glyphs, stem, and description.

    *glance* is the full ``glyph age`` suffix (``⇧ 8d``); when
    *content_width* is positive the suffix is right-aligned on the row's
    first line. A description that would collide wraps below it; the
    suffix sheds the age first and then the glyph so the stem never wraps.
    """
    base = _build_row_text(node, generated_paths=generated_paths, detail=True)
    if not glance:
        return base
    style = "bold" if glance_promoted else "dim"
    if content_width <= 0:
        base.append("  ")
        base.append(glance, style=style)
        return base
    head_len = _build_row_text(
        node, generated_paths=generated_paths, detail=False
    ).cell_len
    for suffix in (glance, glance_glyph):
        if not suffix:
            continue
        placed = _place_first_line_suffix(
            base, Text(suffix, style=style), content_width, head_len
        )
        if placed is not None:
            return placed
    return base


def _build_row_text(
    node: MemoryRailNode, *, generated_paths: frozenset[str], detail: bool
) -> Text:
    """Build a rail row; ``detail=False`` stops after the name the rail keys on."""
    if node.is_web and node.web is not None:
        return _build_web_row_text(node, generated_paths=generated_paths, detail=detail)
    if node.is_strand and node.strand is not None:
        return _build_strand_row_text(node, detail=detail)
    note = node.note
    base = Text()
    if node.depth > 0:
        base.append(_CHILD_INDENT, style="dim")
    marker = _CORE_MARK if note.type == "core" else _REFERENCE_MARK
    base.append(f"{marker} ")
    if note.relative_path in generated_paths:
        base.append(f"{_GENERATED_MARK} ")
    if note_is_invalid(note):
        base.append(f"{_INVALID_MARK} ", style="bold")
    base.append(note.path.stem)
    snippet = collapse_description(note.description) if detail else ""
    if snippet:
        base.append("  ")
        base.append(snippet, style="dim")
    return base


def _place_first_line_suffix(
    base: Text, suffix: Text, width: int, head_len: int
) -> Text | None:
    """Right-align *suffix* on *base*'s first line of *width* cells.

    Text past the room left on line one continues on the next line,
    broken at a space inside the detail when there is one. ``None``
    when the first *head_len* cells (the name) would not fit beside it.
    """
    room = int(width) - suffix.cell_len - 2
    if room < head_len:
        return None
    if base.cell_len <= room:
        line = base.copy()
        line.append(" " * (int(width) - base.cell_len - suffix.cell_len))
        line.append_text(suffix)
        return line
    plain = base.plain
    head_chars = _chars_within_cells(plain, head_len)
    offset = _chars_within_cells(plain, room)
    space = plain.rfind(" ", head_chars, offset + 1)
    cut = space if space >= head_chars else offset
    first = base[:cut]
    first.rstrip()
    rest = base[cut:]
    skip = len(rest.plain) - len(rest.plain.lstrip())
    rest = rest[skip:]
    line = first.copy()
    line.append(" " * (int(width) - first.cell_len - suffix.cell_len))
    line.append_text(suffix)
    if rest.plain:
        line.append("\n")
        line.append_text(rest)
    return line


def _chars_within_cells(plain: str, cells: int) -> int:
    """Return how many leading characters of *plain* fit in *cells* cells."""
    used = 0
    for index, char in enumerate(plain):
        used += cell_len(char)
        if used > cells:
            return index
    return len(plain)


def _build_web_row_text(
    node: MemoryRailNode, *, generated_paths: frozenset[str], detail: bool = True
) -> Text:
    web = node.web
    assert web is not None
    text = Text()
    if node.depth > 0:
        text.append(_CHILD_INDENT, style="dim")
    text.append(f"{_WEB_EXPANDED_MARK if node.expanded else _WEB_COLLAPSED_MARK} ")
    text.append(f"{_WEB_MARK} ")
    if node.note.relative_path in generated_paths:
        text.append(f"{_GENERATED_MARK} ")
    text.append(web.slug)
    if not detail:
        return text
    strand_word = web.strand_noun if len(web.strands) == 1 else f"{web.strand_noun}s"
    text.append(f"  {len(web.strands)} {strand_word}", style="dim")
    snippet = collapse_description(web.description)
    if snippet:
        text.append("  ")
        text.append(snippet, style="dim")
    return text


def _build_strand_row_text(node: MemoryRailNode, *, detail: bool = True) -> Text:
    strand = node.strand
    assert strand is not None
    text = Text()
    text.append("  " * max(0, node.depth), style="dim")
    text.append(f"{_STRAND_MARK} ")
    text.append(strand.keyword)
    if not detail:
        return text
    if strand.aliases:
        text.append("  ")
        text.append("aka " + " · ".join(strand.aliases), style="dim")
    elif strand.summary:
        text.append("  ")
        text.append(strand.summary, style="dim")
    return text


def note_rail_content_width(rail_width: int) -> int:
    """Return the text width inside a rail of *rail_width* (chrome aside)."""
    return max(0, int(rail_width) - _NOTE_RAIL_CHROME)


def note_rail_width(
    nodes: tuple[MemoryRailNode, ...],
    *,
    generated_paths: frozenset[str],
    available_width: int,
    glance_width: int = 0,
) -> int:
    """Return the width ``#memory-panel-notes`` should take.

    Wide enough for the widest row of *nodes* to render on one line, clamped
    so the rail is never narrower than its historical fixed width and never
    takes the note card's share of *available_width* -- the panel body's
    content width, or ``0`` before the first layout has settled.
    *glance_width* reserves the recency column (suffix plus its gap).
    """
    if not nodes:
        return _NOTE_RAIL_MIN_WIDTH
    widest = max(
        build_note_row_text(node, generated_paths=generated_paths).cell_len
        for node in nodes
    )
    if glance_width > 0:
        widest += int(glance_width) + 2
    desired = widest + _NOTE_RAIL_CHROME
    cap = _NOTE_RAIL_MAX_WIDTH
    if available_width > 0:
        # The ``- 1`` is ``#memory-panel-detail``'s ``margin-left``.
        room = available_width - _NOTE_RAIL_DETAIL_RESERVED - 1
        cap = min(cap, max(_NOTE_RAIL_MIN_WIDTH, room))
    return max(_NOTE_RAIL_MIN_WIDTH, min(cap, desired))


__all__ = [
    "build_note_row_text",
    "note_rail_content_width",
    "note_rail_width",
]
