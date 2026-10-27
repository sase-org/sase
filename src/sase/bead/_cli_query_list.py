"""Listing handlers for the read-only bead CLI."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from sase.bead.cli_common import get_read_view
from sase.bead.cli_dep_render import resolve_color
from sase.bead.cli_detail import (
    artifact_reference_context,
    design_paths_are_relative,
    plan_reference_roots,
)
from sase.bead.cli_query_render import (
    render_list_compact,
    render_list_full,
    render_list_json,
)
from sase.bead.model import BeadTier, Issue, IssueType, Status
from sase.bead_summary_presentation import (
    BeadSummaryRow,
    bead_list_summary_line,
    summarize_bead_rows,
)
from sase.task_types import issue_matches_task_types


DEFAULT_CLOSED_LIST_LIMIT = 20

DEFAULT_LIST_STATUSES = [
    Status.OPEN,
    Status.CLAIMED,
    Status.READY,
    Status.SNOOZED,
    Status.IN_PROGRESS,
]
ALL_LIST_STATUSES = [
    *DEFAULT_LIST_STATUSES,
    Status.CLOSED,
]


def handle_bead_list(args: argparse.Namespace) -> None:
    use_color = resolve_color(getattr(args, "color", "auto"))
    window = _resolve_created_window(args)
    with get_read_view() as view:
        explicit_statuses = args.status is not None
        statuses = (
            _list_statuses(args.status)
            if explicit_statuses
            else list(DEFAULT_LIST_STATUSES)
        )
        issue_types = [IssueType(t) for t in args.type] if args.type else None
        tiers = [BeadTier(t) for t in args.tier] if args.tier else None
        task_types = getattr(args, "task_type", None)
        explicit_limit = getattr(args, "limit", None) is not None
        if window == (None, None):
            # Pushdown lane: task-type filtering, the newest-N limit, and
            # the pre-limit total all resolve inside the read model, so
            # bounded listings never hydrate the rows they drop.
            limit = getattr(args, "limit", None)
            if limit is None and Status.CLOSED in statuses:
                limit = DEFAULT_CLOSED_LIST_LIMIT
            total, issues = view.list_issue_page(
                statuses=statuses,
                issue_types=issue_types,
                tiers=tiers,
                task_types=task_types,
                limit=limit,
            )
            implicit_closed = False
            if not issues and not explicit_statuses:
                statuses = [Status.CLOSED]
                limit = getattr(args, "limit", None)
                if limit is None:
                    limit = DEFAULT_CLOSED_LIST_LIMIT
                total, issues = view.list_issue_page(
                    statuses=statuses,
                    issue_types=issue_types,
                    tiers=tiers,
                    task_types=task_types,
                    limit=limit,
                )
                implicit_closed = bool(issues)
        else:
            issues = _filter_by_task_type(
                _filter_by_created_window(
                    view.list_issues(
                        statuses=statuses, issue_types=issue_types, tiers=tiers
                    ),
                    window=window,
                ),
                task_types,
            )
            implicit_closed = False
            if not issues and not explicit_statuses:
                issues = _filter_by_task_type(
                    _filter_by_created_window(
                        view.list_issues(
                            statuses=[Status.CLOSED],
                            issue_types=issue_types,
                            tiers=tiers,
                        ),
                        window=window,
                    ),
                    task_types,
                )
                statuses = [Status.CLOSED]
                implicit_closed = bool(issues)
            total = len(issues)
            limit = getattr(args, "limit", None)
            if limit:
                issues = issues[-limit:]
        summary_rows: Sequence[BeadSummaryRow] = issues
        summary = summarize_bead_rows(summary_rows, matched=total)
        implicit_limit = not explicit_limit
        summary_line = bead_list_summary_line(
            summary,
            use_color=use_color,
            implicit_limit=implicit_limit,
        )

        match args.format:
            case "compact":
                if not issues:
                    print("No issues found.")
                    return
                if implicit_closed:
                    print("No open beads to show — defaulting to --status closed.")
                print(render_list_compact(issues, use_color=use_color), end="")
                print(f"\n{summary_line}")
            case "json":
                print(
                    render_list_json(
                        issues,
                        total=total,
                        statuses=statuses,
                        implied_status_closed=implicit_closed,
                        summary=summary,
                    ),
                    end="",
                )
            case "full":
                if not issues:
                    print("No issues found.")
                    return
                if implicit_closed:
                    print("No open beads to show — defaulting to --status closed.")
                print(
                    render_list_full(
                        view,
                        issues,
                        relativize_design=design_paths_are_relative(),
                        plan_roots=plan_reference_roots(),
                        reference_context=(
                            artifact_reference_context()
                            if any(issue.refs for issue in issues)
                            else None
                        ),
                    ),
                    end="",
                )
                print(f"\n{summary_line}")
            case _:
                raise AssertionError(f"unknown list format: {args.format}")


def _list_statuses(values: list[str]) -> list[Status]:
    if "all" in values:
        return list(ALL_LIST_STATUSES)
    return [Status(value) for value in values]


def _resolve_created_window(args: argparse.Namespace) -> tuple[int | None, int | None]:
    since_text = getattr(args, "since", None)
    until_text = getattr(args, "until", None)
    if since_text is None and until_text is None:
        return (None, None)

    from sase.core import time as core_time
    from sase.vcs_log.dates import (
        VcsLogDateError,
        normalize_reference_time,
        parse_time_bound,
    )

    reference = normalize_reference_time(core_time.local_now())
    try:
        since = (
            parse_time_bound(since_text).resolve(now=reference, boundary="since")
            if since_text
            else None
        )
        until = (
            parse_time_bound(until_text).resolve(now=reference, boundary="until")
            if until_text
            else None
        )
    except VcsLogDateError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(2)
    if since is not None and until is not None and since > until:
        print("Error: --since must not be later than --until", file=sys.stderr)
        sys.exit(2)
    return (since, until)


def _filter_by_task_type(
    issues: list[Issue],
    task_types: list[str] | None,
) -> list[Issue]:
    if not task_types:
        return issues
    return [
        issue
        for issue in issues
        if issue_matches_task_types(issue.task_type, task_types)
    ]


def _filter_by_created_window(
    issues: list[Issue],
    *,
    window: tuple[int | None, int | None],
) -> list[Issue]:
    since, until = window
    if since is None and until is None:
        return issues
    return [
        issue
        for issue in issues
        if _issue_created_in_window(issue, since=since, until=until)
    ]


def _issue_created_in_window(
    issue: Issue,
    *,
    since: int | None,
    until: int | None,
) -> bool:
    from sase.core.time import parse_local

    created = parse_local(issue.created_at)
    if created is None:
        return False
    created_epoch = int(created.timestamp())
    if since is not None and created_epoch < since:
        return False
    if until is not None and created_epoch > until:
        return False
    return True
