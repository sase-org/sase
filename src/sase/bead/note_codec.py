"""Wire encoding and decoding for structured bead notes.

``notes`` crosses three storage surfaces that all speak the same record
shape: the Rust outcome dicts read by :mod:`sase.core.bead_wire`, the
``issues.jsonl`` rows written by :mod:`sase.bead.jsonl`, and the JSON column
in the compatibility SQLite mirror. They share this codec so a record cannot
mean one thing in one surface and something else in another.

Key order and omitted-when-absent optional keys mirror ``BeadNoteWire`` in
sase-core so a row this module writes is byte-identical to the Rust writer's.
``parse_legacy_note_blob`` ports sase-core's reducer-side parser of the same
name so a store with no event directory (a bare ``issues.jsonl``, or the
SQLite mirror) recovers the same records the Rust reducer would.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sase.bead.model import BeadNote

LEGACY_NOTE_ID_PREFIX = "__legacy_note__"


def _note_to_dict(note: BeadNote) -> dict[str, Any]:
    """Encode one note in sase-core wire field order."""
    return {
        "id": note.id,
        "timestamp": note.timestamp,
        "author": note.author,
        "text": note.text,
        **({"edited_at": note.edited_at} if note.edited_at is not None else {}),
        **({"edited_by": note.edited_by} if note.edited_by is not None else {}),
    }


def notes_to_dicts(notes: list[BeadNote]) -> list[dict[str, Any]]:
    return [_note_to_dict(note) for note in notes]


def _note_from_dict(entry: object) -> BeadNote | None:
    if not isinstance(entry, dict):
        return None
    note_id = str(entry.get("id") or "").strip()
    timestamp = str(entry.get("timestamp") or "").strip()
    author = str(entry.get("author") or "").strip()
    text = str(entry.get("text") or "").strip()
    if not note_id or not timestamp or not author or not text:
        return None
    edited_at = entry.get("edited_at")
    edited_by = entry.get("edited_by")
    return BeadNote(
        id=note_id,
        timestamp=timestamp,
        author=author,
        text=text,
        edited_at=None if edited_at is None else str(edited_at),
        edited_by=None if edited_by is None else str(edited_by),
    )


def notes_from_dicts(value: object) -> list[BeadNote]:
    """Decode a list of note dicts, tolerating absence and junk entries."""
    if not isinstance(value, list):
        return []
    notes: list[BeadNote] = []
    for entry in value:
        note = _note_from_dict(entry)
        if note is not None:
            notes.append(note)
    return notes


def notes_text(notes: list[BeadNote]) -> str:
    """The flattened text projection, matching sase-core's ``notes_text``."""
    return "\n\n".join(
        f"[{note.timestamp} · {note.author}] {note.text.strip()}" for note in notes
    )


def notes_from_data(
    value: object,
    *,
    fallback_timestamp: str,
    fallback_author: str,
) -> list[BeadNote]:
    """Decode either the new record list or a legacy free-text blob.

    Mirrors sase-core's untagged ``IssueNotesInput`` deserializer: a plain
    string is recovered into records via :func:`parse_legacy_note_blob`
    rather than treated as a single opaque record.
    """
    if isinstance(value, str):
        if not value.strip():
            return []
        return parse_legacy_note_blob(
            value, LEGACY_NOTE_ID_PREFIX, fallback_timestamp, fallback_author
        )
    return notes_from_dicts(value)


def _fallback_value(value: str) -> str:
    value = value.strip()
    return value or "unknown"


def parse_legacy_note_blob(
    text: str,
    event_id: str,
    timestamp: str,
    actor: str,
) -> list[BeadNote]:
    """Recover structured notes from a pre-migration free-text blob.

    Splits *text* into blank-line-delimited paragraphs, matching how
    ``appended_note_text`` joined them. A paragraph beginning
    ``[<rfc3339-ts> · <actor>] `` starts a new record with that recovered
    timestamp and author; a marker whose timestamp does not parse is not
    treated as a header. Any text before the first marker (or the whole blob,
    if it never had one) is attributed to *timestamp* and *actor*.
    """
    fallback_timestamp = _fallback_value(timestamp)
    fallback_author = _fallback_value(actor)
    records: list[BeadNote] = []
    current: dict[str, str] | None = None

    for paragraph in _legacy_note_paragraphs(text):
        header = _legacy_note_header(paragraph)
        if header is not None:
            if current is not None:
                records.append(BeadNote(**current))
            header_timestamp, header_actor, body = header
            current = {
                "id": f"{event_id}#{len(records) + 1}",
                "timestamp": header_timestamp,
                "author": header_actor,
                "text": body,
            }
            continue

        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if current is not None:
            current["text"] = (
                f"{current['text']}\n\n{paragraph}" if current["text"] else paragraph
            )
        else:
            current = {
                "id": f"{event_id}#{len(records) + 1}",
                "timestamp": fallback_timestamp,
                "author": fallback_author,
                "text": paragraph,
            }

    if current is not None:
        records.append(BeadNote(**current))
    return records


def _legacy_note_paragraphs(text: str) -> list[str]:
    paragraphs: list[str] = []
    current: list[str] = []
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    for line in normalized.split("\n"):
        if line.strip() == "":
            if current:
                paragraphs.append("\n".join(current))
                current = []
        else:
            current.append(line)
    if current:
        paragraphs.append("\n".join(current))
    return paragraphs


def _legacy_note_header(paragraph: str) -> tuple[str, str, str] | None:
    if not paragraph.startswith("["):
        return None
    rest = paragraph[1:]
    if "] " not in rest:
        return None
    header, _, body = rest.partition("] ")
    if " · " not in header:
        return None
    timestamp, _, actor = header.partition(" · ")
    timestamp = timestamp.strip()
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    actor = actor.strip()
    body = body.strip()
    if not actor or not body:
        return None
    return (timestamp, actor, body)


__all__ = [
    "LEGACY_NOTE_ID_PREFIX",
    "notes_from_data",
    "notes_from_dicts",
    "notes_text",
    "notes_to_dicts",
    "parse_legacy_note_blob",
]
