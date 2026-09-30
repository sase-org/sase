"""Single-bead note attachment authoring entry point."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ._authoring_audience import decide_visibilities
from ._authoring_common import bare_word_hints
from ._authoring_manifest import build_manifest
from ._authoring_models import AuthoredNoteAttachments, roster_wires
from ._authoring_scan import assign_names, scan_resolve_ingest

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sase.bead.attachments.progress import ProgressFactory
    from sase.bead.model import BeadNote


def author_note_attachments(
    text: str,
    *,
    notes: Sequence[BeadNote] = (),
    cwd: Path | str | None = None,
    allow_sensitive: bool = False,
    previous_manifest: Sequence[str] = (),
    preferred_names: Mapping[str, str] | None = None,
    progress_factory: ProgressFactory | None = None,
    audience_requested: str = "auto",
    audience_confirmed: bool = False,
    audience_actor: str | None = None,
) -> AuthoredNoteAttachments:
    """Scan *text*, ingest referenced files, and compose the stored note.

    *preferred_names* maps a raw scanner path (as written in the note text)
    to the attachment name it should take instead of its file basename.
    *progress_factory* draws a TTY bar per ingested file (the CLI passes
    :func:`transfer_progress`); the TUI passes nothing and stays clean.
    *audience_requested* is one of ``auto`` | ``public`` | ``private`` |
    ``local_only``; *audience_confirmed* skips the human widening prompt.
    """
    from sase.core.rust import require_rust_binding

    roster = roster_wires(notes)
    scan, path_refs, reuse_refs, resolved, blobs, base_dir = scan_resolve_ingest(
        text, list(roster), cwd, allow_sensitive, progress_factory
    )
    assigned, display_bases = assign_names(
        resolved, blobs, roster, path_refs, preferred_names
    )
    assigned_names = [assigned[index] for index in range(len(path_refs))]
    compose_binding = require_rust_binding("compose_note_attachment_text")
    stored_text = str(compose_binding(text, scan, assigned_names))
    visibilities = decide_visibilities(
        resolved,
        blobs,
        assigned,
        notes=notes,
        allow_sensitive=allow_sensitive,
        audience_requested=audience_requested,
        audience_confirmed=audience_confirmed,
        audience_actor=audience_actor,
    )
    manifest, echo_rows = build_manifest(
        resolved, blobs, assigned, reuse_refs, roster, display_bases, visibilities
    )
    new_names = [wire["name"] for wire in manifest]
    detached = tuple(name for name in previous_manifest if name not in new_names)
    for name in detached:
        echo_rows.append(f"detached {name}")
    echo_rows.extend(bare_word_hints(scan, base_dir))
    return AuthoredNoteAttachments(
        stored_text=stored_text,
        attachments=manifest,
        echo_rows=echo_rows,
        detached=detached,
    )
