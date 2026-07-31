"""Read-only bead CLI command handlers."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sase.artifact_ref_models import ArtifactRefContext
from sase.bead.cli_common import get_read_view, status_icon
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
from sase.bead.model import (
    BeadSearchMatch,
    BeadTier,
    Issue,
    IssueType,
    Status,
)
from sase.bead.project import BeadProject

# Closed bead listings can grow without bound, so default to the newest few
# rows when the user did not request an explicit ``--limit``.
DEFAULT_CLOSED_LIST_LIMIT = 20


def handle_bead_list(args: argparse.Namespace) -> None:
    with get_read_view() as view:
        explicit_statuses = args.status is not None
        statuses = (
            [Status(s) for s in args.status]
            if explicit_statuses
            else [Status.OPEN, Status.CLAIMED, Status.READY, Status.IN_PROGRESS]
        )
        issue_types = [IssueType(t) for t in args.type] if args.type else None
        tiers = [BeadTier(t) for t in args.tier] if args.tier else None
        issues = view.list_issues(
            statuses=statuses, issue_types=issue_types, tiers=tiers
        )
        implicit_closed = False
        if not issues and not explicit_statuses:
            issues = view.list_issues(
                statuses=[Status.CLOSED], issue_types=issue_types, tiers=tiers
            )
            statuses = [Status.CLOSED]
            implicit_closed = bool(issues)
        total = len(issues)
        closed_in_scope = implicit_closed or Status.CLOSED in statuses
        limit = getattr(args, "limit", None)
        if limit is None and closed_in_scope:
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
                print(_render_list_compact(issues), end="")
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


def handle_bead_show(args: argparse.Namespace) -> None:
    with get_read_view() as view:
        try:
            issue = view.show(args.id)
        except KeyError:
            print(f"Error: issue not found: {args.id}", file=sys.stderr)
            sys.exit(1)

        match args.format:
            case "compact":
                print(_render_list_compact([issue]), end="")
            case "json":
                detail = resolve_issue_detail(view, issue)
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
                detail = resolve_issue_detail(view, issue)
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
                    ),
                    end="",
                )
            case _:
                raise AssertionError(f"unknown show format: {args.format}")


def handle_bead_search(args: argparse.Namespace) -> None:
    if not args.query.strip():
        print("Error: search query cannot be empty", file=sys.stderr)
        sys.exit(2)

    with get_read_view() as view:
        statuses = [Status(s) for s in args.status] if args.status else None
        issue_types = [IssueType(t) for t in args.type] if args.type else None
        tiers = [BeadTier(t) for t in args.tier] if args.tier else None
        matches = view.search(
            args.query,
            statuses=statuses,
            issue_types=issue_types,
            tiers=tiers,
            limit=args.limit,
        )

        match args.format:
            case "compact":
                print(_render_search_compact(matches, args.query), end="")
            case "json":
                print(_render_search_json(matches, args.query), end="")
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
        for issue in issues:
            parent = f" ← {issue.parent_id}" if issue.parent_id else ""
            print(f"{status_icon(issue.status)} {issue.id} · {issue.title}{parent}")
        print(f"\n{'-' * 60}")
        suffix = "" if len(issues) == 1 else "s"
        print(f"Ready: {len(issues)} task bead{suffix} with no active blockers")


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
        print(f"  Claimed:     {s.get('claimed', 0)}")
        print(f"  Ready:       {s.get('ready', 0)}")
        print(f"  In Progress: {s.get('in_progress', 0)}")
        print(f"  Closed:      {s.get('closed', 0)}")
        print(f"  Plans:       {s.get('plan', 0)}")
        print(f"  Phases:      {s.get('phase', 0)}")
        print(f"  Tasks:       {s.get('task', 0)}")


def _render_list_compact(issues: list[Issue]) -> str:
    lines = []
    for issue in issues:
        parent = f" ← {issue.parent_id}" if issue.parent_id else ""
        lines.append(f"{status_icon(issue.status)} {issue.id} · {issue.title}{parent}")
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


def _render_search_compact(matches: list[BeadSearchMatch], query: str) -> str:
    if not matches:
        return f'No beads match "{query}".\n'

    lines: list[str] = []
    for match in matches:
        issue = match.issue
        lines.append(f"{status_icon(issue.status)} {issue.id} · {issue.title}")
        snippet = _compact_snippet(match, query)
        if snippet:
            lines.append(f"  {snippet}")
    return "\n".join(lines) + "\n"


def _compact_snippet(match: BeadSearchMatch, query: str) -> str:
    issue = match.issue
    has_title_or_description_match = any(
        field in {"title", "description"} for field in match.matched_fields
    )
    description = _single_line_snippet(issue.description, query)
    if has_title_or_description_match and description:
        return description

    for field in match.matched_fields:
        if field == "title":
            continue
        value = _search_field_value(issue, field)
        snippet = _single_line_snippet(value, query)
        if snippet:
            return f'{field}: "{snippet}"'
    return ""


def _single_line_snippet(value: str, query: str, max_chars: int = 96) -> str:
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if not lines:
        return ""

    lowered_query = query.lower()
    line = next(
        (line for line in lines if lowered_query in line.lower()),
        lines[0],
    )
    if len(line) <= max_chars:
        return line

    index = line.lower().find(lowered_query)
    if index < 0:
        return line[: max_chars - 1].rstrip() + "…"
    start = max(0, index - max_chars // 2)
    end = min(len(line), start + max_chars)
    start = max(0, end - max_chars)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(line) else ""
    return f"{prefix}{line[start:end].strip()}{suffix}"


def _search_field_value(issue: Issue, field: str) -> str:
    values = {
        "id": issue.id,
        "title": issue.title,
        "description": issue.description,
        "notes": issue.notes,
        "design": issue.design,
        "refs": "\n".join(issue.refs),
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


def _render_search_json(matches: list[BeadSearchMatch], query: str) -> str:
    envelope = {
        "query": query,
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
