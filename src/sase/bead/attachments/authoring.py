"""Shared authoring service for bead note attachments.

Compatibility facade: the pipeline lives in focused modules; this module
keeps the historical ``sase.bead.attachments.authoring`` import surface
intact. Patch the module that defines a helper (``_authoring_scan``,
``_authoring_audience``, ...), not this facade.

One pipeline, used by the CLI note verbs and the TUI add-note modal::

    1. Scan the text with the bead's current roster names.
    2. Resolve and stat every referenced path; apply the sensitive-path policy.
    3. Raise one error for every scanner diagnostic and resolution problem.
    4. Ingest each unique resolved path once.
    5. Classify, probe images, and record the machine origin.
    6. Uniquify names against the roster plus this text, then compose.

It returns the stored text, the wire manifest, echo rows, and the names the
edit detached. Nothing is written to the bead store: callers pass the
manifest into the mutation only after this returns.
"""

from __future__ import annotations

from ._authoring_audience import stream_attachment_wire
from ._authoring_models import (
    HINT_ROW_PREFIX,
    AuthoredNoteAttachments,
    NoteAttachmentAuthoringError,
    roster_wires,
)
from .authoring_per_bead import author_note_attachments_per_bead
from .authoring_single import author_note_attachments

__all__ = [
    "HINT_ROW_PREFIX",
    "AuthoredNoteAttachments",
    "NoteAttachmentAuthoringError",
    "author_note_attachments",
    "author_note_attachments_per_bead",
    "roster_wires",
    "stream_attachment_wire",
]
