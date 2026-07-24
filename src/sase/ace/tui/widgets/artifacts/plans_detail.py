"""Rich properties and Markdown bodies for the Artifacts Plans detail pane."""

from __future__ import annotations

from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text

from sase.bead.model import BeadTier, Issue, IssueType, PhaseSize, Status
from sase.bead_status_presentation import bead_status_presentation
from sase.phase_size_presentation import (
    PHASE_SIZE_STYLES,
    PHASE_SIZE_VALUES,
    normalize_phase_size,
    phase_size_chip,
)
from sase.plan_search.model import PlanSearchMatch
from sase.sdd.plan_properties import (
    ordered_plan_property_items,
    plan_property_label,
)

from .plans_data import LinkedPlanDocument, PlanProposal, PlansSnapshot


DetailProperty = tuple[str, str | Text]


def proposal_properties_header(
    proposal: PlanProposal,
    *,
    project_name: str,
) -> RenderableType:
    """Build a proposal title and complete property grid."""
    title = Text("◆ ", style="bold #FFD700")
    title.append(proposal.title, style="bold white")
    proposed = proposal.timestamp or "—"
    if proposal.age:
        proposed += f"  ·  {proposal.age}"
    properties: list[DetailProperty] = [
        ("State", _chip("pending approval", "#FFD700", glyph="◆")),
        ("Tier", proposal.tier),
        ("Agent", proposal.agent),
        ("Model", proposal.provider_model),
        ("Proposed", proposed),
        ("Project", project_name),
        ("Path", proposal.plan_path),
    ]
    properties.extend(_frontmatter_properties(proposal.frontmatter))
    return _properties_header(title, properties)


def bead_properties_header(
    issue: Issue,
    snapshot: PlansSnapshot | None,
    *,
    project: str,
    project_name: str,
) -> RenderableType:
    """Build a bead title and complete property grid."""
    title = Text(f"{_status_glyph(issue.status)} ", style=_status_style(issue.status))
    title.append(issue.id, style="bold #FFD700")
    title.append(f" · {issue.title}", style="bold white")
    properties: list[DetailProperty] = [
        ("Status", _status_chip(issue.status)),
        ("Readiness", _readiness_chip(issue, snapshot, project=project)),
        ("Type", issue.issue_type.value),
    ]
    if issue.issue_type is IssueType.PHASE:
        properties.append(("Size", phase_size_chip(issue.size or PhaseSize.SMALL)))
    if issue.tier is not None:
        properties.append(("Tier", issue.tier.value))
    if (
        issue.issue_type is IssueType.PLAN
        and issue.tier is BeadTier.EPIC
        and (phase_sizes := _epic_phase_sizes(issue, snapshot, project=project))
        is not None
    ):
        properties.append(("Phase sizes", phase_sizes))
    properties.extend(
        [
            ("Model", issue.model),
            ("Assignee", issue.assignee),
            ("ChangeSpec", issue.changespec_name),
            (
                "External bug",
                f"#{issue.changespec_bug_id}" if issue.changespec_bug_id else "",
            ),
            ("Design path", issue.design),
            ("Project", project_name),
            ("Created", issue.created_at),
            ("Updated", issue.updated_at),
            ("Closed", issue.closed_at or ""),
        ]
    )
    if issue.close_reason:
        properties.append(("Close reason", issue.close_reason))
    properties.append(
        (
            "Dependencies",
            _dependencies_text(issue, snapshot, project=project),
        )
    )
    return _properties_header(title, properties)


def archive_properties_header(
    match: PlanSearchMatch,
    *,
    project_name: str,
) -> RenderableType:
    """Build an archived-plan title and complete property grid."""
    plan = match.plan
    title = Text("▤ ", style="bold #00D7AF")
    title.append(plan.title or plan.name, style="bold white")
    properties = list(_frontmatter_properties(plan.frontmatter))
    properties.extend(
        [
            ("Source", plan.source),
            ("Project", project_name),
            ("Path", plan.path),
        ]
    )
    return _properties_header(title, properties)


