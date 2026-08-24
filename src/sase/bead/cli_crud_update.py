"""Field-update bead CLI command handler."""

from __future__ import annotations

import argparse
import sys
from typing import Any

from sase.bead.cli_common import auto_commit_bead_store, bead_store_mutation
from sase.bead.cli_crud_common import mutation_outcome_ids, resolve_mutation_author
from sase.bead.flag_fields import (
    FlagFields,
    flag_fields,
    is_flag_task_bead,
    replace_flag_thresholds,
)
from sase.bead.model import Issue
from sase.bead.mutation_commit import require_mutation_commit_message
from sase.cli_file_values import CliFileValueError, read_at_path_value


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
    try:
        description = (
            read_at_path_value(args.description, target="--description")
            if args.description is not None
            else None
        )
        note = (
            read_at_path_value(args.note, target="--note")
            if getattr(args, "note", None) is not None
            else None
        )
    except CliFileValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    if note is not None and not note.strip():
        print("Error: note entry cannot be empty or blank", file=sys.stderr)
        sys.exit(1)
    with bead_store_mutation(auto_commit_bead_store) as mutation:
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
            if len(args.ids) != 1:
                targets = ", ".join(args.ids)
                print(
                    "Error: --remove-by takes exactly one flag bead ID "
                    f"(got {len(args.ids)}: {targets})",
                    file=sys.stderr,
                )
                sys.exit(1)
            try:
                target = proj.show(args.ids[0])
            except KeyError:
                print(f"Error: issue not found: {args.ids[0]}", file=sys.stderr)
                sys.exit(1)
            current = flag_fields(target)
            if current is None:
                print(
                    f"Error: --remove-by requires a flag bead: {args.ids[0]}",
                    file=sys.stderr,
                )
                sys.exit(1)
            new_flag = _parse_remove_by_arg(args.remove_by, current.key)
            if not is_flag_task_bead(target):
                print(
                    f"Error: --remove-by requires a flag bead: {args.ids[0]}",
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
        try:
            if fields:
                issues = proj.update_many(args.ids, **fields)
                outcomes.append(proj.last_mutation_outcome)
            else:
                issues = [proj.show(issue_id) for issue_id in args.ids]
            if note is not None:
                author = resolve_mutation_author(proj)
                issues = proj.append_note_many(args.ids, note, author=author)
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
        if changed_ids:
            mutation.commit(require_mutation_commit_message("update", changed_ids))
    _print_update_results(
        issues,
        changed_ids=changed_ids,
        reopened_ancestors=reopened_ancestors,
    )
