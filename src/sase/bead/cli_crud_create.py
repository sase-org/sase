"""Bead store initialization and bead creation CLI command handlers."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from sase.bead.cli_common import (
    auto_commit_bead_store,
    bead_store_mutation,
    find_beads_location,
    init_beads,
    storage_plan_path,
)
from sase.bead.model import BeadTier, FlagRecord, IssueType
from sase.bead.mutation_commit import require_mutation_commit_message
from sase.task_types import (
    TaskTypeCreateError,
    parse_field_args,
    resolve_created_task_type,
)

_TYPE_ARG_USAGE = (
    "plan(<plan_file>), plan(<plan_file>,<parent_id>), "
    "phase(<parent_id>), flag(<key>,<YYYY-MM-DD>,<release>), "
    "task, or task(<slug>)"
)


def handle_bead_init(args: argparse.Namespace) -> None:
    root, beads_dirname = find_beads_location(materialize=True)
    beads_path = root / beads_dirname
    if beads_path.exists():
        print(f"Already initialized: {beads_path}")
        return
    init_beads(root, beads_dirname)
    print(f"Initialized {beads_dirname}/ in {root}")


def parse_type_arg(
    value: str,
) -> tuple[IssueType, str | None, str | None, FlagRecord | None, str]:
    """Parse the ``--type`` argument into type metadata.

    Returns ``(issue_type, plan_path, parent_id, flag, task_type)``.

    Accepted forms:
    - ``task``                              -> TASK, untyped
    - ``task(<slug>)``                      -> TASK, task_type=slug
    - ``plan(<path>)``                      -> PLAN, design=path
    - ``plan(<path>,<parent_id>)``          -> PLAN, design=path, parent_id
    - ``phase(<parent_id>)``                -> PHASE, parent_id
    - ``flag(<key>,<YYYY-MM-DD>,<release>)`` -> FLAG, flag=FlagRecord(...)
    """
    if value == "task":
        return IssueType.TASK, None, None, None, ""

    m = re.match(r"^(plan|phase|flag|task)\((.+)\)$", value)
    if not m:
        print(
            f"Error: invalid --type value: {value}\nExpected: {_TYPE_ARG_USAGE}",
            file=sys.stderr,
        )
        sys.exit(1)

    kind, inner = m.group(1), m.group(2)
    parts = [p.strip() for p in inner.split(",")]

    if kind == "plan":
        if len(parts) == 1:
            return IssueType.PLAN, parts[0], None, None, ""
        if len(parts) == 2:
            return IssueType.PLAN, parts[0], parts[1], None, ""
        print(
            f"Error: plan() expects 1 or 2 arguments, got {len(parts)}",
            file=sys.stderr,
        )
        sys.exit(1)
    if kind == "phase":
        if len(parts) == 1:
            return IssueType.PHASE, None, parts[0], None, ""
        print(
            f"Error: phase() expects exactly 1 argument, got {len(parts)}",
            file=sys.stderr,
        )
        sys.exit(1)
    if kind == "task":
        if len(parts) == 1 and parts[0]:
            return IssueType.TASK, None, None, None, parts[0]
        print(
            f"Error: task() expects exactly 1 argument, got {len(parts)}",
            file=sys.stderr,
        )
        sys.exit(1)
    if len(parts) == 3:
        return (
            IssueType.FLAG,
            None,
            None,
            FlagRecord(
                key=parts[0], remove_by_date=parts[1], remove_by_release=parts[2]
            ),
            "",
        )
    print(
        f"Error: flag() expects exactly 3 arguments, got {len(parts)}",
        file=sys.stderr,
    )
    sys.exit(1)


def handle_bead_create(args: argparse.Namespace) -> None:
    issue_type, plan_path, parent_id, flag_record, task_type = parse_type_arg(args.type)
    try:
        field_values = parse_field_args(getattr(args, "field", None))
        if field_values and issue_type != IssueType.TASK:
            raise TaskTypeCreateError(
                "-f/--field can only be set on task beads created with "
                "-T 'task(<slug>)'"
            )
        task_type, field_values = resolve_created_task_type(task_type, field_values)
    except TaskTypeCreateError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    changespec_name = (
        getattr(args, "patch", None)
        or getattr(args, "changespec", None)  # legacy CLI alias
        or ""
    )
    changespec_bug_id = getattr(args, "bug_id", None) or ""
    if issue_type != IssueType.PLAN and (changespec_name or changespec_bug_id):
        print(
            "Error: Patch metadata can only be attached to plan beads",
            file=sys.stderr,
        )
        sys.exit(1)
    if changespec_bug_id and not changespec_name:
        print("Error: --bug-id requires --patch/--changespec", file=sys.stderr)
        sys.exit(1)
    tier = BeadTier(args.tier) if getattr(args, "tier", None) else None
    if issue_type != IssueType.PLAN and tier is not None:
        print("Error: --tier can only be set on plan beads", file=sys.stderr)
        sys.exit(1)
    size = getattr(args, "size", None)
    if issue_type == IssueType.TASK and size is None:
        print(
            "Error: task beads require -z/--size "
            "(xsmall, small, medium, large, or xlarge)",
            file=sys.stderr,
        )
        sys.exit(1)
    if issue_type == IssueType.PLAN and size is not None:
        print("Error: --size can only be set on phase or task beads", file=sys.stderr)
        sys.exit(1)
    design = ""
    resolved_plan_file: Path | None = None
    if plan_path:
        plan_file = Path(plan_path)
        if not plan_file.exists():
            print(f"Error: plan file not found: {plan_path}", file=sys.stderr)
            sys.exit(1)
        resolved_plan_file = plan_file.resolve()
        design = storage_plan_path(resolved_plan_file)

    from sase.bead.attribution import plan_proposed_by, resolve_bead_creator

    creator = resolve_bead_creator(
        issue_type=issue_type,
        plan_proposed_by=(
            plan_proposed_by(resolved_plan_file)
            if resolved_plan_file is not None
            else None
        ),
    )

    prefix_repair: tuple[str, str] | None = None
    with bead_store_mutation(auto_commit_bead_store) as mutation:
        proj = mutation.project
        if parent_id:
            try:
                parent_id = proj.show(parent_id).id
            except KeyError:
                print(f"Error: parent bead not found: {parent_id}", file=sys.stderr)
                sys.exit(1)
            except ValueError as exc:
                print(f"Error: {exc}", file=sys.stderr)
                sys.exit(1)

        try:
            issue = proj.create(
                title=args.title,
                issue_type=issue_type,
                parent_id=parent_id,
                description=args.description or "",
                assignee=args.assignee or "",
                design=design,
                refs=getattr(args, "ref", None) or (),
                tier=tier,
                changespec_name=changespec_name,
                changespec_bug_id=changespec_bug_id,
                external_ref=getattr(args, "external_ref", None) or "",
                flag=flag_record,
                model=getattr(args, "model", None) or "",
                size=size,
                created_by=creator,
                task_type=task_type,
                task_type_fields=field_values,
            )
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        prefix_repair = proj.last_prefix_repair
        mutation.commit(require_mutation_commit_message("create", [issue.id]))
    if prefix_repair is not None:
        from sase.bead.cli_work_from_plan_render import render_prefix_repair

        render_prefix_repair(*prefix_repair)
    print(f"Created {issue.issue_type.value}: {issue.id} — {issue.title}")
