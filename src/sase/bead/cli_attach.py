"""Bead attachment CLI command handler: ``sase bead attach``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from sase.bead.cli_common import (
    auto_commit_bead_store,
    bead_store_mutation,
    resolve_bead_operation_context,
)
from sase.bead.cli_crud_common import (
    print_attachment_echo_rows,
    resolve_mutation_author,
)
from sase.bead.mutation_commit import require_mutation_commit_message


def handle_bead_attach(args: argparse.Namespace) -> None:
    """Attach file snapshots to a bead as a new attributed note."""
    files: list[str] = list(getattr(args, "files", None) or [])
    name = getattr(args, "name", None)
    prose = getattr(args, "note", None)
    allow_sensitive = bool(getattr(args, "allow_sensitive", False))
    local_only = bool(getattr(args, "local_only", False))
    private = bool(getattr(args, "private", False))
    public = bool(getattr(args, "public", False))
    confirmed = bool(getattr(args, "yes", False))
    from sase.bead.attachments import audience as _audience

    if public and not _audience.audience_enabled():
        _audience.refuse_public_when_flag_off()
    _audience.validate_audience_flags(
        private=private,
        public=public,
        allow_sensitive=allow_sensitive,
        local_only=local_only,
        has_attachments=True,
    )
    audience_requested = _audience.requested_from_flags(
        private=private, public=public, local_only=local_only
    )

    if "-" in files and name is None:
        print(
            "Error: -N/--name is required when attaching from stdin (-).",
            file=sys.stderr,
        )
        sys.exit(1)
    if name is not None and len(files) != 1:
        print(
            "Error: -N/--name takes exactly one file "
            f"(got {len(files)}: {', '.join(files)}).",
            file=sys.stderr,
        )
        sys.exit(1)

    bead_context = resolve_bead_operation_context([args.id], for_write=True)
    issue_id = bead_context.resolved_ids[0]
    placement = "skip"
    placement_store: Any | None = None
    placement_key: str | None = None
    placement_require = False
    placement_wires: list[dict[str, Any]] = []
    with bead_store_mutation(
        auto_commit_bead_store,
        bead_context=bead_context,
    ) as mutation:
        try:
            author = args.author
            if author is None:
                author = resolve_mutation_author(mutation.project)
            current = mutation.project.show(issue_id)
            if files == ["-"]:
                stored_text, manifest, echo_rows = _author_stdin_attach(
                    current.notes,
                    prose=prose,
                    name=str(name),
                    allow_sensitive=allow_sensitive,
                    audience_requested=audience_requested,
                    audience_confirmed=confirmed,
                )
            else:
                authored = _author_files_attach(
                    current.notes,
                    prose=prose,
                    files=files,
                    name=name,
                    allow_sensitive=allow_sensitive,
                    audience_requested=audience_requested,
                    audience_confirmed=confirmed,
                )
                stored_text, manifest, echo_rows = (
                    authored.stored_text,
                    authored.attachments,
                    authored.echo_rows,
                )
            if manifest:
                from sase.bead.attachments.upload import pre_write_upload

                (
                    placement,
                    placement_store,
                    placement_key,
                    placement_require,
                ) = pre_write_upload(
                    manifest,
                    echo_rows,
                    local_only=local_only,
                    bead_context=bead_context,
                )
                placement_wires = list(manifest)
            issue = mutation.project.append_note(
                issue_id,
                stored_text,
                author=author,
                attachments=manifest,
            )
        except KeyError:
            print(f"Error: issue not found: {args.id}", file=sys.stderr)
            sys.exit(1)
        if placement in ("git", "large", "mixed", "public_pending") and placement_wires:
            from sase.bead.attachments.upload import post_write_queue

            post_write_queue(
                mutation,
                placement_wires,
                echo_rows,
                placement=placement,
                stores=placement_store,
                project_key=placement_key,
                require_upload=placement_require,
            )
        mutation.commit(require_mutation_commit_message("attach", [issue.id]))

    print_attachment_echo_rows(echo_rows)
    print(f"Attached: {issue.id} — {issue.title}")


def _author_files_attach(
    notes: Any,
    *,
    prose: str | None,
    files: list[str],
    name: str | None,
    allow_sensitive: bool,
    audience_requested: str = "auto",
    audience_confirmed: bool = False,
) -> Any:
    """Run the authoring service over prose plus one token per file."""
    from sase.bead.attachments.authoring import (
        NoteAttachmentAuthoringError,
        author_note_attachments,
    )

    source = _attach_source_text(prose, files)
    preferred = {files[0]: name} if name is not None else None
    from sase.bead.attachments.progress import transfer_progress

    try:
        return author_note_attachments(
            source,
            notes=notes,
            cwd=Path.cwd(),
            allow_sensitive=allow_sensitive,
            preferred_names=preferred,
            progress_factory=transfer_progress,
            audience_requested=audience_requested,
            audience_confirmed=audience_confirmed,
        )
    except NoteAttachmentAuthoringError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


def _author_stdin_attach(
    notes: Any,
    *,
    prose: str | None,
    name: str,
    allow_sensitive: bool,
    audience_requested: str = "auto",
    audience_confirmed: bool = False,
) -> tuple[str, list[dict[str, Any]], list[str]]:
    """Attach piped stdin bytes under *name*, with optional prose above.

    Stdin has no path for the scanner, so the stream is ingested directly and
    only the prose (when present) goes through the authoring service. Either
    failure writes no note.
    """
    from sase.bead.attachments.authoring import (
        NoteAttachmentAuthoringError,
        author_note_attachments,
        roster_wires,
        stream_attachment_wire,
    )
    from sase.bead.attachments.ingest import IngestError, ingest_stream

    roster = roster_wires(notes)
    manifest: list[dict[str, Any]] = []
    echo_rows: list[str] = []
    from sase.bead.attachments.progress import transfer_progress

    if prose:
        try:
            authored = author_note_attachments(
                prose,
                notes=notes,
                cwd=Path.cwd(),
                allow_sensitive=allow_sensitive,
                progress_factory=transfer_progress,
                audience_requested=audience_requested,
                audience_confirmed=audience_confirmed,
            )
        except NoteAttachmentAuthoringError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        manifest.extend(authored.attachments)
        echo_rows.extend(authored.echo_rows)
        stored_text = authored.stored_text
    else:
        stored_text = ""
    try:
        blob = ingest_stream(sys.stdin.buffer, display_name="<stdin>")
    except IngestError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    existing = dict(roster)
    for wire in manifest:
        existing[wire["name"]] = wire
    try:
        wire, row = stream_attachment_wire(
            name,
            sha256=blob.sha256,
            size_bytes=blob.size_bytes,
            head=bytes(blob.head),
            object_path=blob.object_path,
            roster=existing,
            audience_requested=audience_requested,
            audience_confirmed=audience_confirmed,
            allow_sensitive=allow_sensitive,
        )
    except NoteAttachmentAuthoringError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    manifest.append(wire)
    echo_rows.append(row)
    if stored_text:
        stored_text += "\n\n"
    stored_text += f"@attachment:{wire['name']}"
    return stored_text, manifest, echo_rows


def _attach_source_text(prose: str | None, files: list[str]) -> str:
    """Build the scanner source: prose, a blank line, then one token per file."""
    tokens = [_attach_token(path) for path in files]
    if prose:
        return prose + "\n\n" + "\n".join(tokens)
    return "\n".join(tokens)


def _attach_token(path: str) -> str:
    """Render one file argument as a scanner path reference."""
    if '"' in path or any(char.isspace() for char in path):
        return f'@"{path}"'
    return f"@{path}"


__all__ = ["handle_bead_attach"]
