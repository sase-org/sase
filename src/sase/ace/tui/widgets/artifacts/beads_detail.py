"""Shared bead presentation used by the Beads detail pane and preview."""

from __future__ import annotations

from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text

from sase.bead.model import BeadTier, Issue, IssueType, PhaseSize, Status
from sase.bead.plus_one_presentation import (
    PLUS_ONE_RICH_STYLE,
    PLUS_ONE_SECTION_LABEL,
    plus_one_badge,
    plus_one_evidence_label,
    plus_one_reports_label,
)
from sase.bead_status_presentation import bead_status_presentation
from sase.bead_type_presentation import bead_type_chip
from sase.core.time import format_local
from sase.phase_size_presentation import (
    PHASE_SIZE_STYLES,
    PHASE_SIZE_VALUES,
    normalize_phase_size,
    phase_size_chip,
)

from ...keymaps import KeymapRegistry, key_display_name
from .beads_data import BeadsSnapshot, PendingTriage

DetailProperty = tuple[str, str | Text]


def bead_properties_header(
    issue: Issue,
    snapshot: BeadsSnapshot | None,
    *,
    project: str,
    project_name: str,
) -> RenderableType:
    """Build a bead title and the complete shared property grid."""
    status = bead_status_presentation(issue.status)
    title = Text(f"{status.tui_glyph} ", style=status.rich_style)
    title.append(issue.id, style="bold #FFD700")
    title.append(f" · {issue.title}", style="bold white")
    if badge := plus_one_badge(issue.plus_one_count):
        title.append(f"  [{badge}]", style=PLUS_ONE_RICH_STYLE)
    properties: list[DetailProperty] = [
        ("ID", issue.id),
        ("Type", bead_type_chip(issue.issue_type)),
        ("Status", _status_chip(issue.status)),
        ("Readiness", _readiness_chip(issue, snapshot, project=project)),
    ]
    if issue.tier is not None:
        properties.append(("Tier", issue.tier.value))
    if issue.issue_type in (IssueType.PHASE, IssueType.TASK):
        properties.append(("Size", phase_size_chip(issue.size or PhaseSize.SMALL)))
    if issue.plus_one_count:
        properties.append(("+1 reports", plus_one_reports_label(issue.plus_one_count)))
    if (
        issue.issue_type is IssueType.PLAN
        and issue.tier is BeadTier.EPIC
        and (phase_sizes := _epic_phase_sizes(issue, snapshot, project=project))
        is not None
    ):
        properties.append(("Phase sizes", phase_sizes))
    if issue.status is Status.CLOSED:
        properties.append(
            (
                "Resolution",
                issue.resolution.value if issue.resolution else "(unrecorded)",
            )
        )
        properties.append(("Close reason", issue.close_reason or ""))
    properties.extend(
        [
            ("Assignee", issue.assignee),
            ("Owner", issue.owner),
            ("Model", issue.model),
            ("Created", format_local(issue.created_at, default="")),
            ("Updated", format_local(issue.updated_at, default="")),
            ("Closed", format_local(issue.closed_at, default="")),
            ("Project", project_name),
            (
                "Dependencies",
                _dependencies_text(issue, snapshot, project=project),
            ),
            ("References", _references_text(issue)),
            ("ChangeSpec", issue.changespec_name),
            (
                "External bug",
                f"#{issue.changespec_bug_id}" if issue.changespec_bug_id else "",
            ),
        ]
    )
    properties.extend(_plan_reference_properties(issue, snapshot, project=project))
    return _properties_header(title, properties)


def bead_body_markdown(
    issue: Issue,
    triage: PendingTriage | None = None,
    *,
    registry: KeymapRegistry | None = None,
) -> str:
    """Render the pending-triage callout, description, then notes."""
    lines: list[str] = []
    if triage is not None:
        launch_key = (
            key_display_name(registry.app.beads_launch_work)
            if registry is not None
            else "w"
        )
        close_key = (
            key_display_name(registry.app.beads_close) if registry is not None else "c"
        )
        lines.extend(
            [
                f"> [!IMPORTANT] {issue.id} is awaiting task triage.",
                f"> Press **{launch_key}** to launch it or **{close_key}** to close it.",
                "",
            ]
        )
    lines.extend(["## Description", "", issue.description or "_No description._"])
    lines.extend(_plus_one_evidence_markdown(issue))
    if issue.notes:
        lines.extend(["", "## Notes", "", issue.notes])
    return "\n".join(lines)


