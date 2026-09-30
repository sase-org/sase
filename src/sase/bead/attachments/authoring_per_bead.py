"""Per-bead note attachment authoring entry point."""

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


def author_note_attachments_per_bead(
    text: str,
    notes_per_bead: Sequence[Sequence[BeadNote]],
    *,
    cwd: Path | str | None = None,
    allow_sensitive: bool = False,
    preferred_names: Mapping[str, str] | None = None,
    progress_factory: ProgressFactory | None = None,
    audience_requested: str = "auto",
    audience_confirmed: bool = False,
    audience_actor: str | None = None,
) -> list[AuthoredNoteAttachments]:
    """Scan and ingest *text* once, then compose one result per bead roster.

    Every unique path is resolved and ingested a single time, but names are
    uniquified against each bead's own roster, so one filename can land on
    different names on different beads. Reuse tokens join per bead too.
    *progress_factory* draws a TTY bar per ingested file (the CLI passes
    :func:`transfer_progress`); the TUI passes nothing and stays clean.
    """
    from sase.core.rust import require_rust_binding

    rosters = [roster_wires(notes) for notes in notes_per_bead]
    union_names = list(dict.fromkeys(name for roster in rosters for name in roster))
    scan, path_refs, reuse_refs, resolved, blobs, base_dir = scan_resolve_ingest(
        text, union_names, cwd, allow_sensitive, progress_factory
    )
    compose_binding = require_rust_binding("compose_note_attachment_text")
    results: list[AuthoredNoteAttachments] = []
    flat_notes = [note for notes in notes_per_bead for note in notes]
    visibilities = decide_visibilities(
        resolved,
        blobs,
        assign_names(resolved, blobs, {}, path_refs, preferred_names)[0],
        notes=flat_notes,
        allow_sensitive=allow_sensitive,
        audience_requested=audience_requested,
        audience_confirmed=audience_confirmed,
        audience_actor=audience_actor,
    )
    for roster in rosters:
        assigned, display_bases = assign_names(
            resolved, blobs, roster, path_refs, preferred_names
        )
        assigned_names = [assigned[index] for index in range(len(path_refs))]
        stored_text = str(compose_binding(text, scan, assigned_names))
        manifest, echo_rows = build_manifest(
            resolved, blobs, assigned, reuse_refs, roster, display_bases, visibilities
        )
        echo_rows.extend(bare_word_hints(scan, base_dir))
        results.append(
            AuthoredNoteAttachments(
                stored_text=stored_text,
                attachments=manifest,
                echo_rows=echo_rows,
            )
        )
    return results
