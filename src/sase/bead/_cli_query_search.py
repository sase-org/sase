"""Search and status handlers for the read-only bead CLI."""

from __future__ import annotations

import argparse
import sys

from sase.bead.cli_common import get_read_view, status_icon
from sase.bead.cli_dep_render import resolve_color
from sase.bead.cli_detail import (
    artifact_reference_context,
    design_paths_are_relative,
    plan_reference_roots,
)
from sase.bead.cli_query_render import (
    compact_size_column,
    compact_size_column_width,
    invalid_search_regex_message,
    render_search_compact,
    render_search_full,
    render_search_json,
    row_badges,
)
from sase.bead.flag_fields import is_flag_bead
from sase.bead.model import BeadTier, IssueType, Status
from sase.bead_summary_presentation import summarize_bead_rows
from sase.bead._cli_query_list import ALL_LIST_STATUSES
from sase.task_types import issue_matches_task_types


def handle_bead_search(args: argparse.Namespace) -> None:
    if not args.query.strip():
        print("Error: search query cannot be empty", file=sys.stderr)
        sys.exit(2)

    use_color = resolve_color(getattr(args, "color", "auto"))
    regex = bool(getattr(args, "regex", False))
    with get_read_view() as view:
        statuses = [Status(s) for s in args.status] if args.status else None
        issue_types = [IssueType(t) for t in args.type] if args.type else None
        tiers = [BeadTier(t) for t in args.tier] if args.tier else None
        task_types = getattr(args, "task_type", None)
        requested_limit = args.limit
        try:
            matches = view.search(
                args.query,
                statuses=statuses,
                issue_types=issue_types,
                tiers=tiers,
                limit=None if task_types else requested_limit,
                regex=regex,
            )
        except ValueError as exc:
            if message := invalid_search_regex_message(exc):
                print(f"Error: {message}", file=sys.stderr)
                sys.exit(2)
            raise

        if task_types:
            matches = [
                match
                for match in matches
                if issue_matches_task_types(match.issue.task_type, task_types)
            ]
            if requested_limit:
                matches = matches[:requested_limit]

        match args.format:
            case "compact":
                print(
                    render_search_compact(
                        matches,
                        args.query,
                        regex,
                        use_color=use_color,
                    ),
                    end="",
                )
            case "json":
                print(render_search_json(matches, args.query, regex), end="")
            case "full":
                print(
                    render_search_full(
                        view,
                        matches,
                        args.query,
                        relativize_design=design_paths_are_relative(),
                        plan_roots=plan_reference_roots(),
                        reference_context=(
                            artifact_reference_context()
                            if any(match.issue.refs for match in matches)
                            else None
                        ),
                    ),
                    end="",
                )
            case _:
                raise AssertionError(f"unknown search format: {args.format}")


def handle_bead_ready(args: argparse.Namespace) -> None:
    with get_read_view() as view:
        issues = view.ready()
        if not issues:
            print("No ready task beads (epic work is preassigned at launch).")
            return
        size_width = compact_size_column_width(issues)
        for issue in issues:
            parent = f" ← {issue.parent_id}" if issue.parent_id else ""
            print(
                f"{status_icon(issue.status)} "
                f"{compact_size_column(issue, use_color=False, width=size_width)}"
                f"{issue.id} · "
                f"{issue.title}{row_badges(issue)}{parent}"
            )
        print(f"\n{'-' * 60}")
        suffix = "" if len(issues) == 1 else "s"
        print(f"Ready: {len(issues)} task bead{suffix} with no active blockers")


def handle_bead_blocked(args: argparse.Namespace) -> None:
    with get_read_view() as view:
        issues = view.blocked()
        if not issues:
            print("No blocked issues.")
            return
        size_width = compact_size_column_width(issues)
        for issue in issues:
            blockers = [d.depends_on_id for d in issue.dependencies]
            blocker_str = ", ".join(blockers)
            print(
                f"● {compact_size_column(issue, use_color=False, width=size_width)}"
                f"{issue.id} · {issue.title}{row_badges(issue)}"
                f"  [blocked by: {blocker_str}]"
            )


def handle_bead_stats(args: argparse.Namespace) -> None:
    with get_read_view() as view:
        s = view.stats()
        flags = [
            issue
            for issue in view.list_issues(
                statuses=ALL_LIST_STATUSES,
                issue_types=[IssueType.TASK],
            )
            if is_flag_bead(issue)
        ]
        flag_summary = summarize_bead_rows(flags, matched=len(flags))
        print("Issue Statistics")
        print(f"  Total:       {s.get('total', 0)}")
        print(f"  Open:        {s.get('open', 0)}")
        print(f"  Claimed:     {s.get('claimed', 0)}")
        print(f"  Ready:       {s.get('ready', 0)}")
        print(f"  Snoozed:     {s.get('snoozed', 0)}")
        print(f"  In Progress: {s.get('in_progress', 0)}")
        print(f"  Closed:      {s.get('closed', 0)}")
        print(f"  Plans:       {s.get('plan', 0)}")
        print(f"  Phases:      {s.get('phase', 0)}")
        print(f"  Tasks:       {s.get('task', 0)}")
        print(f"  Flags:       {len(flags)}")
        print(f"  Due Flags:   {flag_summary.due_flags}")
        print(f"  +1 Reports:  {s.get('plus_one', 0)}")
