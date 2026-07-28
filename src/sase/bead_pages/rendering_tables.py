"""Relationship and association tables for bead pages."""

from __future__ import annotations

from datetime import UTC, datetime

from sase.agents_sync.rendering_commits import MAX_RENDERED_COMMITS
from sase.agents_sync.rendering_markdown import (
    md_cell,
    md_code,
    md_escape,
    relative_page_url,
)
from sase.bead.cli_common import status_icon
from sase.bead.cli_detail import IssueDetail, IssueRef
from sase.bead.model import Issue
from sase.bead_pages.associations import (
    BeadAssociationIndex,
    BeadAgentAssociation,
    BeadCommitAssociation,
)
from sase.bead_pages.paths import bead_page_path


def render_phases(
    detail: IssueDetail,
    associations: BeadAssociationIndex,
) -> list[str]:
    """Render a root bead's direct phases in stable id order."""

    phases = tuple(
        ref.issue
        for ref in sorted(detail.phases, key=lambda item: item.issue_id)
        if ref.issue is not None
    )
    if not phases:
        return []
    lines = [
        "",
        "## Phases",
        "",
        "| Bead | Title | Status | Size | Agents | Commits |",
        "|---|---|---|---|---:|---:|",
    ]
    for phase in phases[:MAX_RENDERED_COMMITS]:
        phase_associations = associations.for_bead(phase.id)
        lines.append(
            "| "
            + " | ".join(
                (
                    _bead_cell(detail.issue.id, phase.id),
                    md_cell(phase.title),
                    f"{status_icon(phase.status)} {phase.status.value}",
                    phase.size.value if phase.size else "small",
                    str(len(phase_associations.agents)),
                    str(len(phase_associations.commits)),
                )
            )
            + " |"
        )
    _append_more(lines, len(phases), "phases")
    return lines


def render_dependencies(detail: IssueDetail) -> list[str]:
    """Render incoming and outgoing dependency edges."""

    rows = sorted(
        (
            *(("Depends on", ref) for ref in detail.depends_on),
            *(("Blocks", ref) for ref in detail.blocks),
        ),
        key=lambda item: (item[1].issue_id, item[0]),
    )
    if not rows:
        return []
    lines = ["", "## Dependencies", ""]
    for relationship, ref in rows[:MAX_RENDERED_COMMITS]:
        lines.append(f"- **{relationship}:** {_reference_label(detail.issue.id, ref)}")
    _append_more(lines, len(rows), "dependencies")
    return lines


def render_agents(
    issue: Issue,
    associations: tuple[BeadAgentAssociation, ...],
) -> list[str]:
    """Render bounded, bead-attributed agent associations."""

    rows = tuple(sorted(associations, key=lambda row: row.sort_key))
    if not rows:
        return []
    lines = [
        "",
        "## Agents",
        "",
        "| Agent | Bead | Commits |",
        "|---|---|---:|",
    ]
    for row in rows[:MAX_RENDERED_COMMITS]:
        label = md_cell(row.label)
        agent = f"[{label}]({row.target})" if row.target else label
        lines.append(
            f"| {agent} | {_bead_cell(issue.id, row.bead_id)} | {row.commit_count} |"
        )
    _append_more(lines, len(rows), "agents")
    return lines


def render_commits(
    issue: Issue,
    associations: tuple[BeadCommitAssociation, ...],
) -> list[str]:
    """Render bounded, bead-attributed commit associations."""

    rows = tuple(sorted(associations, key=lambda row: row.sort_key))
    if not rows:
        return []
    lines = [
        "",
        "## Commits",
        "",
        "| Commit | Subject | Bead | Committed (UTC) |",
        "|---|---|---|---|",
    ]
    for row in rows[:MAX_RENDERED_COMMITS]:
        label = f"`{md_code(row.label)}`"
        commit = f"[{label}]({row.target})" if row.target else label
        committed = datetime.fromtimestamp(row.committed_at, tz=UTC).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        lines.append(
            f"| {commit} | {md_cell(row.subject)}"
            f" | {_bead_cell(issue.id, row.bead_id)} | {committed} |"
        )
    _append_more(lines, len(rows), "commits")
    return lines


def _reference_label(source_id: str, ref: IssueRef) -> str:
    if ref.issue is None:
        return f"{md_escape(ref.issue_id)} (not found)"
    return f"{_bead_cell(source_id, ref.issue_id)} {status_icon(ref.issue.status)}"


def _bead_cell(source_id: str, target_id: str) -> str:
    source = bead_page_path(source_id)
    target = bead_page_path(target_id)
    href = relative_page_url(source, target)
    return f"[{md_escape(target_id)}]({href})"


def _append_more(lines: list[str], count: int, label: str) -> None:
    remaining = count - MAX_RENDERED_COMMITS
    if remaining > 0:
        lines.extend(["", f"… and {remaining} more {label}"])


__all__ = [
    "render_agents",
    "render_commits",
    "render_dependencies",
    "render_phases",
]