def bead_preview_markdown(
    issue: Issue,
    snapshot: BeadsSnapshot | None,
    *,
    project: str,
    registry: KeymapRegistry | None = None,
) -> str:
    triage = (
        None if snapshot is None else snapshot.triage_gates.get((project, issue.id))
    )
    lines = [
        f"# {issue.id} · {issue.title}",
        "",
        f"**Type:** {issue.issue_type.value}  ",
        f"**Status:** {issue.status.value}  ",
        f"**Readiness:** {_readiness_label(issue, snapshot, project=project)}  ",
    ]
    if issue.tier is not None:
        lines.append(f"**Tier:** {issue.tier.value}  ")
    if issue.size is not None:
        lines.append(f"**Size:** {issue.size.value}  ")
    if issue.plus_one_count:
        lines.append(f"**+1 reports:** {issue.plus_one_count}  ")
    if issue.assignee:
        lines.append(f"**Assignee:** {issue.assignee}  ")
    if issue.owner:
        lines.append(f"**Owner:** {issue.owner}  ")
    if issue.model:
        lines.append(f"**Model:** {issue.model}  ")
    if issue.changespec_name:
        lines.append(f"**ChangeSpec:** {issue.changespec_name}  ")
    if issue.changespec_bug_id:
        lines.append(f"**External bug:** #{issue.changespec_bug_id}  ")
    if issue.design.strip():
        lines.append(f"**Plan reference:** {issue.design.strip()}  ")
        path = (
            "" if snapshot is None else snapshot.plan_links.get((project, issue.id), "")
        )
        lines.append(f"**Linked plan:** {path or 'cannot resolve'}  ")
    for index, reference in enumerate(issue.refs):
        label = "**References:**" if index == 0 else " " * len("**References:**")
        lines.append(f"{label} {reference}  ")
    lines.extend(["", bead_body_markdown(issue, triage, registry=registry)])
    if issue.dependencies:
        lines.extend(["", "## Dependencies", ""])
        for dependency in issue.dependencies:
            state = _dependency_state(
                snapshot, dependency.depends_on_id, project=project
            )
            lines.append(f"- {dependency.depends_on_id} — {state}")
    lines.extend(
        [
            "",
            "## History",
            "",
            f"- Created: {format_local(issue.created_at)}",
            f"- Updated: {format_local(issue.updated_at)}",
        ]
    )
    if issue.closed_at:
        lines.append(f"- Closed: {format_local(issue.closed_at)}")
    if issue.status is Status.CLOSED:
        resolution = issue.resolution.value if issue.resolution else "(unrecorded)"
        lines.append(f"- Resolution: {resolution}")
    if issue.close_reason:
        lines.append(f"- Close reason: {issue.close_reason}")
    return "\n".join(lines)


def _plus_one_evidence_markdown(issue: Issue) -> list[str]:
    if not issue.plus_one_evidence:
        return []
    lines = ["", f"## {PLUS_ONE_SECTION_LABEL.title()}", ""]
    for index, evidence in enumerate(issue.plus_one_evidence):
        if index:
            lines.append("")
        label = plus_one_evidence_label(evidence).replace("`", "\\`")
        lines.append(f"> [!TIP] **{label}**")
        lines.extend(
            f"> {line}" if line else ">" for line in evidence.note.splitlines()
        )
        if evidence.refs:
            lines.append(">")
            lines.append(f"> **Refs:** {', '.join(evidence.refs)}")
    return lines


def resolved_plan_path(
    issue: Issue,
    snapshot: BeadsSnapshot | None,
    *,
    project: str,
) -> str | None:
    if snapshot is None:
        return None
    return snapshot.plan_links.get((project, issue.id)) or None


def _plan_reference_properties(
    issue: Issue,
    snapshot: BeadsSnapshot | None,
    *,
    project: str,
) -> tuple[DetailProperty, ...]:
    reference = issue.design.strip()
    if not reference:
        return (("Plan reference", ""),)
    resolved = resolved_plan_path(issue, snapshot, project=project)
    if resolved is None:
        return (
            ("Plan reference", reference),
            ("Linked plan", Text("cannot resolve", style="#FF8787")),
        )
    return (("Plan reference", reference), ("Linked plan", resolved))


def _references_text(issue: Issue) -> Text:
    if not issue.refs:
        return Text("—", style="dim")
    text = Text()
    for index, reference in enumerate(issue.refs):
        if index:
            text.append("\n")
        text.append(reference, style="white")
    return text


