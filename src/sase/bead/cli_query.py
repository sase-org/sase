"""Read-only bead CLI command handlers."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable
from pathlib import Path

from rich.cells import cell_len

from sase.artifact_ref_models import ArtifactRefContext
from sase.bead.cli_common import created_cell, get_read_view, status_icon
from sase.bead.cli_dep_render import ANSI_BOLD_BLUE, resolve_color, styled
from sase.bead.cli_detail import (
    artifact_reference_context,
    design_paths_are_relative,
    issue_to_wire_dict,
    plan_reference_roots,
    render_issue_detail,
    render_issue_detail_json,
    resolve_bead_creator_url,
    resolve_bead_page_url,
    resolve_issue_detail,
)
from sase.bead.cli_detail_style import DetailStyle, resolve_detail_style
from sase.bead.model import (
    BeadSearchMatch,
    BeadTier,
    Issue,
    IssueType,
    Status,
)
from sase.bead.project import BeadProject
from sase.bead.plus_one_presentation import (
    PLUS_ONE_CLI_STYLE,
    POST_CLOSE_CLI_STYLE,
    post_close_plus_one_badge,
    post_close_plus_one_count,
    plus_one_badge,
    plus_one_evidence_search_text,
)
from sase.bead.reopen_presentation import (
    REOPEN_CLI_STYLE,
    close_history_search_text,
    reopen_badge,
)
from sase.bead_status_presentation import bead_status_presentation
from sase.bead_type_presentation import (
    BEAD_TYPE_VALUES,
    bead_type_cli_cell,
    bead_type_presentation,
)
from sase.main.parser_bead_common import resolve_wrap_width
from sase.markdown_width import markdown_print_width
from sase.phase_size_presentation import PHASE_SIZE_TOKEN_WIDTH, phase_size_cli_token

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
        issues = _filter_by_created_window(
            view.list_issues(statuses=statuses, issue_types=issue_types, tiers=tiers),
            window=window,
        )
        implicit_closed = False
        if not issues and not explicit_statuses:
            issues = _filter_by_created_window(
                view.list_issues(
                    statuses=[Status.CLOSED],
                    issue_types=issue_types,
                    tiers=tiers,
                ),
                window=window,
            )
            statuses = [Status.CLOSED]
            implicit_closed = bool(issues)
        total = len(issues)
        closed_in_scope = implicit_closed or Status.CLOSED in statuses
        limit = getattr(args, "limit", None)
        if limit is None and closed_in_scope and window == (None, None):
            limit = DEFAULT_CLOSED_LIST_LIMIT
        if limit:
            issues = issues[-limit:]

        match args.format:
            case "compact":
                if not issues:
                    print("No issues found.")
                    return
                if implicit_closed:
                    print("No open beads to show — defaulting to --status closed.")
                print(_render_list_compact(issues, use_color=use_color), end="")
            case "json":
                print(
                    _render_list_json(
                        issues,
                        total=total,
                        statuses=statuses,
                        implied_status_closed=implicit_closed,
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
    with get_read_view() as view:
        try:
            detail = None
            if args.format == "compact":
                issue = view.show(args.id)
            else:
                detail = resolve_issue_detail(view, args.id)
                issue = detail.issue
        except KeyError:
            print(f"Error: issue not found: {args.id}", file=sys.stderr)
            sys.exit(1)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)

        style = resolve_detail_style(
            style=getattr(args, "style", "auto"),
            color=getattr(args, "color", "auto"),
        )
        wrap = resolve_wrap_width(getattr(args, "wrap", markdown_print_width()))
        match args.format:
            case "compact":
                print(
                    _render_list_compact(
                        [issue], use_color=style is not DetailStyle.PLAIN
                    ),
                    end="",
                )
            case "json":
                assert detail is not None
                print(
                    render_issue_detail_json(
                        detail,
                        created_by_url=(
                            resolve_bead_creator_url(issue.created_by)
                            if issue.created_by
                            else None
                        ),
                        page_url=resolve_bead_page_url(issue.id),
                    ),
                    end="",
                )
            case "full":
                assert detail is not None
                reference_context = artifact_reference_context() if issue.refs else None
                print(
                    render_issue_detail(
                        detail,
                        relativize_design=design_paths_are_relative(),
                        plan_roots=plan_reference_roots(),
                        reference_context=reference_context,
                        creator_url=(
                            resolve_bead_creator_url(issue.created_by)
                            if issue.created_by
                            else None
                        ),
                        page_url=resolve_bead_page_url(issue.id),
                        style=style,
                        wrap=wrap,
                    ),
                    end="",
                )
            case _:
                raise AssertionError(f"unknown show format: {args.format}")


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
        try:
            matches = view.search(
                args.query,
                statuses=statuses,
                issue_types=issue_types,
                tiers=tiers,
                limit=args.limit,
                regex=regex,
            )
        except ValueError as exc:
            if message := _invalid_search_regex_message(exc):
                print(f"Error: {message}", file=sys.stderr)
                sys.exit(2)
            raise

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
        print(f"  +1 Reports:  {s.get('plus_one', 0)}")


def _row_badges(issue: Issue, *, use_color: bool = False) -> str:
    """Return the shared ``[+N]``/``[↺N]`` suffix for one bead row.

    Every row surface (list, ready, blocked, search) shares this so the two
    badges cannot appear in different orders or with different spacing.
    """
    badges = []
    if badge := plus_one_badge(issue.plus_one_count):
        badges.append(styled(f"[{badge}]", PLUS_ONE_CLI_STYLE, use_color))
    if reopened := reopen_badge(len(issue.close_history)):
        badges.append(styled(f"[{reopened}]", REOPEN_CLI_STYLE, use_color))
    if post_close := post_close_plus_one_badge(post_close_plus_one_count(issue)):
        badges.append(styled(f"[{post_close}]", POST_CLOSE_CLI_STYLE, use_color))
    return "".join(f" {badge}" for badge in badges)


def _compact_size_column_width(issues: list[Issue]) -> int:
    return (
        PHASE_SIZE_TOKEN_WIDTH if any(issue.size is not None for issue in issues) else 0
    )


def _compact_size_column(issue: Issue, *, use_color: bool, width: int) -> str:
    if width == 0:
        return ""
    return f"{phase_size_cli_token(issue.size, use_color=use_color, width=width)} "


def _render_list_compact(issues: list[Issue], *, use_color: bool) -> str:
    # Measured (not assumed) so the column stays aligned even though the three
    # type glyphs may not always share a Unicode width class.
    type_width = max(
        cell_len(bead_type_presentation(value).glyph) for value in BEAD_TYPE_VALUES
    )
    size_width = _compact_size_column_width(issues)
    lines = []
    for issue in issues:
        type_cell = bead_type_cli_cell(
            issue.issue_type, use_color=use_color, width=type_width
        )
        status = bead_status_presentation(issue.status)
        status_glyph = styled(status.glyph, status.cli_style, use_color)
        issue_id = styled(issue.id, ANSI_BOLD_BLUE, use_color)
        parent = f" ← {issue.parent_id}" if issue.parent_id else ""
        lines.append(
            f"{type_cell} {status_glyph} "
            f"{_compact_size_column(issue, use_color=use_color, width=size_width)}"
            f"{issue_id} · {issue.title}"
            f"{_row_badges(issue, use_color=use_color)}{parent}"
            f"{created_cell(issue, use_color=use_color)}"
        )
    return "\n".join(lines) + "\n"


def _render_list_full(
    view: BeadProject,
    issues: list[Issue],
    *,
    relativize_design: bool,
    plan_roots: tuple[Path, ...],
    reference_context: ArtifactRefContext | None = None,
) -> str:
    sections = [
        render_issue_detail(
            resolve_issue_detail(view, issue),
            relativize_design=relativize_design,
            plan_roots=plan_roots,
            reference_context=reference_context,
        ).rstrip("\n")
        for issue in issues
    ]
    return f"\n{'-' * 60}\n".join(sections) + "\n"


def _render_list_json(
    issues: list[Issue],
    *,
    total: int,
    statuses: list[Status],
    implied_status_closed: bool,
) -> str:
    envelope = {
        "count": len(issues),
        "total": total,
        "statuses": [status.value for status in statuses],
        "implied_status_closed": implied_status_closed,
        "results": [issue_to_wire_dict(issue) for issue in issues],
    }
    return json.dumps(envelope, indent=2) + "\n"


def _render_search_compact(
    matches: list[BeadSearchMatch],
    query: str,
    regex: bool = False,
    *,
    use_color: bool,
) -> str:
    if not matches:
        return f'No beads match "{query}".\n'

    type_width = max(
        cell_len(bead_type_presentation(value).glyph) for value in BEAD_TYPE_VALUES
    )
    size_width = _compact_size_column_width([match.issue for match in matches])
    lines: list[str] = []
    for match in matches:
        issue = match.issue
        type_cell = bead_type_cli_cell(
            issue.issue_type,
            use_color=use_color,
            width=type_width,
        )
        lines.append(
            f"{type_cell} {status_icon(issue.status)} "
            f"{_compact_size_column(issue, use_color=use_color, width=size_width)}"
            f"{issue.id} · "
            f"{issue.title}{_row_badges(issue, use_color=use_color)}"
            f"{created_cell(issue, use_color=use_color)}"
        )
        snippet = _compact_snippet(match, query, regex)
        if snippet:
            lines.append(f"  {snippet}")
    return "\n".join(lines) + "\n"


def _compact_snippet(match: BeadSearchMatch, query: str, regex: bool) -> str:
    issue = match.issue
    has_title_or_description_match = any(
        field in {"title", "description"} for field in match.matched_fields
    )
    description = _single_line_snippet(issue.description, query, regex=regex)
    if has_title_or_description_match and description:
        return description

    for field in match.matched_fields:
        if field == "title":
            continue
        value = _search_field_value(issue, field)
        snippet = _single_line_snippet(value, query, regex=regex)
        if snippet:
            return f'{field}: "{snippet}"'
    return ""


def _single_line_snippet(
    value: str,
    query: str,
    *,
    regex: bool = False,
    max_chars: int = 96,
) -> str:
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if not lines:
        return ""

    matches_line = _line_matcher(query, regex=regex)
    line = next(
        (line for line in lines if matches_line(line)),
        lines[0],
    )
    if len(line) <= max_chars:
        return line

    index = _line_match_start(line, query, regex=regex)
    if index < 0:
        return line[: max_chars - 1].rstrip() + "…"
    start = max(0, index - max_chars // 2)
    end = min(len(line), start + max_chars)
    start = max(0, end - max_chars)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(line) else ""
    return f"{prefix}{line[start:end].strip()}{suffix}"


def _line_matcher(query: str, *, regex: bool) -> Callable[[str], bool]:
    if regex:
        try:
            pattern = re.compile(query, re.IGNORECASE)
        except re.error:
            return lambda _line: False
        return lambda line: pattern.search(line) is not None

    lowered_query = query.lower()
    return lambda line: lowered_query in line.lower()


def _line_match_start(line: str, query: str, *, regex: bool) -> int:
    if regex:
        try:
            match = re.search(query, line, re.IGNORECASE)
        except re.error:
            return -1
        return -1 if match is None else match.start()

    return line.lower().find(query.lower())


def _invalid_search_regex_message(exc: ValueError) -> str | None:
    message = str(exc)
    if message.startswith("validation: "):
        message = message.removeprefix("validation: ")
    if "invalid search regex:" in message:
        return message
    if "invalid regex:" in message:
        return message.replace("invalid regex:", "invalid search regex:", 1)
    return None


def _search_field_value(issue: Issue, field: str) -> str:
    values = {
        "id": issue.id,
        "title": issue.title,
        "description": issue.description,
        "notes": issue.notes,
        "design": issue.design,
        "refs": "\n".join(issue.refs),
        "plus_one_evidence": plus_one_evidence_search_text(issue.plus_one_evidence),
        "close_history": close_history_search_text(issue.close_history),
        "owner": issue.owner,
        "assignee": issue.assignee,
        "model": issue.model,
        "size": issue.size.value if issue.size else "",
        "changespec_name": issue.changespec_name,
        "changespec_bug_id": issue.changespec_bug_id,
        "status": issue.status.value,
        "type": issue.issue_type.value,
        "tier": issue.tier.value if issue.tier else "",
    }
    return values.get(field, "")


def _render_search_json(
    matches: list[BeadSearchMatch],
    query: str,
    regex: bool,
) -> str:
    envelope = {
        "query": query,
        "regex": regex,
        "count": len(matches),
        "results": [
            {
                "issue": issue_to_wire_dict(match.issue),
                "matched_fields": match.matched_fields,
            }
            for match in matches
        ],
    }
    return json.dumps(envelope, indent=2) + "\n"


def _render_search_full(
    view: BeadProject,
    matches: list[BeadSearchMatch],
    query: str,
    *,
    relativize_design: bool,
    plan_roots: tuple[Path, ...],
) -> str:
    if not matches:
        return f'No beads match "{query}".\n'

    reference_context = (
        artifact_reference_context()
        if any(match.issue.refs for match in matches)
        else None
    )
    sections = [
        render_issue_detail(
            resolve_issue_detail(view, match.issue),
            relativize_design=relativize_design,
            plan_roots=plan_roots,
            reference_context=reference_context,
        ).rstrip("\n")
        for match in matches
    ]
    return f"\n{'-' * 60}\n".join(sections) + "\n"
