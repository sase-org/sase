"""CLI handlers for the 'sase bead' subcommand."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sase.bead.model import IssueType, Status
from sase.bead.project import BEADS_DIRNAME, BeadProject
from sase.bead.workspace import MergedBeadView, get_project_beads_dirs


def _find_project_root() -> Path:
    """Walk up from cwd to find a directory containing .sase_beads/.

    Falls back to the primary workspace via the sase workspace provider
    if no .sase_beads/ is found in ancestor directories.
    """
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        if (parent / BEADS_DIRNAME).is_dir():
            return parent

    # Fall back to workspace provider
    from sase.bead.workspace import resolve_primary_workspace

    primary = resolve_primary_workspace()
    if primary and (primary / BEADS_DIRNAME).is_dir():
        return primary

    return cwd


def _get_project() -> BeadProject:
    """Open the BeadProject for write operations."""
    root = _find_project_root()
    try:
        return BeadProject(root)
    except FileNotFoundError:
        print(
            f"Error: no {BEADS_DIRNAME}/ directory found. Run 'sase bead init' first.",
            file=sys.stderr,
        )
        sys.exit(1)


def _get_read_view() -> MergedBeadView | BeadProject:
    """Get a merged read view across all workspaces.

    Falls back to the local BeadProject if workspace resolution fails.
    """
    beads_dirs = get_project_beads_dirs()
    if beads_dirs:
        return MergedBeadView(beads_dirs)
    return _get_project()


def _status_icon(status: Status) -> str:
    return {"open": "○", "in_progress": "◐", "closed": "✓"}[status.value]


# --- Subcommand handlers ---


def handle_bead_init(args: argparse.Namespace) -> None:
    root = Path.cwd()
    if (root / BEADS_DIRNAME).exists():
        print(f"Already initialized: {BEADS_DIRNAME}/ exists")
        return
    with BeadProject.init(root):
        pass
    print(f"Initialized {BEADS_DIRNAME}/ in {root}")


def handle_bead_create(args: argparse.Namespace) -> None:
    plan_path: str | None = args.plan
    parent_id: str | None = args.parent

    if not plan_path and not parent_id:
        print(
            "Error: at least one of --plan or --parent is required.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Determine type: plan if --plan provided, phase otherwise
    issue_type = IssueType.PLAN if plan_path else IssueType.PHASE

    # Validate plan file exists and resolve path for the design field
    design = ""
    if plan_path:
        plan_file = Path(plan_path)
        if not plan_file.exists():
            print(f"Error: plan file not found: {plan_path}", file=sys.stderr)
            sys.exit(1)
        design = str(plan_file.resolve())

    with _get_project() as proj:
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
        )
        print(f"Created {issue.issue_type.value}: {issue.id} — {issue.title}")


def handle_bead_list(args: argparse.Namespace) -> None:
    with _get_read_view() as view:
        status = Status(args.status) if args.status else None
        issue_type = IssueType(args.type) if args.type else None
        issues = view.list_issues(status=status, issue_type=issue_type)
        if not issues:
            print("No issues found.")
            return
        for issue in issues:
            icon = _status_icon(issue.status)
            parent = f" ← {issue.parent_id}" if issue.parent_id else ""
            print(f"{icon} {issue.id} · {issue.title}{parent}")


def handle_bead_show(args: argparse.Namespace) -> None:
    with _get_read_view() as view:
        try:
            issue = view.show(args.id)
        except KeyError:
            print(f"Error: issue not found: {args.id}", file=sys.stderr)
            sys.exit(1)

        icon = _status_icon(issue.status)
        print(f"{icon} {issue.id} · {issue.title}   [{issue.status.value.upper()}]")
        print(f"Type: {issue.issue_type.value} · Owner: {issue.owner or '(none)'}")
        if issue.assignee:
            print(f"Assignee: {issue.assignee}")
        if issue.parent_id:
            print(f"\nPARENT\n  ↑ {issue.parent_id}")
        # Show children if plan
        if issue.issue_type == IssueType.PLAN:
            children = view.get_epic_children(issue.id)
            if children:
                print("\nCHILDREN")
                for c in children:
                    ci = _status_icon(c.status)
                    print(f"  {ci} {c.id}: {c.title}")
        # Show dependencies
        deps_on = list(issue.dependencies)
        if deps_on:
            print("\nDEPENDS ON")
            for d in deps_on:
                try:
                    dep_issue = view.show(d.depends_on_id)
                    di = _status_icon(dep_issue.status)
                    print(f"  → {di} {dep_issue.id}: {dep_issue.title}")
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
                    bi = _status_icon(b.status)
                    print(f"  ← {bi} {b.id}: {b.title}")
                except KeyError:
                    print(f"  ← {bid} (not found)")
        if issue.description:
            print(f"\nDESCRIPTION\n{issue.description}")
        if issue.notes:
            print(f"\nNOTES\n{issue.notes}")
        if issue.design:
            print(f"\nDESIGN\n{issue.design}")


def handle_bead_ready(args: argparse.Namespace) -> None:
    with _get_read_view() as view:
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
    with _get_project() as proj:
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
    with _get_project() as proj:
        try:
            closed = proj.close(args.ids, reason=args.reason)
        except KeyError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        for issue in closed:
            print(f"✓ Closed: {issue.id} — {issue.title}")


def handle_bead_dep(args: argparse.Namespace) -> None:
    if args.dep_action == "add":
        with _get_project() as proj:
            dep = proj.add_dependency(args.issue, args.depends_on)
            print(f"✓ Added dependency: {dep.issue_id} depends on {dep.depends_on_id}")
    else:
        print(f"Unknown dep action: {args.dep_action}", file=sys.stderr)
        sys.exit(1)


def handle_bead_blocked(args: argparse.Namespace) -> None:
    with _get_read_view() as view:
        issues = view.blocked()
        if not issues:
            print("No blocked issues.")
            return
        for issue in issues:
            blockers = [d.depends_on_id for d in issue.dependencies]
            blocker_str = ", ".join(blockers)
            print(f"● {issue.id} · {issue.title}  [blocked by: {blocker_str}]")


def handle_bead_sync(args: argparse.Namespace) -> None:
    with _get_project() as proj:
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
    with _get_read_view() as view:
        s = view.stats()
        print("Issue Statistics")
        print(f"  Total:       {s.get('total', 0)}")
        print(f"  Open:        {s.get('open', 0)}")
        print(f"  In Progress: {s.get('in_progress', 0)}")
        print(f"  Closed:      {s.get('closed', 0)}")
        print(f"  Plans:       {s.get('plan', 0)}")
        print(f"  Phases:      {s.get('phase', 0)}")


def handle_bead_doctor(args: argparse.Namespace) -> None:
    with _get_project() as proj:
        messages = proj.doctor()
        for msg in messages:
            print(msg)


def handle_bead_onboard(args: argparse.Namespace) -> None:
    print("""sase bead — Lightweight git-native issue tracking

Quick Start:
  sase bead init                                 Create .sase_beads/ in current directory
  sase bead create --title="Fix bug" --parent=<plan-id>
  sase bead create --title="New feature" --plan=plan.md
  sase bead create --title="Sub-plan" --plan=plan.md --parent=<plan-id>
  sase bead list                                 List all issues
  sase bead list --status=open                   List open issues
  sase bead ready                                Show issues ready to work
  sase bead show <id>                            View issue details
  sase bead update <id> --status=in_progress     Claim an issue
  sase bead close <id>                           Close an issue
  sase bead dep add <issue> <depends-on>         Add dependency
  sase bead blocked                              Show blocked issues
  sase bead sync                                 Commit JSONL to git
  sase bead stats                                Project statistics
  sase bead doctor                               Health check""")
