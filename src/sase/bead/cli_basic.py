"""General bead CLI command handlers."""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

from sase.bead.cli_common import (
    find_beads_location,
    get_project,
    get_read_view,
    init_beads,
    normalize_workspace_path,
    status_icon,
)
from sase.bead.model import IssueType, Status


def handle_bead_init(args: argparse.Namespace) -> None:
    root, beads_dirname = find_beads_location()
    beads_path = root / beads_dirname
    if beads_path.exists():
        print(f"Already initialized: {beads_path}")
        return
    init_beads(root, beads_dirname)
    print(f"Initialized {beads_dirname}/ in {root}")


def _parse_type_arg(value: str) -> tuple[IssueType, str | None, str | None]:
    """Parse the ``--type`` argument into (issue_type, plan_path, parent_id).

    Accepted forms:
    - ``plan(<path>)``                → PLAN, design=path, parent_id=None
    - ``plan(<path>,<parent_id>)``    → PLAN, design=path, parent_id=parent_id
    - ``phase(<parent_id>)``          → PHASE, design=None, parent_id=parent_id
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
    issue_type, plan_path, parent_id = _parse_type_arg(args.type)
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

    # Validate plan file exists and resolve path for the design field
    design = ""
    if plan_path:
        plan_file = Path(plan_path)
        if not plan_file.exists():
            print(f"Error: plan file not found: {plan_path}", file=sys.stderr)
            sys.exit(1)
        design = str(normalize_workspace_path(plan_file.resolve()))

    with get_project() as proj:
        # Validate parent exists
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


def handle_bead_list(args: argparse.Namespace) -> None:
    with get_read_view() as view:
        statuses = (
            [Status(s) for s in args.status]
            if args.status
            else [Status.OPEN, Status.IN_PROGRESS]
        )
        issue_types = [IssueType(t) for t in args.type] if args.type else None
        issues = view.list_issues(statuses=statuses, issue_types=issue_types)
        if not issues:
            print("No issues found.")
            return
        for issue in issues:
            icon = status_icon(issue.status)
            parent = f" ← {issue.parent_id}" if issue.parent_id else ""
            print(f"{icon} {issue.id} · {issue.title}{parent}")


def handle_bead_show(args: argparse.Namespace) -> None:
    with get_read_view() as view:
        try:
            issue = view.show(args.id)
        except KeyError:
            print(f"Error: issue not found: {args.id}", file=sys.stderr)
            sys.exit(1)

        icon = status_icon(issue.status)
        print(f"{icon} {issue.id} · {issue.title}   [{issue.status.value.upper()}]")
        print(f"Type: {issue.issue_type.value} · Owner: {issue.owner or '(none)'}")
        if issue.assignee:
            print(f"Assignee: {issue.assignee}")
        if issue.parent_id:
            try:
                parent = view.show(issue.parent_id)
                print(
                    f"\nPARENT\n  ↑ {parent.id} · {parent.title}"
                    f"   [{parent.status.value.upper()}]"
                )
            except KeyError:
                print(f"\nPARENT\n  ↑ {issue.parent_id}")
        # Show children if plan
        if issue.issue_type == IssueType.PLAN:
            children = view.get_epic_children(issue.id)
            if children:
                print("\nCHILDREN")
                for c in children:
                    ci = status_icon(c.status)
                    print(f"  {ci} {c.id}: {c.title}")
        # Show dependencies
        deps_on = list(issue.dependencies)
        if deps_on:
            print("\nDEPENDS ON")
            for d in deps_on:
                try:
                    dep_issue = view.show(d.depends_on_id)
                    di = status_icon(dep_issue.status)
                    print(
                        f"  → {di} {dep_issue.id}: {dep_issue.title}"
                        f"   [{dep_issue.status.value.upper()}]"
                    )
                except KeyError:
                    print(f"  → {d.depends_on_id} (not found)")
        # Show what this blocks
        all_issues = view.list_issues()
        blocks: list[str] = []
        for other in all_issues:
            for d in other.dependencies:
                if d.depends_on_id == issue.id:
                    blocks.append(other.id)
        if blocks:
            print("\nBLOCKS")
            for bid in blocks:
                try:
                    b = view.show(bid)
                    bi = status_icon(b.status)
                    print(f"  ← {bi} {b.id}: {b.title}   [{b.status.value.upper()}]")
                except KeyError:
                    print(f"  ← {bid} (not found)")
        if issue.description:
            print(f"\nDESCRIPTION\n  {issue.description}")
        if issue.notes:
            print(f"\nNOTES\n  {issue.notes}")
        if issue.issue_type == IssueType.PLAN and (
            issue.changespec_name or issue.changespec_bug_id
        ):
            print("\nCHANGESPEC")
            if issue.changespec_name:
                print(f"  Name: {issue.changespec_name}")
            if issue.changespec_bug_id:
                print(f"  Bug ID: {issue.changespec_bug_id}")
        if issue.design:
            from sase.sdd.beads import get_sdd_config

            if get_sdd_config():
                display = os.path.relpath(issue.design)
            else:
                display = issue.design
            print(f"\nPLAN\n  {display}")


def handle_bead_ready(args: argparse.Namespace) -> None:
    with get_read_view() as view:
        issues = view.ready()
        if not issues:
            print("No issues ready (all blocked or none open).")
            return
        for issue in issues:
            parent = f" ← {issue.parent_id}" if issue.parent_id else ""
            print(f"○ {issue.id} · {issue.title}{parent}")
        print(f"\n{'-' * 60}")
        print(f"Ready: {len(issues)} issues with no active blockers")


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


def handle_bead_dep(args: argparse.Namespace) -> None:
    if args.dep_action == "add":
        with get_project() as proj:
            dep = proj.add_dependency(args.issue, args.depends_on)
            print(f"✓ Added dependency: {dep.issue_id} depends on {dep.depends_on_id}")
    else:
        print(f"Unknown dep action: {args.dep_action}", file=sys.stderr)
        sys.exit(1)


def handle_bead_blocked(args: argparse.Namespace) -> None:
    with get_read_view() as view:
        issues = view.blocked()
        if not issues:
            print("No blocked issues.")
            return
        for issue in issues:
            blockers = [d.depends_on_id for d in issue.dependencies]
            blocker_str = ", ".join(blockers)
            print(f"● {issue.id} · {issue.title}  [blocked by: {blocker_str}]")


def handle_bead_sync(args: argparse.Namespace) -> None:
    with get_project() as proj:
        if args.status:
            clean = proj.sync_is_clean()
            if clean:
                print("✓ JSONL is in sync with git")
            else:
                print("○ JSONL has uncommitted changes")
            return
        proj.sync()
        print("✓ Synced issues to git")


def handle_bead_stats(args: argparse.Namespace) -> None:
    with get_read_view() as view:
        s = view.stats()
        print("Issue Statistics")
        print(f"  Total:       {s.get('total', 0)}")
        print(f"  Open:        {s.get('open', 0)}")
        print(f"  In Progress: {s.get('in_progress', 0)}")
        print(f"  Closed:      {s.get('closed', 0)}")
        print(f"  Plans:       {s.get('plan', 0)}")
        print(f"  Phases:      {s.get('phase', 0)}")


def handle_bead_doctor(args: argparse.Namespace) -> None:
    with get_project() as proj:
        messages = proj.doctor()
        for msg in messages:
            print(msg)


def handle_bead_rm(args: argparse.Namespace) -> None:
    with get_project() as proj:
        try:
            removed = proj.remove(args.id)
        except KeyError:
            print(f"Error: issue not found: {args.id}", file=sys.stderr)
            sys.exit(1)
        for issue in removed:
            print(f"✗ Removed: {issue.id} — {issue.title}")


def handle_bead_onboard(args: argparse.Namespace) -> None:
    print("""sase bead — Lightweight git-native issue tracking

Quick Start:
  sase bead init                                 Create .sase_beads/ in current directory
  sase bead create -t "Fix bug" --type phase(<plan-id>)
  sase bead create -t "New feature" --type plan(plan.md)
  sase bead create -t "Sub-plan" --type plan(plan.md,<plan-id>)
  sase bead list                                 List all issues
  sase bead list --status=open                   List open issues
  sase bead ready                                Show issues ready to work
  sase bead show <id>                            View issue details
  sase bead update <id> --status=in_progress     Claim an issue
  sase bead close <id>                           Close an issue
  sase bead rm <id>                              Remove an issue (and children)
  sase bead dep add <issue> <depends-on>         Add dependency
  sase bead blocked                              Show blocked issues
  sase bead sync                                 Commit JSONL to git
  sase bead stats                                Project statistics
  sase bead doctor                               Health check
  sase bead work <epic>                          Mark an epic plan ready to work""")
