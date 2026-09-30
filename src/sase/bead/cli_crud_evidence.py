"""Attributed-evidence bead CLI command handlers: ``+1`` and ``note``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich.console import Console
from rich.markup import escape

from sase.agent.identity import current_instant, resolve_observation_window_start
from sase.bead.cli_common import (
    auto_commit_bead_store,
    bead_store_mutation,
    resolve_bead_operation_context,
)
from sase.bead.cli_crud_common import (
    note_attachments_enabled as _note_attachments_enabled,
    print_attachment_echo_rows,
    resolve_mutation_author,
)
from sase.bead.model import Status
from sase.bead.mutation_commit import require_mutation_commit_message
from sase.cli_file_values import (
    CliFileValueError,
    read_at_path_value,
    read_note_text_value,
)

if TYPE_CHECKING:
    from sase.bead.attachments.authoring import AuthoredNoteAttachments


def _withheld_reopen_note(reporter: str, closed_at: str) -> str:
    return (
        f"{reporter}'s +1 postdates the {closed_at} close, but its "
        "observation window does not, so the reopen was withheld and the "
        "bead was left closed. Re-file with --verified-after-close if this "
        "reproduces on a tree that already contains the close."
    )


def handle_bead_plus_one(args: argparse.Namespace) -> None:
    """Record independently attributed evidence on an existing task bead."""
    verified_after_close = bool(getattr(args, "verified_after_close", False))
    allow_sensitive = bool(getattr(args, "allow_sensitive", False))
    attachments_on = _note_attachments_enabled()
    local_only = bool(getattr(args, "local_only", False)) and attachments_on
    try:
        if attachments_on:
            note = read_note_text_value(args.note, target="--note", bead_id=args.id)
        else:
            note = read_at_path_value(args.note, target="--note")
    except CliFileValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    bead_context = resolve_bead_operation_context([args.id], for_write=True)
    issue_id = bead_context.resolved_ids[0]
    echo_rows: list[str] = []
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
            stored_note = note
            note_attachments: list[dict[str, Any]] | None = None
            if attachments_on:
                authored = _author_note_text(
                    mutation,
                    issue_id,
                    note,
                    edit_ordinal=None,
                    allow_sensitive=allow_sensitive,
                )
                stored_note = authored.stored_text
                note_attachments = authored.attachments or None
                echo_rows = authored.echo_rows
                if note_attachments:
                    from sase.bead.attachments.upload import pre_write_upload

                    (
                        placement,
                        placement_store,
                        placement_key,
                        placement_require,
                    ) = pre_write_upload(
                        note_attachments,
                        echo_rows,
                        local_only=local_only,
                        bead_context=bead_context,
                        attachments_on=attachments_on,
                    )
                    placement_wires = list(note_attachments)
            reporter = getattr(args, "author", None)
            if reporter is None:
                reporter = resolve_mutation_author(mutation.project)
            if verified_after_close:
                target = mutation.project.show(issue_id)
                if target.status is not Status.CLOSED:
                    print(
                        "Error: --verified-after-close requires a closed "
                        f"bead (currently {target.status.value}): {issue_id}",
                        file=sys.stderr,
                    )
                    sys.exit(1)
                observed_since = current_instant()
            else:
                observed_since = resolve_observation_window_start()
            issue, changed = mutation.project.plus_one(
                issue_id,
                stored_note,
                reporter=reporter,
                refs=getattr(args, "ref", None) or (),
                observed_since=observed_since,
                note_attachments=note_attachments,
            )
        except KeyError:
            print(f"Error: issue not found: {args.id}", file=sys.stderr)
            sys.exit(1)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        outcome = mutation.project.last_mutation_outcome
        reopen_withheld = bool(outcome.get("reopen_withheld"))
        reopen_withheld_closed_at = str(outcome.get("reopen_withheld_closed_at") or "")
        if changed and reopen_withheld:
            mutation.project.append_note(
                issue.id,
                _withheld_reopen_note(reporter, reopen_withheld_closed_at),
                author=reporter,
            )
        if changed and placement in ("git", "large", "mixed") and placement_wires:
            from sase.bead.attachments.upload import post_write_queue

            post_write_queue(
                mutation,
                placement_wires,
                echo_rows,
                placement=placement,
                stores=placement_store,
                project_key=placement_key,
                require_upload=placement_require,
                attachments_on=attachments_on,
            )
        if changed:
            mutation.commit(require_mutation_commit_message("+1", [issue.id]))

    report_word = "report" if issue.plus_one_count == 1 else "reports"
    if changed:
        # The withheld-reopen follow-up note is generated text, not scanned.
        print_attachment_echo_rows(echo_rows)
    if changed and reopen_withheld:
        # Soft wrap: the reminder names two commands, and a mid-word wrap
        # (e.g. splitting `sase bead open`) reads as a broken instruction.
        Console(soft_wrap=True).print(
            f"[yellow]·[/yellow] +1 recorded: {escape(issue.id)} — "
            f"[bold]+{issue.plus_one_count}[/bold] independent {report_word}, "
            f"but the close at {escape(reopen_withheld_closed_at)} was left "
            "standing (reopen withheld). Pass --verified-after-close if you "
            "reproduced this after the close, or `sase bead open` to reopen "
            "directly."
        )
        return
    if changed:
        Console().print(
            f"[green]✓[/green] +1 recorded: {escape(issue.id)} — "
            f"[bold]+{issue.plus_one_count}[/bold] independent {report_word}"
        )
        return
    if reporter == issue.created_by:
        reason = "the task creator does not count as an additional reporter"
    else:
        reason = (
            f"{reporter} already reported this task; use `sase bead note` "
            "for supplementary evidence"
        )
    Console().print(
        f"[yellow]·[/yellow] Unchanged: {escape(issue.id)} — "
        f"{escape(reason)} ([bold]+{issue.plus_one_count}[/bold])"
    )


def handle_bead_note(args: argparse.Namespace) -> None:
    edit_ordinal = getattr(args, "edit", None)
    remove_ordinal = getattr(args, "remove", None)
    allow_sensitive = bool(getattr(args, "allow_sensitive", False))
    attachments_on = _note_attachments_enabled()
    local_only = bool(getattr(args, "local_only", False)) and attachments_on
    text = args.text

    if edit_ordinal is not None and not text:
        print("Error: --edit requires note text", file=sys.stderr)
        sys.exit(1)
    if remove_ordinal is not None and text:
        print("Error: --remove does not take note text", file=sys.stderr)
        sys.exit(1)
    if edit_ordinal is None and remove_ordinal is None and not text:
        print("Error: note text is required", file=sys.stderr)
        sys.exit(1)

    if isinstance(text, list) and text:
        try:
            if len(text) == 1:
                if attachments_on:
                    text = read_note_text_value(
                        text[0], target="note text", bead_id=args.id
                    )
                else:
                    text = read_at_path_value(text[0], target="note text")
            else:
                text = " ".join(text)
        except CliFileValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)

    bead_context = resolve_bead_operation_context([args.id], for_write=True)
    issue_id = bead_context.resolved_ids[0]
    echo_rows: list[str] = []
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
            stored_text = str(text)
            manifest: list[dict[str, Any]] | None = None
            if attachments_on and remove_ordinal is None:
                authored = _author_note_text(
                    mutation,
                    issue_id,
                    str(text),
                    edit_ordinal=edit_ordinal,
                    allow_sensitive=allow_sensitive,
                )
                stored_text = authored.stored_text
                manifest = authored.attachments
                echo_rows = authored.echo_rows
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
                        attachments_on=attachments_on,
                    )
                    placement_wires = list(manifest)
            if edit_ordinal is not None:
                issue = mutation.project.edit_note(
                    issue_id,
                    edit_ordinal,
                    stored_text,
                    author=author,
                    attachments=manifest,
                )
                operation = "note_edit"
            elif remove_ordinal is not None:
                issue = mutation.project.remove_note(
                    issue_id, remove_ordinal, author=author
                )
                operation = "note_remove"
            else:
                issue = mutation.project.append_note(
                    issue_id,
                    stored_text,
                    author=author,
                    attachments=(manifest or None),
                )
                operation = "note"
        except KeyError:
            print(f"Error: issue not found: {args.id}", file=sys.stderr)
            sys.exit(1)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        if placement in ("git", "large", "mixed") and placement_wires:
            from sase.bead.attachments.upload import post_write_queue

            post_write_queue(
                mutation,
                placement_wires,
                echo_rows,
                placement=placement,
                stores=placement_store,
                project_key=placement_key,
                require_upload=placement_require,
                attachments_on=attachments_on,
            )
        mutation.commit(require_mutation_commit_message(operation, [issue.id]))

    print_attachment_echo_rows(echo_rows)
    if edit_ordinal is not None:
        print(f"Note #{edit_ordinal} edited: {issue.id} — {issue.title}")
    elif remove_ordinal is not None:
        print(f"Note #{remove_ordinal} removed: {issue.id} — {issue.title}")
    else:
        print(f"Noted: {issue.id} — {issue.title}")


def _author_note_text(
    mutation: Any,
    issue_id: str,
    text: str,
    *,
    edit_ordinal: int | None,
    allow_sensitive: bool,
) -> AuthoredNoteAttachments:
    """Run the attachment authoring service over note text.

    Returns the composed stored text, the manifest to persist, and the
    echo rows. Exits non-zero when the text has attachment problems;
    nothing is written then.
    """
    from sase.bead.attachments.authoring import (
        NoteAttachmentAuthoringError,
        author_note_attachments,
    )

    current = mutation.project.show(issue_id)
    previous: tuple[str, ...] = ()
    if edit_ordinal is not None and 1 <= edit_ordinal <= len(current.notes):
        previous = tuple(
            attachment.name
            for attachment in current.notes[edit_ordinal - 1].attachments
        )
    from sase.bead.attachments.progress import transfer_progress

    try:
        authored = author_note_attachments(
            text,
            notes=current.notes,
            cwd=Path.cwd(),
            allow_sensitive=allow_sensitive,
            previous_manifest=previous,
            progress_factory=transfer_progress,
        )
    except NoteAttachmentAuthoringError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    return authored
