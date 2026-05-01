"""Create/update/delete bead CLI command handlers."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from sase.bead.cli_common import (
    find_beads_location,
    get_project,
    init_beads,
    normalize_workspace_path,
)
from sase.bead.model import IssueType


def handle_bead_init(args: argparse.Namespace) -> None:
    root, beads_dirname = find_beads_location()
    beads_path = root / beads_dirname
    if beads_path.exists():
        print(f"Already initialized: {beads_path}")
        return
    init_beads(root, beads_dirname)
    print(f"Initialized {beads_dirname}/ in {root}")


def parse_type_arg(value: str) -> tuple[IssueType, str | None, str | None]:
    """Parse the ``--type`` argument into (issue_type, plan_path, parent_id).

    Accepted forms:
    - ``plan(<path>)``                -> PLAN, design=path, parent_id=None
    - ``plan(<path>,<parent_id>)``    -> PLAN, design=path, parent_id=parent_id
    - ``phase(<parent_id>)``          -> PHASE, design=None, parent_id=parent_id
    """
    m = re.match(r"^(plan|phase)\((.+)\)$", value)
    if not m:
        print(
            f"Error: invalid --type value: {value}\n"
            "Expected: plan(<plan_file>), plan(<plan_file>,<parent_id>), or phase(<parent_id>)",
            file=sys.stderr,
        )
        sys.exit(1)

    kind, inner = m.group(1), m.group(2)
    parts = [p.strip() for p in inner.split(",")]

    if kind == "plan":
        if len(parts) == 1:
            return IssueType.PLAN, parts[0], None
        if len(parts) == 2:
            return IssueType.PLAN, parts[0], parts[1]
        print(
            f"Error: plan() expects 1 or 2 arguments, got {len(parts)}",
            file=sys.stderr,
        )
        sys.exit(1)
    else:  # phase
        if len(parts) == 1:
            return IssueType.PHASE, None, parts[0]
        print(
            f"Error: phase() expects exactly 1 argument, got {len(parts)}",
            file=sys.stderr,
        )
        sys.exit(1)


def handle_bead_create(args: argparse.Namespace) -> None:
    issue_type, plan_path, parent_id = parse_type_arg(args.type)
    changespec_name = getattr(args, "changespec", None) or ""
    changespec_bug_id = getattr(args, "bug_id", None) or ""
    if issue_type != IssueType.PLAN and (changespec_name or changespec_bug_id):
        print(
            "Error: ChangeSpec metadata can only be attached to plan beads",
            file=sys.stderr,
        )
        sys.exit(1)
    if changespec_bug_id and not changespec_name:
        print("Error: --bug-id requires --changespec", file=sys.stderr)
        sys.exit(1)

    design = ""
    if plan_path:
        plan_file = Path(plan_path)
        if not plan_file.exists():
            print(f"Error: plan file not found: {plan_path}", file=sys.stderr)
            sys.exit(1)
        design = str(normalize_workspace_path(plan_file.resolve()))

    with get_project() as proj:
        if parent_id:
            try:
                proj.show(parent_id)
            except KeyError:
                print(f"Error: parent bead not found: {parent_id}", file=sys.stderr)
                sys.exit(1)

        issue = proj.create(
            title=args.title,
            issue_type=issue_type,
            parent_id=parent_id,
            description=args.description or "",
            assignee=args.assignee or "",
            design=design,
            changespec_name=changespec_name,
            changespec_bug_id=changespec_bug_id,
        )
        print(f"Created {issue.issue_type.value}: {issue.id} — {issue.title}")


def handle_bead_update(args: argparse.Namespace) -> None:
    with get_project() as proj:
        fields: dict[str, str | None] = {}
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
        if not fields:
            print("No fields to update.", file=sys.stderr)
            sys.exit(1)
        try:
            issue = proj.update(args.id, **fields)
        except KeyError:
            print(f"Error: issue not found: {args.id}", file=sys.stderr)
            sys.exit(1)
        print(f"✓ Updated issue: {issue.id} — {issue.title}")


def handle_bead_close(args: argparse.Namespace) -> None:
    with get_project() as proj:
        try:
            closed = proj.close(args.ids, reason=args.reason)
        except KeyError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        for issue in closed:
            print(f"✓ Closed: {issue.id} — {issue.title}")


def handle_bead_rm(args: argparse.Namespace) -> None:
    with get_project() as proj:
        try:
            removed = proj.remove(args.id)
        except KeyError:
            print(f"Error: issue not found: {args.id}", file=sys.stderr)
            sys.exit(1)
        for issue in removed:
            print(f"✗ Removed: {issue.id} — {issue.title}")


_parse_type_arg = parse_type_arg
