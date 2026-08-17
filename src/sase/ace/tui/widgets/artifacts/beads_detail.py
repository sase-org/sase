"""Shared bead presentation used by the Beads detail pane and preview."""

from __future__ import annotations

from rich.console import RenderableType
from rich.text import Text

from sase.bead.model import BeadTier, Issue, IssueType, PhaseSize, Status
from sase.bead.plus_one_presentation import (
    PLUS_ONE_RICH_STYLE,
    POST_CLOSE_RICH_STYLE,
    post_close_plus_one_badge,
    post_close_plus_one_count,
    plus_one_badge,
    plus_one_reports_label,
)
from sase.bead.snooze_presentation import (
    SNOOZE_RICH_STYLE,
    snooze_wake_chip,
)
from sase.bead_status_presentation import bead_status_presentation
from sase.bead_time_presentation import bead_created_label
from sase.bead_type_presentation import bead_type_chip
from sase.core.time import format_local
from sase.phase_size_presentation import phase_size_chip

from ...keymaps import KeymapRegistry, key_display_name
from .beads_data import BeadsSnapshot, PendingTriage
from .beads_data_models import ExternalIssueLink
from .beads_detail_body import (
    close_history_markdown as _close_history_markdown,
    flag_markdown as _flag_markdown,
    plus_one_evidence_markdown as _plus_one_evidence_markdown,
)
from .beads_detail_external import (
    external_issue_inline as _external_issue_inline,
    external_issue_markdown as _external_issue_markdown,
    external_issue_property_text as _external_issue_property_text,
)
from .beads_detail_properties import (
    DetailProperty,
    created_text as _created_text,
    dependencies_text as _dependencies_text,
    dependency_state as _dependency_state,
    epic_phase_sizes as _epic_phase_sizes,
    flag_properties as _flag_properties,
    plan_reference_properties as _plan_reference_properties,
    previously_closed_text as _previously_closed_text,
    properties_header as _properties_header,
    readiness_chip as _readiness_chip,
    readiness_label as _readiness_label,
    references_text as _references_text,
    resolved_plan_path,
    snooze_text as _snooze_text,
    status_chip as _status_chip,
)


