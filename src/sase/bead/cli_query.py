"""Read-only bead CLI command handlers."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sase.bead.cli_common import get_read_view, status_icon
from sase.bead.model import BeadTier, IssueType, Status
from sase.daemon.read_facade import read_or_fallback
from sase.daemon.read_models import (
    bead_detail_from_dict,
    bead_list_from_dict,
    bead_stats_from_dict,
)


def handle_bead_list(args: argparse.Namespace) -> None:
    statuses = (
        [Status(s) for s in args.status]
        if args.status
        else [Status.OPEN, Status.IN_PROGRESS]
    )
    issue_types = [IssueType(t) for t in args.type] if args.type else None
    tiers = [BeadTier(t) for t in args.tier] if args.tier else None

    def direct() -> list[Any]:
        with get_read_view() as view:
            return view.list_issues(
                statuses=statuses, issue_types=issue_types, tiers=tiers
            )

    issues = _bead_read_result(
        "bead_list",
        args=args,
        direct_loader=direct,
        daemon_loader=lambda daemon, project_id: (
            bead_list_from_dict(
                daemon.bead_list(
                    project_id=project_id,
                    statuses=[status.value for status in statuses],
                    issue_types=(
                        None
                        if issue_types is None
                        else [row.value for row in issue_types]
                    ),
                    tiers=None if tiers is None else [row.value for row in tiers],
                )
            ).issues
        ),
    )
    if not issues:
        print("No issues found.")
        return
    for issue in issues:
        icon = status_icon(issue.status)
        parent = f" ← {issue.parent_id}" if issue.parent_id else ""
        print(f"{icon} {issue.id} · {issue.title}{parent}")


def handle_bead_show(args: argparse.Namespace) -> None:
    def direct() -> tuple[Any, list[Any]]:
        with get_read_view() as view:
            issue = view.show(args.id)
            return issue, view.list_issues()

    try:
        issue, all_issues = _bead_read_result(
            "bead_show",
            args=args,
            direct_loader=direct,
            daemon_loader=lambda daemon, project_id: (
                bead_detail_from_dict(
                    daemon.bead_show(project_id=project_id, bead_id=args.id)
                ).issue,
                bead_list_from_dict(daemon.bead_list(project_id=project_id)).issues,
            ),
        )
    except KeyError:
        print(f"Error: issue not found: {args.id}", file=sys.stderr)
        sys.exit(1)

    _print_bead_show(issue, all_issues)


def handle_bead_ready(args: argparse.Namespace) -> None:
    def direct() -> list[Any]:
        with get_read_view() as view:
            return view.ready()

    issues = _bead_read_result(
        "bead_ready",
        args=args,
        direct_loader=direct,
        daemon_loader=lambda daemon, project_id: (
            bead_list_from_dict(daemon.bead_ready(project_id=project_id)).issues
        ),
    )
    if not issues:
        print("No issues ready (all blocked or none open).")
        return
    for issue in issues:
        parent = f" ← {issue.parent_id}" if issue.parent_id else ""
        print(f"○ {issue.id} · {issue.title}{parent}")
    print(f"\n{'-' * 60}")
    print(f"Ready: {len(issues)} issues with no active blockers")


def handle_bead_blocked(args: argparse.Namespace) -> None:
    def direct() -> list[Any]:
        with get_read_view() as view:
            return view.blocked()

    issues = _bead_read_result(
        "bead_blocked",
        args=args,
        direct_loader=direct,
        daemon_loader=lambda daemon, project_id: (
            bead_list_from_dict(daemon.bead_blocked(project_id=project_id)).issues
        ),
    )
    if not issues:
        print("No blocked issues.")
        return
    for issue in issues:
        blockers = [d.depends_on_id for d in issue.dependencies]
        blocker_str = ", ".join(blockers)
        print(f"● {issue.id} · {issue.title}  [blocked by: {blocker_str}]")


def handle_bead_stats(args: argparse.Namespace) -> None:
    def direct() -> dict[str, int]:
        with get_read_view() as view:
            return view.stats()

    stats = _bead_read_result(
        "bead_stats",
        args=args,
        direct_loader=direct,
        daemon_loader=lambda daemon, project_id: (
            bead_stats_from_dict(daemon.bead_stats(project_id=project_id)).stats
        ),
    )
    print("Issue Statistics")
    print(f"  Total:       {stats.get('total', 0)}")
    print(f"  Open:        {stats.get('open', 0)}")
    print(f"  In Progress: {stats.get('in_progress', 0)}")
    print(f"  Closed:      {stats.get('closed', 0)}")
    print(f"  Plans:       {stats.get('plan', 0)}")
    print(f"  Phases:      {stats.get('phase', 0)}")


@dataclass(frozen=True)
class _DaemonBeadContext:
    project_id: str


def _bead_read_result[T](
    surface: str,
    *,
    args: argparse.Namespace,
    direct_loader: Callable[[], T],
    daemon_loader: Callable[[Any, str], T],
) -> T:
    context = _current_bead_daemon_context()
    if context is None:
        return direct_loader()
    return read_or_fallback(
        surface,
        args=args,
        daemon_loader=lambda daemon: daemon_loader(daemon, context.project_id),
        direct_loader=direct_loader,
    ).value


def _current_bead_daemon_context() -> _DaemonBeadContext | None:
    from sase.bead.cli_common import find_beads_location
    from sase.bead.project_name import infer_project_name_from_cwd
    from sase.bead.workspace import get_project_beads_dirs_for_project

    project_id = infer_project_name_from_cwd()
    if project_id is None:
        return None

    root, beads_dirname = find_beads_location()
    selected = (root / beads_dirname).resolve()
    canonical_dirs = get_project_beads_dirs_for_project(project_id)
    if not canonical_dirs or len(canonical_dirs) != 1:
        return None
    try:
        canonical = canonical_dirs[0].resolve()
    except OSError:
        return None
    if canonical != selected:
        return None
    return _DaemonBeadContext(project_id=project_id)


def _print_bead_show(issue: Any, all_issues: list[Any]) -> None:
    issue_by_id = {row.id: row for row in all_issues}
    icon = status_icon(issue.status)
    print(f"{icon} {issue.id} · {issue.title}   [{issue.status.value.upper()}]")
    tier = f" · Tier: {issue.tier.value}" if issue.tier else ""
    print(f"Type: {issue.issue_type.value}{tier} · Owner: {issue.owner or '(none)'}")
    if issue.assignee:
        print(f"Assignee: {issue.assignee}")
    if issue.model:
        print(f"Model: {issue.model}")
    if issue.epic_count is not None:
        print(f"Epic Count: {issue.epic_count}")
    if issue.parent_id:
        parent = issue_by_id.get(issue.parent_id)
        if parent is None:
            print(f"\nPARENT\n  ↑ {issue.parent_id}")
        else:
            print(
                f"\nPARENT\n  ↑ {parent.id} · {parent.title}"
                f"   [{parent.status.value.upper()}]"
            )
    if issue.issue_type == IssueType.PLAN:
        children = [row for row in all_issues if row.parent_id == issue.id]
        if children:
            print("\nCHILDREN")
            for child in children:
                ci = status_icon(child.status)
                print(f"  {ci} {child.id}: {child.title}")
    deps_on = list(issue.dependencies)
    if deps_on:
        print("\nDEPENDS ON")
        for dependency in deps_on:
            dep_issue = issue_by_id.get(dependency.depends_on_id)
            if dep_issue is None:
                print(f"  → {dependency.depends_on_id} (not found)")
            else:
                di = status_icon(dep_issue.status)
                print(
                    f"  → {di} {dep_issue.id}: {dep_issue.title}"
                    f"   [{dep_issue.status.value.upper()}]"
                )
    blocks = [
        other.id
        for other in all_issues
        for dependency in other.dependencies
        if dependency.depends_on_id == issue.id
    ]
    if blocks:
        print("\nBLOCKS")
        for block_id in blocks:
            blocked = issue_by_id.get(block_id)
            if blocked is None:
                print(f"  ← {block_id} (not found)")
            else:
                bi = status_icon(blocked.status)
                print(
                    f"  ← {bi} {blocked.id}: {blocked.title}"
                    f"   [{blocked.status.value.upper()}]"
                )
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