def _ordered_frontmatter_items(
    frontmatter: dict[str, str],
) -> tuple[tuple[str, str], ...]:
    """Order known plan properties first, then remaining keys alphabetically."""
    return tuple(ordered_plan_property_items(frontmatter))


def bead_body_markdown(
    issue: Issue,
    linked_plan: LinkedPlanDocument | None = None,
) -> str:
    """Render a bead's description, notes, and worker-loaded linked plan."""
    lines = ["## Description", "", issue.description or "_No description._"]
    if issue.notes:
        lines.extend(["", "## Notes", "", issue.notes])
    if linked_plan is not None:
        lines.extend(["", "---", "", "## Plan", ""])
        if linked_plan.error is not None:
            lines.append(f"_{linked_plan.error}_")
        else:
            for key, value in _ordered_frontmatter_items(linked_plan.frontmatter):
                label = plan_property_label(key)
                lines.append(f"**{label}:** {value.replace(chr(10), ' ')}  ")
            if linked_plan.frontmatter:
                lines.append("")
            lines.append(linked_plan.body or "_The linked plan is empty._")
    return "\n".join(lines)


def linked_plan_for_issue(
    issue: Issue,
    snapshot: PlansSnapshot | None,
    *,
    project: str,
) -> LinkedPlanDocument | None:
    """Return a phase override or its owning epic's linked document."""
    if snapshot is None:
        return None
    direct = snapshot.linked_plan_documents.get((project, issue.id))
    if direct is not None:
        return direct
    if issue.parent_id:
        return snapshot.linked_plan_documents.get((project, issue.parent_id))
    return None


def archive_preview_markdown(match: PlanSearchMatch) -> str:
    """Preserve the full-screen archive preview content."""
    plan = match.plan
    lines = [
        f"# {plan.title or plan.name}",
        "",
        f"**Tier:** {plan.kind}  ",
        f"**Status:** {plan.status or 'unknown'}  ",
        f"**Created:** {plan.created_at or '—'}  ",
        f"**Path:** {plan.path}",
        "",
    ]
    if plan.summary:
        lines.extend(["> " + plan.summary.replace("\n", "\n> "), ""])
    lines.append(plan.body or "_No plan body._")
    return "\n".join(lines)


def bead_preview_markdown(
    issue: Issue,
    snapshot: PlansSnapshot | None,
    *,
    project: str,
) -> str:
    """Preserve the full-screen bead preview content."""
    lines = [
        f"# {issue.id} · {issue.title}",
        "",
        f"**Status:** {issue.status.value}  ",
        f"**Readiness:** {_readiness_label(issue, snapshot, project=project)}  ",
        f"**Type:** {issue.issue_type.value}  ",
    ]
    if issue.issue_type is IssueType.PHASE:
        size = normalize_phase_size(issue.size or PhaseSize.SMALL)
        lines.append(f"**Size:** {size or 'unavailable'}  ")
    elif (
        issue.tier is BeadTier.EPIC
        and (phase_sizes := _epic_phase_sizes(issue, snapshot, project=project))
        is not None
    ):
        lines.append(f"**Phase sizes:** {phase_sizes.plain}  ")
    if issue.model:
        lines.append(f"**Model:** {issue.model}  ")
    if issue.assignee:
        lines.append(f"**Assignee:** {issue.assignee}  ")
    if issue.changespec_name:
        lines.append(f"**ChangeSpec:** {issue.changespec_name}  ")
    if issue.changespec_bug_id:
        lines.append(f"**External bug:** #{issue.changespec_bug_id}  ")
    if issue.design:
        lines.append(f"**Design:** {issue.design}  ")
    lines.extend(["", bead_body_markdown(issue)])
    if issue.dependencies:
        lines.extend(["", "## Dependencies", ""])
        for dependency in issue.dependencies:
            state = _dependency_state(
                snapshot,
                dependency.depends_on_id,
                project=project,
            )
            lines.append(f"- {dependency.depends_on_id} — {state}")
    lines.extend(
        [
            "",
            "## History",
            "",
            f"- Created: {issue.created_at or '—'}",
            f"- Updated: {issue.updated_at or '—'}",
        ]
    )
    if issue.closed_at:
        lines.append(f"- Closed: {issue.closed_at}")
    if issue.close_reason:
        lines.append(f"- Close reason: {issue.close_reason}")
    return "\n".join(lines)


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


