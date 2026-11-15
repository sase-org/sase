"""Pure render helpers for the ACE bead preview card."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text

from sase.bead.flag_fields import flag_fields, is_flag_bead
from sase.bead.model import BeadTier, Issue, IssueType, Resolution, Status
from sase.bead.plus_one_presentation import plus_one_badge
from sase.bead.snooze_presentation import snooze_wake_chip
from sase.bead_flag_presentation import (
    FLAG_ACCENT,
    FLAG_GLYPH,
    flag_due_chip,
    flag_key_chip,
)
from sase.bead_status_presentation import bead_status_presentation
from sase.bead_time_presentation import (
    BEAD_TIME_UNKNOWN_LABEL,
    bead_age_label,
    bead_created_label,
)
from sase.bead_type_presentation import BEAD_TYPE_PRESENTATIONS, bead_type_presentation
from sase.macro.highlight_theme import derive_argument_color
from sase.phase_size_presentation import PHASE_SIZE_ACCENTS, phase_size_chip
from sase.task_type_presentation import task_type_chip

from sase.ace.tui.models.bead_preview import BeadPreview

_COLOR_MUTED = "dim"
_COLOR_LABEL = "dim"
_COLOR_TITLE = "bold"
_FALLBACK_ACCENT = "#FFD700"
_PILL_FOREGROUND = "#1a1a1a"
_LOADING_GLYPH = "◌"
_PROGRESS_METER_CAP = 12
_NUMBERED_CHILD_CAP = 9


@dataclass(frozen=True)
class BeadCardPalette:
    """Contrast-adapted colors for the bead preview card."""

    plan: str
    phase: str
    task: str
    flag: str
    statuses: dict[str, str]
    sizes: dict[str, str]

    def type_color(self, key: str) -> str:
        """Return the adapted accent for a type key."""
        return {
            "plan": self.plan,
            "phase": self.phase,
            "task": self.task,
            "flag": self.flag,
        }[key]


def bead_card_palette(theme: Any) -> BeadCardPalette:
    """Return contrast-adapted type, status, and size colors."""
    background = getattr(theme, "background", None) or "#000000"
    foreground = getattr(theme, "foreground", None)

    def adapt(color: str) -> str:
        return (
            derive_argument_color(
                color,
                foreground=foreground,
                background=background,
            )
            or color
        )

    statuses = {
        name: adapt(presentation.rich_color)
        for name, presentation in (
            (status, bead_status_presentation(status))
            for status in (
                "open",
                "claimed",
                "ready",
                "snoozed",
                "in_progress",
                "closed",
            )
        )
    }
    sizes: dict[str, str] = {
        name: adapt(accent) for name, accent in PHASE_SIZE_ACCENTS.items()
    }
    return BeadCardPalette(
        plan=adapt(BEAD_TYPE_PRESENTATIONS["plan"].accent_color),
        phase=adapt(BEAD_TYPE_PRESENTATIONS["phase"].accent_color),
        task=adapt(BEAD_TYPE_PRESENTATIONS["task"].accent_color),
        flag=adapt(FLAG_ACCENT),
        statuses=statuses,
        sizes=sizes,
    )


def _bead_identity(issue: Issue) -> tuple[str, str, str]:
    """Return ``(glyph, label, type_key)`` for the identity row.

    *type_key* is ``plan``, ``phase``, ``task``, or ``flag``.
    """
    if is_flag_bead(issue):
        return FLAG_GLYPH, "FLAG", "flag"
    if issue.issue_type == IssueType.PLAN:
        glyph = bead_type_presentation(IssueType.PLAN).glyph
        if issue.tier == BeadTier.EPIC:
            return glyph, "EPIC", "plan"
        if issue.tier == BeadTier.PLAN:
            return glyph, "TALE", "plan"
        return glyph, "PLAN", "plan"
    if issue.issue_type == IssueType.PHASE:
        glyph = bead_type_presentation(IssueType.PHASE).glyph
        return glyph, "PHASE", "phase"
    glyph = bead_type_presentation(IssueType.TASK).glyph
    task_type = (issue.task_type or "").strip()
    if task_type:
        return glyph, f"TASK · {task_type}", "task"
    return glyph, "TASK", "task"


def build_bead_loading_title(
    bead_id: str,
    *,
    project_label: str,
    accent: str,
    breadcrumb: str | None = None,
) -> RenderableType:
    """Build the loading-state identity row: ``◌ <id>`` plus project."""
    identity = Text()
    identity.append(_LOADING_GLYPH, style=f"bold {accent}")
    identity.append(" ")
    identity.append(bead_id, style=_COLOR_TITLE)
    if project_label:
        first_line = Table.grid(expand=True, padding=(0, 0, 0, 2))
        first_line.add_column(ratio=1, overflow="ellipsis")
        first_line.add_column(justify="right", no_wrap=True)
        first_line.add_row(identity, Text(project_label, style=f"bold {accent}"))
        lines: list[RenderableType] = [first_line]
    else:
        lines = [identity]
    return _with_breadcrumb(lines, breadcrumb)


def build_bead_title(
    issue: Issue,
    *,
    project_label: str,
    palette: BeadCardPalette,
    children: tuple[Issue, ...] = (),
    breadcrumb: str | None = None,
) -> RenderableType:
    """Build the identity row, title, and chip row."""
    glyph, label, type_key = _bead_identity(issue)
    accent = palette.type_color(type_key)
    identity = Text()
    identity.append(glyph, style=f"bold {accent}")
    identity.append(" ")
    identity.append(label, style=f"bold {accent}")
    identity.append("  ")
    identity.append(issue.id, style=_COLOR_TITLE)

    if project_label:
        first_line = Table.grid(expand=True, padding=(0, 0, 0, 2))
        first_line.add_column(ratio=1, overflow="ellipsis")
        first_line.add_column(justify="right", no_wrap=True)
        first_line.add_row(identity, Text(project_label, style=f"bold {accent}"))
        lines: list[RenderableType] = [first_line]
    else:
        lines = [identity]

    title = (issue.title or "").strip()
    if title:
        lines.append(Text(title, style=_COLOR_TITLE))
    chips = _build_bead_chips(issue, palette=palette, children=children)
    if chips.plain.strip():
        lines.append(chips)
    return _with_breadcrumb(lines, breadcrumb)


def _build_bead_chips(
    issue: Issue,
    *,
    palette: BeadCardPalette,
    children: tuple[Issue, ...] = (),
) -> Text:
    """Build the status / size / type / flag / snooze / +1 / resolution chips."""
    text = Text()
    try:
        presentation = bead_status_presentation(issue.status)
    except ValueError:
        presentation = None
    if presentation is not None:
        status_key = (
            issue.status.value
            if isinstance(issue.status, Status)
            else str(issue.status)
        )
        color = palette.statuses.get(status_key, presentation.rich_color)
        human = presentation.label.replace("_", " ").lower()
        _append_chip(
            text,
            f"{presentation.tui_glyph} {human}",
            accent=color,
        )
    if issue.size is not None:
        _append_rich(text, phase_size_chip(issue.size))
    if issue.issue_type == IssueType.TASK and issue.task_type:
        _append_rich(text, task_type_chip(issue.task_type))
    fields = flag_fields(issue)
    if fields is not None:
        _append_rich(text, flag_key_chip(fields.key))
        try:
            due = flag_due_chip(
                fields.remove_by_date,
                fields.remove_by_release,
                today=date.today(),
                release=_current_release(),
            )
        except (ValueError, TypeError):
            due = None
        if due is not None and due.plain.strip():
            _append_rich(text, due)
    if issue.snooze is not None:
        wake = snooze_wake_chip(issue.snooze.until)
        if wake:
            _append_chip(text, wake, accent=palette.statuses.get("snoozed", "#6C6C6C"))
    badge = plus_one_badge(issue.plus_one_count)
    if badge:
        _append_chip(text, badge, accent=palette.task)
    if issue.status == Status.CLOSED and issue.resolution is not None:
        resolution = (
            issue.resolution.value
            if isinstance(issue.resolution, Resolution)
            else str(issue.resolution)
        )
        if resolution:
            _append_chip(
                text,
                resolution,
                accent=palette.statuses.get("closed", "#5FD787"),
            )
    if issue.issue_type == IssueType.PLAN and children:
        meter = _build_bead_progress_meter(children, palette=palette)
        if meter.plain.strip():
            if text.plain:
                text.append("  ")
            text.append_text(meter)
    return text


def build_bead_meta(
    preview: BeadPreview,
    *,
    accent: str | None = None,
) -> RenderableType:
    """Build the dim-label property grid for a loaded preview."""
    issue = preview.issue
    rows: list[tuple[str, str | Text]] = []
    project_label = preview.store.project_label
    if project_label:
        rows.append(("Project", project_label))
    plan_row = _plan_row(preview)
    if plan_row is not None:
        rows.append(plan_row)
    if issue.assignee:
        rows.append(("Assignee", issue.assignee))
    if issue.owner:
        rows.append(("Owner", issue.owner))
    if issue.model:
        rows.append(("Model", issue.model))
    created = bead_created_label(issue.created_at)
    if created and created != BEAD_TIME_UNKNOWN_LABEL:
        rows.append(("Created", created))
    updated = _relative_age(issue.updated_at)
    if updated:
        rows.append(("Updated", updated))
    if issue.status == Status.CLOSED:
        closed = _closed_value(issue)
        if closed:
            rows.append(("Closed", closed))
    notes = _notes_value(issue)
    if notes is not None:
        rows.append(("Notes", notes))

    grid = Table.grid(expand=True, padding=(0, 2, 0, 0))
    grid.add_column(no_wrap=True)
    grid.add_column(ratio=1, overflow="fold")
    for label, value in rows:
        rendered = value if isinstance(value, Text) else Text(value, style=accent or "")
        grid.add_row(Text(label, style=_COLOR_LABEL), rendered)
    return grid


def bead_description_markdown(issue: Issue) -> str:
    """Return description Markdown, or empty when the body should stay dim."""
    return (issue.description or "").strip()


def _build_bead_progress_meter(
    children: tuple[Issue, ...],
    *,
    palette: BeadCardPalette,
) -> Text:
    """Build the chip-row meter: per-child glyphs, cap, and closed count."""
    text = Text()
    if not children:
        return text
    closed = sum(1 for child in children if _is_closed(child))
    shown = children[:_PROGRESS_METER_CAP]
    for child in shown:
        glyph, color = _status_glyph(child, palette)
        text.append(glyph, style=color)
    if len(children) > _PROGRESS_METER_CAP:
        text.append("…", style=_COLOR_MUTED)
    text.append(f" {closed}/{len(children)} phases closed", style=_COLOR_MUTED)
    return text


def build_bead_related(
    preview: BeadPreview,
    *,
    palette: BeadCardPalette,
) -> RenderableType | None:
    """Build lineage, children, and dependency rows above the meta grid."""
    sections: list[RenderableType] = []
    lineage = _lineage_rows(preview.ancestors, palette=palette)
    if lineage:
        sections.extend(lineage)
    children_block = _children_block(
        preview.issue.id,
        preview.children,
        heading=_children_heading(preview.issue),
        palette=palette,
    )
    if children_block is not None:
        sections.append(children_block)
    blocked = _dependency_block(
        "Blocked by",
        preview.depends_on,
        palette=palette,
    )
    if blocked is not None:
        sections.append(blocked)
    blocks = _dependency_block("Blocks", preview.blocks, palette=palette)
    if blocks is not None:
        sections.append(blocks)
    if not sections:
        return None
    return Group(*sections)


def numbered_child_count(children: tuple[Issue, ...]) -> int:
    """Return how many children have a 1-9 drill-down number."""
    return min(len(children), _NUMBERED_CHILD_CAP)


def children_are_phases(issue: Issue) -> bool:
    """Return whether the children heading is ``PHASES``."""
    return issue.issue_type == IssueType.PLAN


def _children_heading(issue: Issue) -> str:
    return "PHASES" if children_are_phases(issue) else "CHILDREN"


def _lineage_rows(
    ancestors: tuple[Issue | None, ...],
    *,
    palette: BeadCardPalette,
) -> list[Text]:
    rows: list[Text] = []
    for ancestor in ancestors:
        rows.append(_lineage_row(ancestor, palette=palette))
    return rows


def _lineage_row(ancestor: Issue | None, *, palette: BeadCardPalette) -> Text:
    text = Text()
    if ancestor is None:
        text.append("Parent", style=_COLOR_LABEL)
        text.append("  ?")
        return text
    text.append(_lineage_label(ancestor), style=_COLOR_LABEL)
    text.append("  ")
    glyph, color = _status_glyph(ancestor, palette)
    text.append(glyph, style=color)
    text.append(" ")
    text.append(ancestor.id)
    title = (ancestor.title or "").strip()
    if title:
        text.append(" · ")
        text.append(title)
    return text


def _lineage_label(ancestor: Issue) -> str:
    if ancestor.issue_type == IssueType.PLAN:
        if ancestor.tier == BeadTier.EPIC:
            return "Epic"
        return "Plan"
    return "Parent"


def _children_block(
    parent_id: str,
    children: tuple[Issue, ...],
    *,
    heading: str,
    palette: BeadCardPalette,
) -> RenderableType | None:
    if not children:
        return None
    rows: list[RenderableType] = [Text(heading, style=_COLOR_LABEL)]
    for index, child in enumerate(children, start=1):
        rows.append(
            _child_row(
                parent_id,
                child,
                index=index,
                palette=palette,
            )
        )
    return Group(*rows)


def _child_row(
    parent_id: str,
    child: Issue,
    *,
    index: int,
    palette: BeadCardPalette,
) -> RenderableType:
    closed = _is_closed(child)
    dim = _COLOR_MUTED if closed else ""
    left = Text()
    if index <= _NUMBERED_CHILD_CAP:
        left.append(f"{index} ", style=dim)
    else:
        left.append("  ", style=dim)
    glyph, color = _status_glyph(child, palette)
    glyph_style = f"{color} {dim}".strip() if dim else color
    left.append(glyph, style=glyph_style)
    left.append(" ")
    left.append(_relative_child_id(parent_id, child.id), style=dim)
    title = (child.title or "").strip()
    if title:
        left.append("  ")
        left.append(title, style=dim)
    size = Text("")
    if child.size is not None:
        size = phase_size_chip(child.size)
        if closed and size.plain.strip():
            size.stylize(_COLOR_MUTED)
    grid = Table.grid(expand=True, padding=(0, 0, 0, 2))
    grid.add_column(ratio=1, overflow="ellipsis")
    grid.add_column(justify="right", no_wrap=True)
    grid.add_row(left, size)
    return grid


def _relative_child_id(parent_id: str, child_id: str) -> str:
    prefix = f"{parent_id}."
    if child_id.startswith(prefix):
        return child_id[len(parent_id) :]
    return child_id


def _dependency_block(
    heading: str,
    issues: tuple[Issue | None, ...],
    *,
    palette: BeadCardPalette,
) -> RenderableType | None:
    if not issues:
        return None
    rows: list[RenderableType] = [Text(heading, style=_COLOR_LABEL)]
    for issue in issues:
        rows.append(_dependency_row(issue, palette=palette))
    return Group(*rows)


def _dependency_row(issue: Issue | None, *, palette: BeadCardPalette) -> Text:
    text = Text()
    if issue is None:
        text.append("?")
        return text
    glyph, color = _status_glyph(issue, palette)
    text.append(glyph, style=color)
    text.append(" ")
    text.append(issue.id)
    title = (issue.title or "").strip()
    if title:
        text.append(" · ")
        text.append(title)
    return text


def _status_glyph(issue: Issue, palette: BeadCardPalette) -> tuple[str, str]:
    try:
        presentation = bead_status_presentation(issue.status)
    except ValueError:
        return "?", _COLOR_MUTED
    status_key = _status_value(issue.status)
    color = palette.statuses.get(status_key, presentation.rich_color)
    return presentation.tui_glyph, color


def _status_value(status: Status | str) -> str:
    return status.value if isinstance(status, Status) else str(status)


def _is_closed(issue: Issue) -> bool:
    return _status_value(issue.status) == Status.CLOSED.value


def _with_breadcrumb(
    lines: list[RenderableType],
    breadcrumb: str | None,
) -> RenderableType:
    if breadcrumb:
        crumb = Text()
        crumb.append("⌫ ", style=_COLOR_MUTED)
        crumb.append(breadcrumb, style=_COLOR_MUTED)
        lines.insert(0, crumb)
    if len(lines) == 1:
        return lines[0]
    return Group(*lines)


def _abbreviate_home(path: str) -> str:
    """Replace the home directory prefix with ``~``."""
    home = str(Path.home())
    prefix = home.rstrip("/\\")
    if path == prefix or path == home:
        return "~"
    sep = "/" if "/" in home else "\\"
    if path.startswith(prefix + sep):
        return "~" + path[len(prefix) :]
    return path


def _plan_row(preview: BeadPreview) -> tuple[str, str | Text] | None:
    label = "Plan (epic)" if preview.plan_source == "parent" else "Plan"
    if preview.plan_path:
        return label, _abbreviate_home(preview.plan_path)
    if preview.plan_reference:
        value = Text(preview.plan_reference)
        value.append(" cannot resolve", style="bold red")
        return label, value
    if preview.plan_source is not None:
        return label, Text("cannot resolve", style="bold red")
    return None


def _closed_value(issue: Issue) -> str:
    closed = _relative_age(issue.closed_at)
    reason = (issue.close_reason or "").strip()
    if closed and reason:
        return f"{closed} · {reason}"
    if closed:
        return closed
    return reason


def _notes_value(issue: Issue) -> Text | None:
    notes = issue.notes
    if not notes:
        return None
    latest = notes[-1]
    count = len(notes)
    age = bead_age_label(latest.timestamp)
    if age == "now":
        summary = f"{count} · latest now"
    elif age:
        summary = f"{count} · latest {age} ago"
    else:
        summary = str(count)
    text = Text(summary)
    preview_lines = "\n".join((latest.text or "").splitlines()[:3]).strip()
    if preview_lines:
        text.append("\n")
        text.append(preview_lines, style=_COLOR_MUTED)
    return text


def _relative_age(value: str | None) -> str:
    age = bead_age_label(value)
    if not age:
        return ""
    if age == "now":
        return age
    return f"{age} ago"


def _current_release() -> str:
    import sase

    return str(getattr(sase, "__version__", "") or "")


def _append_chip(text: Text, label: str, *, accent: str) -> None:
    if text.plain:
        text.append(" ")
    text.append(f" {label} ", style=f"bold {_PILL_FOREGROUND} on {accent}")


def _append_rich(text: Text, chip: Text) -> None:
    if not chip.plain.strip():
        return
    if text.plain:
        text.append(" ")
    text.append_text(chip)


__all__ = [
    "BeadCardPalette",
    "bead_card_palette",
    "bead_description_markdown",
    "build_bead_loading_title",
    "build_bead_meta",
    "build_bead_related",
    "build_bead_title",
    "children_are_phases",
    "numbered_child_count",
]
