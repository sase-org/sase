"""Rendering helpers for read-only bead CLI queries."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path

from rich.cells import cell_len

import sase
from sase.artifact_ref_models import ArtifactRefContext
from sase.bead_flag_presentation import flag_due_cli_cell, flag_key_cli_cell
from sase.bead.cli_common import created_cell, status_icon
from sase.bead.cli_dep_render import ANSI_BOLD_BLUE, styled
from sase.bead.cli_detail import (
    issue_to_wire_dict,
    render_issue_detail,
    resolve_issue_detail,
)
from sase.bead.model import BeadSearchMatch, Issue, Status
from sase.bead.plus_one_presentation import (
    PLUS_ONE_CLI_STYLE,
    POST_CLOSE_CLI_STYLE,
    post_close_plus_one_badge,
    post_close_plus_one_count,
    plus_one_badge,
    plus_one_evidence_search_text,
)
from sase.bead.project import BeadProject
from sase.bead.reopen_presentation import (
    REOPEN_CLI_STYLE,
    close_history_search_text,
    reopen_badge,
)
from sase.bead_status_presentation import bead_status_presentation
from sase.bead_summary_presentation import BeadListSummary
from sase.bead_type_presentation import (
    BEAD_TYPE_VALUES,
    bead_type_cli_cell,
    bead_type_presentation,
)
from sase.core import time as core_time
from sase.phase_size_presentation import PHASE_SIZE_TOKEN_WIDTH, phase_size_cli_token


def row_badges(issue: Issue, *, use_color: bool = False) -> str:
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


def compact_size_column_width(issues: list[Issue]) -> int:
    return (
        PHASE_SIZE_TOKEN_WIDTH if any(issue.size is not None for issue in issues) else 0
    )


def compact_size_column(issue: Issue, *, use_color: bool, width: int) -> str:
    if width == 0:
        return ""
    return f"{phase_size_cli_token(issue.size, use_color=use_color, width=width)} "


def _flag_compact_cells(issue: Issue, *, use_color: bool) -> str:
    """Return the compact flag identity and removal cells for flag rows."""
    record = issue.flag
    if record is None:
        return ""
    today = core_time.local_now().date()
    due_cell = flag_due_cli_cell(
        record,
        today=today,
        release=sase.__version__,
        use_color=use_color,
    )
    return f"  {flag_key_cli_cell(record.key, use_color=use_color)} {due_cell}"


def render_list_compact(issues: list[Issue], *, use_color: bool) -> str:
    # Measured (not assumed) so the column stays aligned even though the three
    # type glyphs may not always share a Unicode width class.
    type_width = max(
        cell_len(bead_type_presentation(value).glyph) for value in BEAD_TYPE_VALUES
    )
    size_width = compact_size_column_width(issues)
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
            f"{compact_size_column(issue, use_color=use_color, width=size_width)}"
            f"{issue_id} · {issue.title}"
            f"{_flag_compact_cells(issue, use_color=use_color)}"
            f"{row_badges(issue, use_color=use_color)}{parent}"
            f"{created_cell(issue, use_color=use_color)}"
        )
    return "\n".join(lines) + "\n"


def render_list_full(
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


def render_list_json(
    issues: list[Issue],
    *,
    total: int,
    statuses: list[Status],
    implied_status_closed: bool,
    summary: BeadListSummary,
) -> str:
    envelope = {
        "count": len(issues),
        "total": total,
        "statuses": [status.value for status in statuses],
        "implied_status_closed": implied_status_closed,
        "by_type": dict(summary.by_type),
        "by_status": dict(summary.by_status),
        "due_flags": summary.due_flags,
        "results": [issue_to_wire_dict(issue) for issue in issues],
    }
    return json.dumps(envelope, indent=2) + "\n"


def render_search_compact(
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
    size_width = compact_size_column_width([match.issue for match in matches])
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
            f"{compact_size_column(issue, use_color=use_color, width=size_width)}"
            f"{issue.id} · "
            f"{issue.title}{_flag_compact_cells(issue, use_color=use_color)}"
            f"{row_badges(issue, use_color=use_color)}"
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
        value = search_field_value(issue, field)
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


def invalid_search_regex_message(exc: ValueError) -> str | None:
    message = str(exc)
    if message.startswith("validation: "):
        message = message.removeprefix("validation: ")
    if "invalid search regex:" in message:
        return message
    if "invalid regex:" in message:
        return message.replace("invalid regex:", "invalid search regex:", 1)
    return None


def search_field_value(issue: Issue, field: str) -> str:
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
        "external_ref": issue.external_ref,
        "status": issue.status.value,
        "type": issue.issue_type.value,
        "tier": issue.tier.value if issue.tier else "",
        "flag_key": issue.flag.key if issue.flag else "",
        "flag_remove_by_date": issue.flag.remove_by_date if issue.flag else "",
        "flag_remove_by_release": (issue.flag.remove_by_release if issue.flag else ""),
    }
    return values.get(field, "")


def render_search_json(
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


def render_search_full(
    view: BeadProject,
    matches: list[BeadSearchMatch],
    query: str,
    *,
    relativize_design: bool,
    plan_roots: tuple[Path, ...],
    reference_context: ArtifactRefContext | None,
) -> str:
    if not matches:
        return f'No beads match "{query}".\n'

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
