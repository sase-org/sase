"""Field-update bead CLI command handler."""

from __future__ import annotations

import argparse
import sys
from typing import Any

from sase.bead.cli_common import auto_commit_bead_store, bead_store_mutation
from sase.bead.cli_crud_common import mutation_outcome_ids
from sase.bead.flag_codec import flag_to_dict
from sase.bead.model import FlagRecord, Issue, IssueType
from sase.bead.mutation_commit import require_mutation_commit_message


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


def _parse_remove_by_arg(value: str, existing_key: str) -> FlagRecord:
    """Parse ``--remove-by <YYYY-MM-DD>/<release>`` into a new flag record."""
    remove_by_date, sep, remove_by_release = value.partition("/")
    if not sep:
        print(
            f"Error: --remove-by expects <YYYY-MM-DD>/<release>: {value}",
            file=sys.stderr,
        )
        sys.exit(1)
    record = FlagRecord(
        key=existing_key,
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


def handle_bead_update(args: argparse.Namespace) -> None:
    if getattr(args, "task_type", None) is not None:
        print(f"Error: {_TASK_TYPE_IMMUTABLE_MESSAGE}", file=sys.stderr)
        sys.exit(1)
    with bead_store_mutation(auto_commit_bead_store) as mutation:
        proj = mutation.project
        fields: dict[str, Any] = {}
        if args.status:
            fields["status"] = args.status
        if args.title:
            fields["title"] = args.title
        if args.description is not None:
            fields["description"] = args.description
        if args.notes is not None:
            fields["notes"] = args.notes
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
            if target.issue_type != IssueType.FLAG or target.flag is None:
                print(
                    f"Error: --remove-by requires a flag bead: {args.ids[0]}",
                    file=sys.stderr,
                )
                sys.exit(1)
            new_flag = _parse_remove_by_arg(args.remove_by, target.flag.key)
            fields["flag"] = flag_to_dict(new_flag)
        if not fields:
            print("No fields to update.", file=sys.stderr)
            sys.exit(1)
        try:
            issues = proj.update_many(args.ids, **fields)
        except KeyError as exc:
            message = str(exc.args[0]) if exc.args else ""
            missing_id = message.rsplit("Issue not found:", 1)[-1].strip()
            print(f"Error: issue not found: {missing_id}", file=sys.stderr)
            sys.exit(1)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        outcome = mutation.project.last_mutation_outcome
        changed_ids = mutation_outcome_ids(outcome, "issue_ids")
        reopened_ancestor_ids = mutation_outcome_ids(outcome, "reopened_ancestor_ids")
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
