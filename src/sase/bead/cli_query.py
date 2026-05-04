"""Read-only bead CLI command handlers."""

from __future__ import annotations

import argparse
import os
import sys

from sase.bead.cli_common import get_read_view, status_icon
from sase.bead.model import BeadTier, IssueType, Status


def handle_bead_list(args: argparse.Namespace) -> None:
    with get_read_view() as view:
        statuses = (
            [Status(s) for s in args.status]
            if args.status
            else [Status.OPEN, Status.IN_PROGRESS]
        )
        issue_types = [IssueType(t) for t in args.type] if args.type else None
        tiers = [BeadTier(t) for t in args.tier] if args.tier else None
        issues = view.list_issues(
            statuses=statuses, issue_types=issue_types, tiers=tiers
        )
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
        tier = f" · Tier: {issue.tier.value}" if issue.tier else ""
        print(
            f"Type: {issue.issue_type.value}{tier} · Owner: {issue.owner or '(none)'}"
        )
        if issue.assignee:
            print(f"Assignee: {issue.assignee}")
        if issue.epic_count is not None:
            print(f"Epic Count: {issue.epic_count}")
        if issue.parent_id:
            try:
                parent = view.show(issue.parent_id)
                print(
                    f"\nPARENT\n  ↑ {parent.id} · {parent.title}"
                    f"   [{parent.status.value.upper()}]"
                )
            except KeyError:
                print(f"\nPARENT\n  ↑ {issue.parent_id}")
        if issue.issue_type == IssueType.PLAN:
            children = view.get_epic_children(issue.id)
            if children:
                print("\nCHILDREN")
                for c in children:
                    ci = status_icon(c.status)
                    print(f"  {ci} {c.id}: {c.title}")
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
