"""Compact ARTIFACTS ``Beads`` row renderer for the prompt-panel header."""

from __future__ import annotations

from rich.cells import cell_len
from rich.text import Text

from sase.ace.tui.bead_hint_targets import bead_hint_target as _bead_hint_target
from sase.ace.tui.bead_touches import BeadTouchEntry
from sase.core.bead_touch_index_facade import BeadNotePreview
from sase.bead.touch_glyphs import touch_glyph

from ._agent_context_common import (
    COLOR_BEAD_PRIMARY,
    COLOR_BEAD_SUBHEADER,
    COLOR_ROLE,
    COLOR_SUMMARY,
    COLOR_TRUNCATION,
    REASON_LINE_CELL_LIMIT,
    append_context_reason,
    append_lane_row,
    format_local_hhmm,
)
from ._agent_display_state import HeaderHintState
from ._helpers import wrap_text_by_cells

MAX_VISIBLE_BEADS = 5
_SUBSECTION_ROW_PREFIX = "  "
_MAX_NOTE_TEXT_LINES = 3

__all__ = [
    "MAX_VISIBLE_BEADS",
    "append_agent_bead_touch_rows",
]


def _bead_touch_glyph(entry: BeadTouchEntry) -> str:
    """Return the row's single strongest verb glyph via the shared vocabulary."""
    return touch_glyph(entry.verbs)


def _ordered_bead_verb_chips(entry: BeadTouchEntry) -> list[str]:
    """Return the verb chips in render order.

    ``own`` first, then durable verbs in the entry's verb-map order
    (the merge produces that order newest-touch-first), then ``read``,
    then ``viewed``. Counts above one render as ``×N``.
    """
    chips: list[str] = []
    if entry.own:
        chips.append("own")
    for verb, count in entry.verbs.items():
        if verb in ("read", "viewed"):
            continue
        chips.append(_chip(verb, count))
    if "read" in entry.verbs:
        chips.append(_chip("read", entry.verbs["read"]))
    if "viewed" in entry.verbs:
        chips.append(_chip("viewed", entry.verbs["viewed"]))
    return chips


def _chip(verb: str, count: int) -> str:
    if count > 1:
        return f"{verb} ×{count}"
    return verb


def _safe_note_text(value: str) -> str:
    """Return display data with whitespace normalized and controls removed."""
    without_controls = "".join(
        " " if character.isspace() else character
        for character in value
        if ord(character) >= 32 and ord(character) != 127
    )
    return " ".join(without_controls.split())


def _append_note_line(text: Text, *, indent: int, content: str, style: str) -> None:
    text.append(" " * indent + "│ ", style=COLOR_BEAD_SUBHEADER)
    text.append(content + "\n", style=style)


def _append_bead_note_preview(
    text: Text,
    *,
    preview: BeadNotePreview,
    current_note_count: int,
    indent: int,
    role_label: str | None = None,
) -> None:
    """Render one bounded, attributed note block beneath its bead row.

    This is intentionally a pure Text helper: the loader has already read the
    cached touch index off the event loop, and rendering performs no bead
    lookup.  The note text is data, never Rich markup, and its display limit
    is independent from the cache's Unicode-safe prefix limit.
    """
    body = _safe_note_text(preview.text)
    if not body:
        return
    author = _safe_note_text(preview.author)
    if not author:
        return
    metadata = f"{format_local_hhmm(preview.timestamp)} · {author}"
    role = _safe_note_text(role_label or "")
    if role:
        metadata += f" · {role}"
    if preview.edited_at:
        metadata += " · edited"

    prefix_cells = cell_len(" " * indent + "│ ")
    available = max(1, REASON_LINE_CELL_LIMIT - prefix_cells)
    for line in wrap_text_by_cells(metadata, available):
        _append_note_line(text, indent=indent, content=line, style=COLOR_SUMMARY)

    body_lines = wrap_text_by_cells(body, available)
    for line in body_lines[:_MAX_NOTE_TEXT_LINES]:
        _append_note_line(text, indent=indent, content=line, style="")

    if len(body_lines) > _MAX_NOTE_TEXT_LINES or preview.truncated:
        _append_note_line(
            text,
            indent=indent,
            content="… full note in bead detail",
            style=COLOR_TRUNCATION,
        )
    earlier = max(current_note_count - 1, 0)
    if earlier:
        noun = "note" if earlier == 1 else "notes"
        _append_note_line(
            text,
            indent=indent,
            content=f"+{earlier} earlier {noun} in bead detail",
            style=COLOR_TRUNCATION,
        )


def append_agent_bead_touch_rows(
    text: Text,
    *,
    entries: tuple[BeadTouchEntry, ...],
    hint_state: HeaderHintState | None = None,
) -> None:
    """Append newest-first bead rows under an ARTIFACTS ``Beads:`` header.

    The ARTIFACTS lane owns sub-section ordering and the summary counts;
    this helper only paints the compact rows, reasons, hints, and overflow
    footer. The bead id is never truncated; the ``↳`` line shows the newest
    audited read reason when present, otherwise the bead title, and is
    omitted when both are empty. The reason/title wraps via
    ``append_context_reason``.
    """
    visible = entries[:MAX_VISIBLE_BEADS]
    show_role_column = any(item.agent_label for item in visible)
    extra_indent = len(_SUBSECTION_ROW_PREFIX)
    for item in visible:
        glyph = _bead_touch_glyph(item)
        assert cell_len(glyph) == 1, f"bead glyph must stay single-cell: {glyph!r}"
        hint_label = None
        if hint_state is not None:
            target = _bead_hint_target(item.bead_id)
            if target is not None:
                hint_number = hint_state.hint_counter
                hint_state.hint_mappings[hint_number] = target
                hint_state.hint_counter += 1
                hint_label = Text(f"[{hint_number}] ", style="bold #FFFF00")
        text.append(_SUBSECTION_ROW_PREFIX)
        reason_indent = (
            append_lane_row(
                text,
                timestamp=item.last_at or item.first_at,
                glyph=glyph,
                glyph_style=COLOR_BEAD_SUBHEADER,
                primary=item.bead_id,
                primary_style=COLOR_BEAD_PRIMARY,
                role_label=item.agent_label,
                show_role_column=show_role_column,
                hint_label=hint_label,
            )
            + extra_indent
        )
        for chip in _ordered_bead_verb_chips(item):
            text.append(" · ", style=COLOR_SUMMARY)
            text.append(chip, style=COLOR_ROLE if chip == "own" else COLOR_SUMMARY)
        text.append("\n")
        if item.note_preview is not None:
            _append_bead_note_preview(
                text,
                preview=item.note_preview,
                current_note_count=item.current_note_count,
                indent=reason_indent,
                role_label=item.note_agent_label,
            )
        reason_text = (
            f"read: {item.read_reasons[0]}"
            if item.note_preview is not None and item.read_reasons
            else (item.read_reasons[0] if item.read_reasons else item.title)
        )
        if reason_text.strip():
            append_context_reason(text, reason_text, indent=reason_indent)

    overflow = len(entries) - len(visible)
    if overflow > 0:
        earliest = entries[-1]
        text.append(
            f"  {_SUBSECTION_ROW_PREFIX}+ {overflow} more · "
            f"{format_local_hhmm(earliest.last_at or earliest.first_at)} earliest\n",
            style=COLOR_TRUNCATION,
        )
