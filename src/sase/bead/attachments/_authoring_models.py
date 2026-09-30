"""Roster and result types for bead note attachment authoring."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sase.bead.model import BeadNote

#: Echo rows starting with this prefix are dim hints, not attached files.
HINT_ROW_PREFIX = "hint: "


class NoteAttachmentAuthoringError(ValueError):
    """One or more attachment problems in note text; nothing was written."""


@dataclass(frozen=True)
class AuthoredNoteAttachments:
    """The result of running the authoring pipeline over note text."""

    stored_text: str
    #: ``BeadNoteAttachmentWire`` dicts to persist with the note.
    attachments: list[dict[str, Any]] = field(default_factory=list)
    #: stderr rows for the write echo. Rows starting with ``"hint: "`` are
    #: dim hints; the rest name attached or detached files.
    echo_rows: list[str] = field(default_factory=list)
    #: Previous-manifest names absent from the new manifest (edits only).
    detached: tuple[str, ...] = ()


def roster_wires(notes: Sequence[BeadNote]) -> dict[str, dict[str, Any]]:
    """Map each roster name to its latest wire dict (public for CLI verbs).

    The latest note wins per name, matching sase-core's
    ``bead_attachment_roster`` over the current notes.
    """
    roster: dict[str, dict[str, Any]] = {}
    for note in notes:
        for attachment in note.attachments:
            wire: dict[str, Any] = {
                "name": attachment.name,
                "sha256": attachment.sha256,
                "size_bytes": attachment.size_bytes,
                "mime_type": attachment.mime_type,
            }
            if attachment.image is not None:
                wire["image"] = {
                    "width": attachment.image[0],
                    "height": attachment.image[1],
                }
            if attachment.origin is not None:
                wire["origin"] = attachment.origin
            if attachment.visibility is not None:
                wire["visibility"] = attachment.visibility
            roster[attachment.name] = wire
    return roster