def _dependencies_text(
    issue: Issue,
    snapshot: BeadsSnapshot | None,
    *,
    project: str,
) -> Text:
    if not issue.dependencies:
        return Text("—", style="dim")
    text = Text()
    statuses = {status.value: status for status in Status}
    for index, dependency in enumerate(issue.dependencies):
        if index:
            text.append("\n")
        state = _dependency_state(snapshot, dependency.depends_on_id, project=project)
        status = statuses.get(state)
        glyph = "?" if status is None else bead_status_presentation(status).tui_glyph
        style = "dim" if status is None else bead_status_presentation(status).rich_style
        text.append(glyph, style=style)
        text.append(f" {dependency.depends_on_id}", style="white")
        text.append(f"  {state.replace('_', ' ')}", style=style)
    return text


def _epic_phase_sizes(
    issue: Issue,
    snapshot: BeadsSnapshot | None,
    *,
    project: str,
) -> Text | None:
    if snapshot is None:
        return None
    phases = snapshot.phases_by_epic.get((project, issue.id))
    if not phases:
        return None
    counts = dict.fromkeys(PHASE_SIZE_VALUES, 0)
    for phase in phases:
        size = normalize_phase_size(phase.issue.size or PhaseSize.SMALL)
        if size is None:
            return None
        counts[size] += 1
    text = Text()
    for size in PHASE_SIZE_VALUES:
        if not counts[size]:
            continue
        if text:
            text.append(" · ", style="dim")
        text.append(f"{counts[size]} ", style="white")
        text.append(size, style=PHASE_SIZE_STYLES[size])
    return text or None


def _dependency_state(
    snapshot: BeadsSnapshot | None,
    issue_id: str,
    *,
    project: str,
) -> str:
    if snapshot is None:
        return "unknown"
    for item in snapshot.tasks:
        if item.project == project and item.issue.id == issue_id:
            return item.issue.status.value
    for item in snapshot.epics:
        if item.project == project and item.issue.id == issue_id:
            return item.issue.status.value
    for (owner, _epic_id), phases in snapshot.phases_by_epic.items():
        if owner != project:
            continue
        for item in phases:
            if item.issue.id == issue_id:
                return item.issue.status.value
    return "unknown"


def _properties_header(
    title: Text,
    properties: list[DetailProperty],
) -> RenderableType:
    table = Table.grid(padding=(0, 1), expand=True)
    table.add_column(justify="right", style="dim", no_wrap=True)
    table.add_column(ratio=1, overflow="fold")
    for label, value in properties:
        table.add_row(label, _property_text(value))
    divider = Text("─" * 72, style="dim #5F5F87", no_wrap=True, overflow="crop")
    return Group(title, table, divider)


def _property_text(value: str | Text) -> Text:
    if isinstance(value, Text):
        return value
    if value:
        return Text(value, style="white", overflow="fold")
    return Text("—", style="dim")


def _chip(label: str, color: str, *, glyph: str = "") -> Text:
    prefix = f"{glyph} " if glyph else ""
    text = Text()
    text.append(f" {prefix}{label} ", style=f"bold #1a1a1a on {color}")
    text.append(" ")
    return text


def _status_chip(status: Status) -> Text:
    presentation = bead_status_presentation(status)
    return _chip(
        presentation.label.replace("_", " ").lower(),
        presentation.rich_color,
        glyph=presentation.tui_glyph,
    )


def _readiness_chip(
    issue: Issue,
    snapshot: BeadsSnapshot | None,
    *,
    project: str,
) -> Text:
    label = _readiness_label(issue, snapshot, project=project)
    if issue.status in {
        Status.CLOSED,
        Status.CLAIMED,
        Status.READY,
        Status.IN_PROGRESS,
    }:
        presentation = bead_status_presentation(issue.status)
        return _chip(label, presentation.rich_color, glyph=presentation.tui_glyph)
    color, glyph = {
        "blocked": ("#FF5F5F", "×"),
        "ready": ("#5FD787", "✓"),
        "waiting": ("#87D7FF", "○"),
        "unknown": ("#878787", "?"),
    }[label]
    return _chip(label, color, glyph=glyph)


def _readiness_label(
    issue: Issue,
    snapshot: BeadsSnapshot | None,
    *,
    project: str,
) -> str:
    if issue.status is Status.CLOSED:
        return "closed"
    if issue.status is Status.CLAIMED:
        return "claimed"
    if issue.status is Status.READY:
        return "ready"
    if issue.status is Status.IN_PROGRESS:
        return "in progress"
    if snapshot is None:
        return "unknown"
    key = (project, issue.id)
    if key in snapshot.blocked_ids:
        return "blocked"
    if key in snapshot.ready_ids:
        return "ready"
    return "waiting"


__all__ = [
    "bead_body_markdown",
    "bead_preview_markdown",
    "bead_properties_header",
    "resolved_plan_path",
]
