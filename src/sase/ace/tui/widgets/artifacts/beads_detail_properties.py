"""Property-grid rows and chips for the shared bead presentation."""

from __future__ import annotations

from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text

from sase.bead.flag_fields import flag_fields
from sase.bead_flag_presentation import flag_key_chip
from sase.bead.model import CloseRecord, Issue, PhaseSize, Status
from sase.bead.reopen_presentation import (
    REOPEN_RICH_STYLE,
    close_history_display_order,
    close_record_label,
    reopen_badge,
)
from sase.bead.snooze_presentation import (
    SNOOZE_ACCENT,
    snooze_plus_one_label,
    snooze_until_label,
)
from sase.bead_status_presentation import bead_status_presentation
from sase.bead_time_presentation import (
    BEAD_TIME_RICH_STYLE,
    BEAD_TIME_UNKNOWN_LABEL,
    bead_created_label,
)
from sase.phase_size_presentation import (
    PHASE_SIZE_STYLES,
    PHASE_SIZE_VALUES,
    normalize_phase_size,
)

from .beads_data import BeadsSnapshot

DetailProperty = tuple[str, str | Text]


def properties_header(
    title: Text,
    properties: list[DetailProperty],
) -> RenderableType:
    table = Table.grid(padding=(0, 1), expand=True)
    table.add_column(justify="right", style="dim", no_wrap=True)
    table.add_column(ratio=1, overflow="fold")
    for label, value in properties:
        text = _property_text(value)
        if not text.plain.strip():
            continue
        table.add_row(label, text)
    divider = Text("─" * 72, style="dim #5F5F87", no_wrap=True, overflow="crop")
    return Group(title, table, divider)


def resolved_plan_path(
    issue: Issue,
    snapshot: BeadsSnapshot | None,
    *,
    project: str,
) -> str | None:
    if snapshot is None:
        return None
    return snapshot.plan_links.get((project, issue.id)) or None


def flag_properties(
    issue: Issue,
    snapshot: BeadsSnapshot | None,
    *,
    project: str,
) -> list[DetailProperty]:
    fields = flag_fields(issue)
    if fields is None:
        return []
    due = None if snapshot is None else snapshot.flag_due.get((project, issue.id))
    properties: list[DetailProperty] = [
        ("Flag", flag_key_chip(fields.key)),
        (
            "Removal",
            f"{fields.remove_by_date} · v{fields.remove_by_release}",
        ),
    ]
    if due is not None:
        due_text = Text(due.label, style=due.style.rich)
        due_text.append(f"  {due.state}", style="dim")
        properties.append(("Due state", due_text))
    return properties


def plan_reference_properties(
    issue: Issue,
    snapshot: BeadsSnapshot | None,
    *,
    project: str,
) -> tuple[DetailProperty, ...]:
    reference = issue.design.strip()
    if not reference:
        return ()
    resolved = resolved_plan_path(issue, snapshot, project=project)
    if resolved is None:
        return (
            ("Plan reference", reference),
            ("Linked plan", Text("cannot resolve", style="#FF8787")),
        )
    return (("Plan reference", reference), ("Linked plan", resolved))


def previously_closed_text(history: list[CloseRecord]) -> Text:
    latest = close_history_display_order(history)[0]
    text = Text(reopen_badge(len(history)), style=REOPEN_RICH_STYLE)
    text.append(f"  {close_record_label(latest)}", style="white")
    return text


def references_text(issue: Issue) -> Text:
    if not issue.refs:
        return Text()
    text = Text()
    for index, reference in enumerate(issue.refs):
        if index:
            text.append("\n")
        text.append(reference, style="white")
    return text


def dependencies_text(
    issue: Issue,
    snapshot: BeadsSnapshot | None,
    *,
    project: str,
) -> Text:
    if not issue.dependencies:
        return Text()
    text = Text()
    statuses = {status.value: status for status in Status}
    for index, dependency in enumerate(issue.dependencies):
        if index:
            text.append("\n")
        state = dependency_state(snapshot, dependency.depends_on_id, project=project)
        status = statuses.get(state)
        glyph = "?" if status is None else bead_status_presentation(status).tui_glyph
        style = "dim" if status is None else bead_status_presentation(status).rich_style
        text.append(glyph, style=style)
        text.append(f" {dependency.depends_on_id}", style="white")
        text.append(f"  {state.replace('_', ' ')}", style=style)
    return text


def epic_phase_sizes(
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


def dependency_state(
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
    for item in snapshot.flags:
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


def created_text(issue: Issue) -> Text:
    """Render the shared creation label in the provenance accent."""
    label = bead_created_label(issue.created_at)
    if label == BEAD_TIME_UNKNOWN_LABEL:
        return Text()
    return Text(label, style=BEAD_TIME_RICH_STYLE, overflow="fold")


def status_chip(status: Status) -> Text:
    presentation = bead_status_presentation(status)
    return _chip(
        presentation.label.replace("_", " ").lower(),
        presentation.rich_color,
        glyph=presentation.tui_glyph,
    )


def snooze_text(issue: Issue) -> Text:
    """Render the wake conditions in one cell, wake time first."""
    record = issue.snooze
    assert record is not None
    parts = [snooze_until_label(record.until)]
    if plus_one := snooze_plus_one_label(issue):
        parts.append(f"+1 target: {plus_one}")
    if record.reason:
        parts.append(record.reason)
    return Text(" · ".join(parts), style=SNOOZE_ACCENT, overflow="fold")


def _property_text(value: str | Text) -> Text:
    if isinstance(value, Text):
        return value
    return Text(value, style="white", overflow="fold")


def _chip(label: str, color: str, *, glyph: str = "") -> Text:
    prefix = f"{glyph} " if glyph else ""
    text = Text()
    text.append(f" {prefix}{label} ", style=f"bold #1a1a1a on {color}")
    text.append(" ")
    return text


__all__ = [
    "DetailProperty",
    "created_text",
    "dependencies_text",
    "dependency_state",
    "epic_phase_sizes",
    "flag_properties",
    "plan_reference_properties",
    "previously_closed_text",
    "properties_header",
    "references_text",
    "resolved_plan_path",
    "snooze_text",
    "status_chip",
]
