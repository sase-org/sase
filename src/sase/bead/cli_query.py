"""Read-only bead CLI command handlers."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import replace

from sase.agent.names._registry import name_registry_load_session
from sase.bead.cli_common import created_cell, get_read_view, status_icon
from sase.bead.cli_dep_render import resolve_color
from sase.bead.cli_detail import (
    artifact_reference_context,
    design_paths_are_relative,
    plan_reference_roots,
    render_issue_detail,
    resolve_bead_creator_url,
    resolve_bead_page_url,
    resolve_issue_detail,
)
from sase.bead.cli_detail_links import (
    NO_LINKS_RECOVERY_HINT,
    assemble_bead_link_neighborhood,
)
from sase.bead.cli_detail_resolution import IssueDetail
from sase.bead.cli_detail_style import DetailStyle, resolve_detail_style
from sase.bead.cli_query_render import (
    compact_size_column as _compact_size_column,
    compact_size_column_width as _compact_size_column_width,
    invalid_search_regex_message as _invalid_search_regex_message,
    render_list_compact as _render_list_compact,
    render_list_full as _render_list_full,
    render_list_json as _render_list_json,
    render_search_compact as _render_search_compact,
    render_search_full as _render_search_full,
    render_search_json as _render_search_json,
    row_badges as _row_badges,
    search_field_value as _search_field_value,
)
from sase.bead.cli_show_batch import (
    build_show_batch_document,
    render_show_batch,
    render_show_document,
    resolve_show_batch,
)
from sase.bead.flag_fields import is_flag_bead
from sase.bead.model import (
    BeadTier,
    Issue,
    IssueType,
    Status,
)
from sase.bead_summary_presentation import (
    BeadSummaryRow,
    bead_list_summary_line,
    summarize_bead_rows,
)
from sase.main.parser_bead_common import resolve_wrap_width
from sase.cli_pager import PagerMode, page_or_print, resolve_pager_mode
from sase.markdown_width import markdown_print_width
from sase.task_types import issue_matches_task_types

# Closed bead listings can grow without bound, so default to the newest few
# rows when the user did not request an explicit ``--limit``.
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
        closed_in_scope = implicit_closed or Status.CLOSED in statuses
        explicit_limit = getattr(args, "limit", None) is not None
        limit = getattr(args, "limit", None)
        if limit is None and closed_in_scope and window == (None, None):
            limit = DEFAULT_CLOSED_LIST_LIMIT
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
                print(_render_list_compact(issues, use_color=use_color), end="")
                print(f"\n{summary_line}")
            case "json":
                print(
                    _render_list_json(
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
                    _render_list_full(
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


def handle_bead_show(args: argparse.Namespace) -> None:
    include_links = not bool(getattr(args, "no_links", False))
    ids = _show_ids(args)
    style = resolve_detail_style(
        style=getattr(args, "style", "auto"),
        color=getattr(args, "color", "auto"),
    )
    wrap = resolve_wrap_width(getattr(args, "wrap", markdown_print_width()))
    pager_mode: PagerMode = resolve_pager_mode(getattr(args, "pager", "auto"))
    pager_document = None

    with name_registry_load_session(), get_read_view() as view:
        batch = resolve_show_batch(
            view,
            ids,
            format_name=args.format,
            include_links=include_links,
            detail_enricher=_with_artifact_link_neighborhood if include_links else None,
        )
        if args.format == "full":
            document = build_show_batch_document(
                batch,
                style=style,
                wrap=wrap,
                relativize_design=design_paths_are_relative(),
                plan_roots=plan_reference_roots(),
                reference_context_factory=artifact_reference_context,
                creator_url_for=resolve_bead_creator_url,
                page_url_for=resolve_bead_page_url,
            )
            pager_document = document
            body = render_show_document(document, style=style, wrap=wrap)
        else:
            body = render_show_batch(
                batch,
                format_name=args.format,
                include_links=include_links,
                style=style,
                wrap=wrap,
                relativize_design=False,
                plan_roots=(),
                reference_context_factory=artifact_reference_context,
                creator_url_for=resolve_bead_creator_url,
                page_url_for=resolve_bead_page_url,
            )

    if body:
        page_or_print(body, mode=pager_mode, document=pager_document)
    for failure in batch.failures:
        print(f"Error: {failure.message}", file=sys.stderr)
    if batch.failures:
        sys.exit(1)


def _show_ids(args: argparse.Namespace) -> list[str]:
    ids = getattr(args, "ids", None)
    if ids is not None:
        return list(ids)
    return [str(args.id)]


def _with_artifact_link_neighborhood(detail: IssueDetail) -> IssueDetail:
    try:
        views = assemble_bead_link_neighborhood(
            bead_id=detail.issue.id,
            bead_owned_rows=detail.bead_owned_artifact_links,
            fallback_issue=detail.issue,
        )
    except (OSError, RuntimeError, ValueError, TypeError, AttributeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        print(f"Hint: {NO_LINKS_RECOVERY_HINT}.", file=sys.stderr)
        sys.exit(1)
    return replace(detail, artifact_links=views)


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
            if message := _invalid_search_regex_message(exc):
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
                    _render_search_compact(
                        matches,
                        args.query,
                        regex,
                        use_color=use_color,
                    ),
                    end="",
                )
            case "json":
                print(_render_search_json(matches, args.query, regex), end="")
            case "full":
                print(
                    _render_search_full(
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
        size_width = _compact_size_column_width(issues)
        for issue in issues:
            parent = f" ← {issue.parent_id}" if issue.parent_id else ""
            print(
                f"{status_icon(issue.status)} "
                f"{_compact_size_column(issue, use_color=False, width=size_width)}"
                f"{issue.id} · "
                f"{issue.title}{_row_badges(issue)}{parent}"
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
        size_width = _compact_size_column_width(issues)
        for issue in issues:
            blockers = [d.depends_on_id for d in issue.dependencies]
            blocker_str = ", ".join(blockers)
            print(
                f"● {_compact_size_column(issue, use_color=False, width=size_width)}"
                f"{issue.id} · {issue.title}{_row_badges(issue)}"
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