def _frontmatter_properties(
    frontmatter: dict[str, str],
) -> tuple[DetailProperty, ...]:
    return tuple(
        (plan_property_label(key), value)
        for key, value in _ordered_frontmatter_items(frontmatter)
    )


def _dependencies_text(
    issue: Issue,
    snapshot: PlansSnapshot | None,
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
        state = _dependency_state(
            snapshot,
            dependency.depends_on_id,
            project=project,
        )
        status = statuses.get(state)
        glyph = "?" if status is None else _status_glyph(status)
        style = "dim" if status is None else _status_style(status)
        text.append(glyph, style=style)
        text.append(f" {dependency.depends_on_id}", style="white")
        text.append(f"  {state.replace('_', ' ')}", style=style)
    return text


def _epic_phase_sizes(
    issue: Issue,
    snapshot: PlansSnapshot | None,
    *,
    project: str,
) -> Text | None:
    """Summarize persisted direct phase sizes without consulting authored plans."""
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
        count = counts[size]
        if not count:
            continue
        if text:
            text.append(" · ", style="dim")
        text.append(f"{count} ", style="white")
        text.append(size, style=PHASE_SIZE_STYLES[size])
    return text or None


def _dependency_state(
    snapshot: PlansSnapshot | None,
    issue_id: str,
    *,
    project: str,
) -> str:
    if snapshot is None:
        return "unknown"
    for (owner, _epic_id), phases in snapshot.phases_by_epic.items():
        if owner != project:
            continue
        for phase in phases:
            if phase.issue.id == issue_id:
                return phase.issue.status.value
    for epic in snapshot.epics:
        if epic.project == project and epic.issue.id == issue_id:
            return epic.issue.status.value
    return "unknown"


def _chip(label: str, color: str, *, glyph: str = "") -> Text:
    prefix = f"{glyph} " if glyph else ""
    text = Text()
    text.append(f" {prefix}{label} ", style=f"bold #1a1a1a on {color}")
    # End on an unstyled cell so Rich doesn't extend the chip background to
    # the table column's full width while padding the row.
    text.append(" ")
    return text


def _status_chip(status: Status) -> Text:
    presentation = bead_status_presentation(status)
    return _chip(
        status.value.replace("_", " "),
        presentation.rich_color,
        glyph=_status_glyph(status),
    )


def _readiness_chip(
    issue: Issue,
    snapshot: PlansSnapshot | None,
    *,
    project: str,
) -> Text:
    label = _readiness_label(issue, snapshot, project=project)
    if issue.status in (Status.CLOSED, Status.CLAIMED, Status.IN_PROGRESS):
        presentation = bead_status_presentation(issue.status)
        return _chip(
            label,
            presentation.rich_color,
            glyph=presentation.tui_glyph,
        )
    color, glyph = {
        "blocked": ("#FF5F5F", "×"),
        "ready": ("#5FD787", "✓"),
        "waiting": ("#87D7FF", "○"),
        "unknown": ("#878787", "?"),
    }[label]
    return _chip(label, color, glyph=glyph)


def _readiness_label(
    issue: Issue,
    snapshot: PlansSnapshot | None,
    *,
    project: str,
) -> str:
    if issue.status == Status.CLOSED:
        return "closed"
    if issue.status == Status.CLAIMED:
        return "claimed"
    if issue.status == Status.IN_PROGRESS:
        return "in progress"
    if snapshot is None:
        return "unknown"
    issue_key = (project, issue.id)
    if issue_key in snapshot.blocked_ids:
        return "blocked"
    if issue_key in snapshot.ready_ids:
        return "ready"
    return "waiting"


def _status_glyph(status: Status) -> str:
    return bead_status_presentation(status).tui_glyph


def _status_style(status: Status) -> str:
    return bead_status_presentation(status).rich_style


__all__ = [
    "archive_preview_markdown",
    "archive_properties_header",
    "bead_body_markdown",
    "bead_preview_markdown",
    "bead_properties_header",
    "linked_plan_for_issue",
    "proposal_properties_header",
]
