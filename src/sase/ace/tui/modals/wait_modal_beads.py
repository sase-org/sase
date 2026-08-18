"""Bead row rendering and preview shaping for the Agents-tab Wait modal."""

from __future__ import annotations

from dataclasses import dataclass

from rich.text import Text
from textual.widgets.option_list import Option

from sase.ace.tui.models.wait_bead_catalog import (
    WaitBeadCandidate,
    WaitBeadCatalog,
    classify_wait_bead_selection,
)
from sase.bead_status_presentation import bead_status_presentation
from sase.bead_time_presentation import BEAD_CREATED_GLYPH, bead_age_label
from sase.bead_type_presentation import bead_type_presentation
from sase.task_type_presentation import task_type_presentation

_ID_WIDTH = 16
_TITLE_WIDTH = 32


@dataclass(frozen=True)
class BeadsValidation:
    """Mirrors ``TimeValidation``'s shape for the beads field's live preview."""

    valid: bool
    bead_ids: list[str]
    message: str
    css_class: str
    guard_armed: bool = False


def validate_beads_selection(
    catalog: WaitBeadCatalog | None,
    bead_ids: list[str],
    *,
    own_bead_ids: frozenset[str],
    project_label: str,
) -> BeadsValidation:
    """Classify a typed bead-wait selection and shape it for the modal."""
    preview = classify_wait_bead_selection(
        catalog,
        bead_ids,
        own_bead_ids=own_bead_ids,
        project_label=project_label,
    )
    return BeadsValidation(
        valid=not preview.guard_armed,
        bead_ids=bead_ids,
        message=preview.message,
        css_class=preview.css_class,
        guard_armed=preview.guard_armed,
    )


def _truncate(value: str, width: int) -> str:
    """Truncate *value* to a fixed display width."""
    if len(value) <= width:
        return value
    if width <= 1:
        return value[:width]
    return value[: width - 1] + "…"


def bead_candidate_option(
    candidate: WaitBeadCandidate,
    index: int,
    *,
    selected_ids: frozenset[str] = frozenset(),
) -> Option:
    """Render one bead completion row."""
    status_presentation = bead_status_presentation(candidate.status)
    type_presentation = bead_type_presentation(candidate.type_label)
    age = bead_age_label(candidate.created_at)

    text = Text()
    text.append(
        f"{status_presentation.tui_glyph} ", style=status_presentation.rich_style
    )
    text.append(f"{_truncate(candidate.bead_id, _ID_WIDTH):<{_ID_WIDTH}}", style="bold")
    text.append(" ")
    text.append(f"{_truncate(candidate.title, _TITLE_WIDTH):<{_TITLE_WIDTH}}")
    text.append("  ")
    text.append(status_presentation.label, style="dim")
    text.append(" · ", style="dim")
    text.append(
        f"{type_presentation.glyph} {candidate.type_label}",
        style=type_presentation.rich_style,
    )
    if candidate.type_label == "task":
        task_presentation = task_type_presentation(candidate.task_type)
        text.append(" ")
        text.append(task_presentation.glyph, style=task_presentation.rich_style)
    if age:
        text.append(" · ", style="dim")
        text.append(f"{BEAD_CREATED_GLYPH} {age}", style="dim")
    if candidate.bead_id in selected_ids:
        text.append(" · selected", style="dim")
    return Option(text, id=f"wait-bead-{index}")


def loading_bead_option() -> Option:
    """Return the placeholder row shown while the bead catalog loads."""
    return Option(Text("  loading beads…", style="dim"), disabled=True)


def empty_bead_option() -> Option:
    """Return the placeholder row shown when no bead matches the filter."""
    return Option(Text("  no matching beads", style="dim"), disabled=True)


def overflow_bead_option(omitted: int) -> Option:
    """Return the trailing row reporting rows omitted by the render cap."""
    return Option(Text(f"  …{omitted} more — keep typing", style="dim"), disabled=True)


__all__ = [
    "BeadsValidation",
    "bead_candidate_option",
    "empty_bead_option",
    "loading_bead_option",
    "overflow_bead_option",
    "validate_beads_selection",
]
