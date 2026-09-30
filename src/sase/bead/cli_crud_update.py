"""Field-update bead CLI command handler."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.bead._project_mutations_shared import combine_mutation_outcomes
from sase.bead.cli_common import (
    auto_commit_bead_store,
    bead_store_mutation,
    resolve_bead_operation_context,
)
from sase.bead.cli_crud_common import (
    mutation_outcome_ids,
    print_attachment_echo_rows,
    resolve_mutation_author,
)
from sase.bead.flag_fields import (
    FlagFields,
    flag_fields,
    is_flag_task_bead,
    replace_flag_thresholds,
)
from sase.bead.model import Issue
from sase.bead.mutation_commit import require_mutation_commit_message
from sase.cli_file_values import (
    CliFileValueError,
    read_at_path_value,
    read_note_text_value,
)

if TYPE_CHECKING:
    from sase.bead.attachments.authoring import AuthoredNoteAttachments


def _print_update_results(
    issues: list[Issue],
    *,
    changed_ids: list[str],
    reopened_ancestors: list[Issue],
) -> None:
    changed = set(changed_ids)
    for issue in issues:
        if issue.id in changed:
            print(f"✓ Updated issue: {issue.id} — {issue.title}")
        else:
            print(f"· Unchanged: {issue.id} — {issue.title}")
    for ancestor in reopened_ancestors:
        print(f"○ Reopened ancestor: {ancestor.id} — {ancestor.title}")


def _parse_remove_by_arg(value: str, existing_key: str) -> FlagFields:
    """Parse ``--remove-by <YYYY-MM-DD>/<release>`` into new thresholds."""
    remove_by_date, sep, remove_by_release = value.partition("/")
    if not sep:
        print(
            f"Error: --remove-by expects <YYYY-MM-DD>/<release>: {value}",
            file=sys.stderr,
        )
        sys.exit(1)
    record = FlagFields(
        key=existing_key,
        kind="",
        remove_by_date=remove_by_date,
        remove_by_release=remove_by_release,
    )
    try:
        record.validate()
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    return record


_TASK_TYPE_IMMUTABLE_MESSAGE = (
    "task_type is immutable; close this bead and recreate it with -T 'task(<slug>)'"
)
_NOTES_TOMBSTONE_MESSAGE = (
    "`sase bead update --notes` was removed because it replaced the note log; "
    "use `sase bead note <id> <text>` to append one bead, or "
    "`sase bead update <ids...> --note <text>` to append to a batch."
)


def _author_update_notes(
    proj: Any,
    issue_ids: list[str],
    text: str,
    *,
    allow_sensitive: bool,
) -> list[tuple[str, AuthoredNoteAttachments]]:
    """Run the attachment authoring service once across every updated bead.

    Each unique path is ingested a single time, then the text is composed per
    bead against that bead's roster, so one filename can uniquify differently
    on each bead. Returns ``(resolved_id, authored)`` pairs in unique-bead
    order. Exits non-zero when the text has attachment problems; nothing is
    written then.
    """
    from sase.bead.attachments.authoring import (
        NoteAttachmentAuthoringError,
        author_note_attachments_per_bead,
    )

    resolved_ids = [proj.resolve_id(issue_id) for issue_id in issue_ids]
    unique_ids = list(dict.fromkeys(resolved_ids))
    notes_per_bead = [list(proj.show(resolved_id).notes) for resolved_id in unique_ids]
    from sase.bead.attachments.progress import transfer_progress

    try:
        results = author_note_attachments_per_bead(
            text,
            notes_per_bead,
            cwd=Path.cwd(),
            allow_sensitive=allow_sensitive,
            progress_factory=transfer_progress,
        )
    except NoteAttachmentAuthoringError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    return list(zip(unique_ids, results, strict=True))


def _combined_outcome_ids(outcomes: list[dict[str, object]], field: str) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for outcome in outcomes:
        for issue_id in mutation_outcome_ids(outcome, field):
            if issue_id not in seen:
                ids.append(issue_id)
                seen.add(issue_id)
    return ids


def handle_bead_update(args: argparse.Namespace) -> None:
    if getattr(args, "task_type", None) is not None:
        print(f"Error: {_TASK_TYPE_IMMUTABLE_MESSAGE}", file=sys.stderr)
        sys.exit(1)
    if getattr(args, "notes", None) is not None:
        print(f"Error: {_NOTES_TOMBSTONE_MESSAGE}", file=sys.stderr)
        sys.exit(1)
    allow_sensitive = bool(getattr(args, "allow_sensitive", False))
    local_only = bool(getattr(args, "local_only", False))
    try:
        description = (
            read_at_path_value(args.description, target="--description")
            if args.description is not None
            else None
        )
        note = (
            read_note_text_value(args.note, target="--note", bead_id=args.ids[0])
            if getattr(args, "note", None) is not None
            else None
        )
    except CliFileValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    if note is not None and not note.strip():
        print("Error: note entry cannot be empty or blank", file=sys.stderr)
        sys.exit(1)
    bead_context = resolve_bead_operation_context(args.ids, for_write=True)
    issue_ids = list(bead_context.resolved_ids)
    with bead_store_mutation(
        auto_commit_bead_store,
        bead_context=bead_context,
    ) as mutation:
        proj = mutation.project
        fields: dict[str, Any] = {}
        if args.status:
            fields["status"] = args.status
        if args.title:
            fields["title"] = args.title
        if description is not None:
            fields["description"] = description
        if args.design is not None:
            fields["design"] = args.design
        if args.assignee is not None:
            fields["assignee"] = args.assignee
        if getattr(args, "external_ref", None) is not None:
            fields["external_ref"] = args.external_ref
        if getattr(args, "clear_external_ref", False):
            fields["external_ref"] = ""
        if getattr(args, "tier", None) is not None:
            fields["tier"] = args.tier
        if getattr(args, "model", None) is not None:
            fields["model"] = args.model
        if getattr(args, "size", None) is not None:
            fields["size"] = args.size
        if getattr(args, "remove_by", None) is not None:
            if len(issue_ids) != 1:
                targets = ", ".join(issue_ids)
                print(
                    "Error: --remove-by takes exactly one flag bead ID "
                    f"(got {len(issue_ids)}: {targets})",
                    file=sys.stderr,
                )
                sys.exit(1)
            try:
                target = proj.show(issue_ids[0])
            except KeyError:
                print(f"Error: issue not found: {issue_ids[0]}", file=sys.stderr)
                sys.exit(1)
            current = flag_fields(target)
            if current is None:
                print(
                    f"Error: --remove-by requires a flag bead: {issue_ids[0]}",
                    file=sys.stderr,
                )
                sys.exit(1)
            new_flag = _parse_remove_by_arg(args.remove_by, current.key)
            if not is_flag_task_bead(target):
                print(
                    f"Error: --remove-by requires a flag bead: {issue_ids[0]}",
                    file=sys.stderr,
                )
                sys.exit(1)
            fields["task_type_fields"] = replace_flag_thresholds(
                target.task_type_fields,
                remove_by_date=new_flag.remove_by_date,
                remove_by_release=new_flag.remove_by_release,
            )
        if not fields and note is None:
            print("No fields to update.", file=sys.stderr)
            sys.exit(1)
        outcomes: list[dict[str, object]] = []
        echo_rows: list[str] = []
        placement = "skip"
        placement_store: Any | None = None
        placement_key: str | None = None
        placement_require = False
        placement_wires: list[dict[str, Any]] = []
        try:
            # Author attachments before any mutation: an attachment problem
            # must leave the bead store unchanged, including field updates.
            authored_per_bead: list[tuple[str, AuthoredNoteAttachments]] | None = None
            if note is not None:
                authored_per_bead = _author_update_notes(
                    proj,
                    issue_ids,
                    note,
                    allow_sensitive=allow_sensitive,
                )
                union_wires: list[dict[str, Any]] = []
                seen_digests: set[str] = set()
                for _, result in authored_per_bead:
                    for row in result.echo_rows:
                        if row not in echo_rows:
                            echo_rows.append(row)
                    for wire in result.attachments:
                        digest = str(wire.get("sha256") or wire.get("digest") or "")
                        if digest and digest not in seen_digests:
                            seen_digests.add(digest)
                            union_wires.append(wire)
                if union_wires:
                    from sase.bead.attachments.upload import pre_write_upload

                    (
                        placement,
                        placement_store,
                        placement_key,
                        placement_require,
                    ) = pre_write_upload(
                        union_wires,
                        echo_rows,
                        local_only=local_only,
                        bead_context=bead_context,
                    )
                    placement_wires = list(union_wires)
            if fields:
                issues = proj.update_many(issue_ids, **fields)
                outcomes.append(proj.last_mutation_outcome)
            else:
                issues = [proj.show(issue_id) for issue_id in issue_ids]
            if note is not None:
                author = resolve_mutation_author(proj)
                if authored_per_bead is not None:
                    note_outcomes: list[dict[str, object]] = []
                    appended: dict[str, Issue] = {}
                    for resolved_id, result in authored_per_bead:
                        appended[resolved_id] = proj.append_note(
                            resolved_id,
                            result.stored_text,
                            author=author,
                            attachments=(result.attachments or None),
                        )
                        note_outcomes.append(proj.last_mutation_outcome)
                    resolved_ids = [proj.resolve_id(issue_id) for issue_id in issue_ids]
                    issues = [appended[resolved_id] for resolved_id in resolved_ids]
                    outcomes.append(combine_mutation_outcomes("update", note_outcomes))
                else:
                    issues = proj.append_note_many(issue_ids, note, author=author)
                    outcomes.append(proj.last_mutation_outcome)
        except KeyError as exc:
            message = str(exc.args[0]) if exc.args else ""
            missing_id = message.rsplit("Issue not found:", 1)[-1].strip()
            print(f"Error: issue not found: {missing_id}", file=sys.stderr)
            sys.exit(1)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        changed_ids = _combined_outcome_ids(outcomes, "issue_ids")
        reopened_ancestor_ids = _combined_outcome_ids(outcomes, "reopened_ancestor_ids")
        reopened_ancestors = [
            proj.show(ancestor_id) for ancestor_id in reopened_ancestor_ids
        ]
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
            )
        if changed_ids:
            mutation.commit(require_mutation_commit_message("update", changed_ids))
    print_attachment_echo_rows(echo_rows)
    _print_update_results(
        issues,
        changed_ids=changed_ids,
        reopened_ancestors=reopened_ancestors,
    )