def bead_properties_header(
    issue: Issue,
    snapshot: BeadsSnapshot | None,
    *,
    project: str,
    project_name: str,
    external_links: tuple[ExternalIssueLink, ...] = (),
) -> RenderableType:
    """Build a bead title and the complete shared property grid."""
    status = bead_status_presentation(issue.status)
    title = Text(f"{status.tui_glyph} ", style=status.rich_style)
    title.append(issue.id, style="bold #FFD700")
    title.append(f" · {issue.title}", style="bold white")
    if badge := plus_one_badge(issue.plus_one_count):
        title.append(f"  [{badge}]", style=PLUS_ONE_RICH_STYLE)
    if post_close := post_close_plus_one_badge(post_close_plus_one_count(issue)):
        title.append(f"  [{post_close}]", style=POST_CLOSE_RICH_STYLE)
    if issue.snooze is not None and (chip := snooze_wake_chip(issue.snooze.until)):
        title.append(f"  [{chip}]", style=SNOOZE_RICH_STYLE)
    properties: list[DetailProperty] = [
        ("ID", issue.id),
        ("Type", bead_type_chip(issue.issue_type)),
        ("Status", _status_chip(issue.status)),
        ("Readiness", _readiness_chip(issue, snapshot, project=project)),
    ]
    properties.extend(_flag_properties(issue, snapshot, project=project))
    if issue.tier is not None:
        properties.append(("Tier", issue.tier.value))
    if issue.issue_type in (IssueType.PHASE, IssueType.TASK):
        properties.append(("Size", phase_size_chip(issue.size or PhaseSize.SMALL)))
    if issue.plus_one_count:
        properties.append(("+1 reports", plus_one_reports_label(issue.plus_one_count)))
    if post_close_count := post_close_plus_one_count(issue):
        properties.append(
            ("Post-close +1", f"{post_close_count} recorded after current close")
        )
    if issue.snooze is not None:
        properties.append(("Snooze", _snooze_text(issue)))
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
    if issue.close_history:
        properties.append(
            ("Previously closed", _previously_closed_text(issue.close_history))
        )
    properties.extend(
        [
            ("Assignee", issue.assignee),
            ("Owner", issue.owner),
            ("Model", issue.model),
            ("Created", _created_text(issue)),
            ("Updated", format_local(issue.updated_at, default="")),
            ("Closed", format_local(issue.closed_at, default="")),
            ("Project", project_name),
            (
                "Dependencies",
                _dependencies_text(issue, snapshot, project=project),
            ),
            ("External issue", _external_issue_property_text(external_links)),
            ("References", _references_text(issue)),
            ("Patch", issue.patch_name),
            (
                "External bug",
                f"#{issue.patch_bug_id}" if issue.patch_bug_id else "",
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
    external_links: tuple[ExternalIssueLink, ...] = (),
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
    lines.extend(_close_history_markdown(issue))
    lines.extend(_flag_markdown(issue))
    lines.extend(_external_issue_markdown(issue, external_links))
    lines.extend(["## Description", "", issue.description or "_No description._"])
    lines.extend(_plus_one_evidence_markdown(issue))
    if issue.notes.strip():
        lines.extend(["", "## Notes", "", issue.notes])
    return "\n".join(lines)


def bead_preview_markdown(
    issue: Issue,
    snapshot: BeadsSnapshot | None,
    *,
    project: str,
    registry: KeymapRegistry | None = None,
    external_links: tuple[ExternalIssueLink, ...] = (),
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
    if issue.flag is not None:
        record = issue.flag
        lines.extend(
            [
                f"**Flag key:** {record.key}  ",
                f"**Remove by date:** {record.remove_by_date}  ",
                f"**Remove by release:** v{record.remove_by_release}  ",
            ]
        )
        due = None if snapshot is None else snapshot.flag_due.get((project, issue.id))
        if due is not None:
            lines.append(f"**Due state:** {due.state} ({due.label})  ")
    if issue.plus_one_count:
        lines.append(f"**+1 reports:** {issue.plus_one_count}  ")
    if issue.snooze is not None:
        lines.append(f"**Snooze:** {_snooze_text(issue).plain}  ")
    if issue.assignee:
        lines.append(f"**Assignee:** {issue.assignee}  ")
    if issue.owner:
        lines.append(f"**Owner:** {issue.owner}  ")
    if issue.model:
        lines.append(f"**Model:** {issue.model}  ")
    if issue.patch_name:
        lines.append(f"**Patch:** {issue.patch_name}  ")
    if issue.patch_bug_id:
        lines.append(f"**External bug:** #{issue.patch_bug_id}  ")
    for index, link in enumerate(external_links):
        label = (
            "**External issue:**" if index == 0 else " " * len("**External issue:**")
        )
        lines.append(f"{label} {_external_issue_inline(link)}  ")
    if issue.design.strip():
        lines.append(f"**Plan reference:** {issue.design.strip()}  ")
        path = (
            "" if snapshot is None else snapshot.plan_links.get((project, issue.id), "")
        )
        lines.append(f"**Linked plan:** {path or 'cannot resolve'}  ")
    for index, reference in enumerate(issue.refs):
        label = "**References:**" if index == 0 else " " * len("**References:**")
        lines.append(f"{label} {reference}  ")
    lines.extend(
        [
            "",
            bead_body_markdown(
                issue,
                triage,
                registry=registry,
                external_links=external_links,
            ),
        ]
    )
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
            f"- Created: {bead_created_label(issue.created_at)}",
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


__all__ = [
    "bead_body_markdown",
    "bead_preview_markdown",
    "bead_properties_header",
    "resolved_plan_path",
]
