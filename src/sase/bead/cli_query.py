"""Read-only bead CLI command handlers."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import sys

from sase.bead.cli_common import get_read_view, status_icon
from sase.bead.model import (
    BeadSearchMatch,
    BeadTier,
    Dependency,
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
            else [Status.OPEN, Status.CLAIMED, Status.IN_PROGRESS]
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
            implicit_closed = bool(issues)
        if not issues:
            print("No issues found.")
            return
        if implicit_closed:
            print("No open beads to show — defaulting to --status closed.")
        closed_in_scope = implicit_closed or Status.CLOSED in statuses
        limit = getattr(args, "limit", None)
        if limit is None and closed_in_scope:
            limit = DEFAULT_CLOSED_LIST_LIMIT
        if limit:
            issues = issues[-limit:]
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
        if issue.status == Status.CLAIMED:
            print(f"Claimed by: {issue.assignee} (agent has not started working yet)")
        if issue.model:
            print(f"Model: {issue.model}")
        if issue.issue_type == IssueType.PHASE:
            print(f"Size: {_phase_size_value(issue)}")
        ancestors: list[Issue] = []
        unresolved_parent_id: str | None = None
        if issue.parent_id:
            ancestors, unresolved_parent_id = _parent_lineage(view, issue)
            lineage = [issue.id]
            lineage.extend(
                f"{_lineage_kind(parent)} {parent.id}" for parent in ancestors
            )
            if unresolved_parent_id is not None:
                lineage.append(f"{unresolved_parent_id} (not found)")
            print(f"\nPARENT\n  ↑ {' ← '.join(lineage)}")
        children = view.get_epic_children(issue.id)
        if children:
            print("\nCHILDREN")
            phases = [
                child for child in children if child.issue_type == IssueType.PHASE
            ]
            child_epics = [
                child for child in children if child.issue_type == IssueType.PLAN
            ]
            if phases:
                print("  PHASES")
                for child in phases:
                    ci = status_icon(child.status)
                    print(
                        f"    {ci} {child.id}: {child.title}"
                        f"   [{child.status.value.upper()}]"
                        f" · Size: {_phase_size_value(child)}"
                    )
            if child_epics:
                print("  CHILD EPICS")
                for child in child_epics:
                    ci = status_icon(child.status)
                    tier = child.tier.value if child.tier else "(none)"
                    print(
                        f"    {ci} {child.id}: {child.title}"
                        f"   [{child.status.value.upper()}] · Tier: {tier}"
                    )
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
            section = (
                "EPIC PLAN"
                if issue.parent_id and issue.tier == BeadTier.EPIC
                else "PLAN"
            )
            print(f"\n{section}\n  {_display_design_path(issue.design)}")
        elif (
            issue.issue_type == IssueType.PHASE
            and ancestors
            and ancestors[0].issue_type == IssueType.PLAN
            and ancestors[0].design
        ):
            resolved_parent = ancestors[0]
            is_epic_parent = resolved_parent.tier == BeadTier.EPIC
            section = "EPIC PLAN" if is_epic_parent else "PARENT PLAN"
            parent_kind = "epic" if is_epic_parent else "plan"
            print(
                f"\n{section}\n"
                f"  From parent {parent_kind} bead "
                f"{resolved_parent.id} · {resolved_parent.title}\n"
                f"  {_display_design_path(resolved_parent.design)}"
            )


def _parent_lineage(
    view: BeadProject,
    issue: Issue,
) -> tuple[list[Issue], str | None]:
    ancestors: list[Issue] = []
    parent_id = issue.parent_id
    seen = {issue.id}
    while parent_id is not None:
        if parent_id in seen:
            return ancestors, parent_id
        seen.add(parent_id)
        try:
            parent = view.show(parent_id)
        except KeyError:
            return ancestors, parent_id
        ancestors.append(parent)
        parent_id = parent.parent_id
    return ancestors, None


def _lineage_kind(issue: Issue) -> str:
    if issue.issue_type == IssueType.PHASE:
        return "phase"
    return "epic" if issue.tier == BeadTier.EPIC else "plan"


def _phase_size_value(issue: Issue) -> str:
    return issue.size.value if issue.size else "small"


def _display_design_path(design: str) -> str:
    from sase.sdd.store import resolve_sdd_store

    if resolve_sdd_store(Path.cwd(), 1).is_in_tree:
        return os.path.relpath(design)
    return design


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
            print(_render_search_full(matches, args.query), end="")
        case _:
            raise AssertionError(f"unknown search format: {args.format}")


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
        print(f"  Claimed:     {s.get('claimed', 0)}")
        print(f"  In Progress: {s.get('in_progress', 0)}")
        print(f"  Closed:      {s.get('closed', 0)}")
        print(f"  Plans:       {s.get('plan', 0)}")
        print(f"  Phases:      {s.get('phase', 0)}")


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
                "issue": _issue_to_wire_dict(match.issue),
                "matched_fields": match.matched_fields,
            }
            for match in matches
        ],
    }
    return json.dumps(envelope, indent=2) + "\n"


def _render_search_full(matches: list[BeadSearchMatch], query: str) -> str:
    if not matches:
        return f'No beads match "{query}".\n'

    sections: list[str] = []
    for match in matches:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            handle_bead_show(argparse.Namespace(id=match.issue.id))
        sections.append(output.getvalue().rstrip("\n"))
    return f"\n{'-' * 60}\n".join(sections) + "\n"


def _issue_to_wire_dict(issue: Issue) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": issue.id,
        "title": issue.title,
        "status": issue.status.value,
        "issue_type": issue.issue_type.value,
        "tier": issue.tier.value if issue.tier else None,
        "parent_id": issue.parent_id,
        "owner": issue.owner,
        "assignee": issue.assignee,
        "created_at": issue.created_at,
        "created_by": issue.created_by,
        "updated_at": issue.updated_at,
        "closed_at": issue.closed_at,
        "close_reason": issue.close_reason,
        "description": issue.description,
        "notes": issue.notes,
        "design": issue.design,
        "model": issue.model,
        "is_ready_to_work": issue.is_ready_to_work,
        "changespec_name": issue.changespec_name,
        "changespec_bug_id": issue.changespec_bug_id,
        "dependencies": [_dependency_to_wire_dict(dep) for dep in issue.dependencies],
    }
    if issue.size is not None:
        payload["size"] = issue.size.value
    return payload


def _dependency_to_wire_dict(dep: Dependency) -> dict[str, str]:
    return {
        "issue_id": dep.issue_id,
        "depends_on_id": dep.depends_on_id,
        "created_at": dep.created_at,
        "created_by": dep.created_by,
    }
