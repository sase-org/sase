"""Shared language and palette for structured bead note presentation."""

from __future__ import annotations

from collections.abc import Iterable

from sase.ansi_style import ansi_sgr
from sase.bead.model import BeadNote
from sase.bead_time_presentation import (
    BEAD_TIME_UNKNOWN_LABEL,
    bead_age_label,
    bead_instant_label,
)

NOTE_ACCENT = "#AFAF87"
NOTE_RICH_STYLE = f"bold {NOTE_ACCENT}"
NOTE_CLI_STYLE = ansi_sgr(color=NOTE_ACCENT, bold=True)
NOTE_SECTION_LABEL = "NOTES"
NOTE_EDITED_MARKER = "edited"


def _instant_and_age_label(value: str, *, relative: bool) -> str:
    instant = bead_instant_label(value)
    if not relative or instant == BEAD_TIME_UNKNOWN_LABEL:
        return instant

    age = bead_age_label(value)
    if not age:
        return instant
    if age == "now":
        return f"{instant} · now"
    return f"{instant} · {age} ago"


def bead_note_label(note: BeadNote, ordinal: int, *, relative: bool) -> str:
    """Return the stable one-line label for a note record."""

    parts = [
        f"#{ordinal}",
        _instant_and_age_label(note.timestamp, relative=relative),
        note.author,
    ]
    if note.edited_at is not None:
        edited = f"{NOTE_EDITED_MARKER} {bead_instant_label(note.edited_at)}"
        if note.edited_by and note.edited_by != note.author:
            edited = f"{edited} by {note.edited_by}"
        parts.append(edited)
    return " · ".join(parts)


def bead_note_search_text(notes: Iterable[BeadNote]) -> str:
    """Flatten structured notes for in-memory search indexes."""

    return "\n".join(
        value
        for note in notes
        for value in (
            note.timestamp,
            note.author,
            note.text,
            note.edited_at,
            note.edited_by,
        )
        if value
    )


__all__ = [
    "NOTE_ACCENT",
    "NOTE_CLI_STYLE",
    "NOTE_EDITED_MARKER",
    "NOTE_RICH_STYLE",
    "NOTE_SECTION_LABEL",
    "bead_note_label",
    "bead_note_search_text",
]
