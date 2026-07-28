"""Pure Rich presentation helpers for immutable plan-display values."""

from __future__ import annotations

from dataclasses import dataclass
import os

from rich.cells import cell_len
from rich.console import Console
from rich.text import Text

from sase.phase_size_presentation import (
    PHASE_SIZE_CHIP_WIDTH,
    phase_size_chip,
)
from sase.sdd.plan_header_block import PlanHeaderSectionKind

from ._plan_display_models import (
    PlanDisplay,
    PlanDisplayPhase,
    _PlanProvenanceSection,
)

PLAN_SECTION_LABEL = "PLAN"
PLAN_SECTION_MAX_WIDTH = 80
PLAN_FIELD_LABEL_WIDTH = cell_len("  Title: ")

COLOR_PLAN_SUBHEADER = "bold #AF87FF"
COLOR_PLAN_PRIMARY = "bold #D7AFFF"
COLOR_PLAN_PATH = "#87AFFF"
COLOR_PLAN_PATH_BASENAME = "bold #87AFFF"
COLOR_PLAN_REASON = "#D7D7AF"
COLOR_PLAN_SUMMARY = "dim"
COLOR_PLAN_EMPTY = "dim italic"
PLAN_MISSING_SUFFIX_STYLE = "dim italic #FF8787"
PLAN_PHASE_ID_STYLE = "#AF87FF"
PLAN_PHASE_MODEL_STYLE = "italic #AF87FF"
PLAN_PROVENANCE_AGENT_STYLE = "#87D7AF"
PLAN_PROVENANCE_COMMIT_STYLE = "#D7AF87"
PLAN_PROVENANCE_ENTRY_LIMIT = 6

_PROVENANCE_ROW_LABELS: dict[PlanHeaderSectionKind, str] = {
    PlanHeaderSectionKind.PLAN: "   Plan: ",
    PlanHeaderSectionKind.PROMPT: " Prompt: ",
    PlanHeaderSectionKind.PARENT: " Parent: ",
    PlanHeaderSectionKind.AGENTS: " Agents: ",
    PlanHeaderSectionKind.COMMITS: "Commits: ",
}
_PROVENANCE_ENTRY_STYLES: dict[PlanHeaderSectionKind, str] = {
    PlanHeaderSectionKind.PLAN: COLOR_PLAN_PATH,
    PlanHeaderSectionKind.PROMPT: COLOR_PLAN_PATH,
    PlanHeaderSectionKind.PARENT: COLOR_PLAN_PATH,
    PlanHeaderSectionKind.AGENTS: PLAN_PROVENANCE_AGENT_STYLE,
    PlanHeaderSectionKind.COMMITS: PLAN_PROVENANCE_COMMIT_STYLE,
}


@dataclass(frozen=True, slots=True)
class _RenderedPlanDocument:
    """Width-aware leading lines and independently omittable phase blocks."""

    intro_lines: tuple[Text, ...]
    phase_blocks: tuple[tuple[Text, ...], ...]

    @property
    def lines(self) -> tuple[Text, ...]:
        return self.intro_lines + tuple(
            line for block in self.phase_blocks for line in block
        )


def plan_lane_header(summary: PlanDisplay) -> Text:
    """Build the styled PLAN lane header, including its trailing newline."""
    text = Text(end="")
    text.append(f"▸ {PLAN_SECTION_LABEL}", style=COLOR_PLAN_SUBHEADER)
    text.append(" · ", style=COLOR_PLAN_SUMMARY)
    text.append_text(plan_lane_details(summary))
    text.append("\n")
    return text


def plan_lane_details(summary: PlanDisplay) -> Text:
    """Build the tier and phase-count detail displayed beside PLAN."""
    text = Text()
    tier = summary.effective_tier
    if tier is None:
        text.append("tier unavailable", style=COLOR_PLAN_EMPTY)
        return text

    text.append(tier, style=COLOR_PLAN_SUMMARY)
    if summary.phase_availability == "available":
        text.append(" · ", style=COLOR_PLAN_SUMMARY)
        text.append(
            _count_phrase(len(summary.phases), "phase"),
            style=COLOR_PLAN_SUMMARY,
        )
    elif summary.phase_availability != "not-applicable":
        text.append(" · ", style=COLOR_PLAN_SUMMARY)
        text.append("phases unavailable", style=COLOR_PLAN_EMPTY)
    return text


def plan_field_rows(
    summary: PlanDisplay,
    *,
    hint_number: int | None = None,
) -> tuple[tuple[str, Text], ...]:
    """Build the canonical Title/Goal/Path rows in display order."""
    return (
        ("  Title: ", _title_value(summary)),
        ("   Goal: ", _goal_value(summary)),
        ("   Path: ", _path_value(summary, hint_number=hint_number)),
    )


def plan_provenance_rows(summary: PlanDisplay) -> tuple[tuple[str, Text], ...]:
    """Build the compact provenance rows shown under the canonical fields."""
    return tuple(
        (_PROVENANCE_ROW_LABELS[section.kind], _provenance_value(section))
        for section in summary.provenance
        if section.kind in _PROVENANCE_ROW_LABELS
    )


def _provenance_value(section: _PlanProvenanceSection) -> Text:
    style = _PROVENANCE_ENTRY_STYLES[section.kind]
    shown = section.entries[:PLAN_PROVENANCE_ENTRY_LIMIT]
    hidden = len(section.entries) - len(shown) + section.omitted
    text = Text()
    for index, entry in enumerate(shown):
        if index:
            text.append(", ", style=COLOR_PLAN_SUMMARY)
        text.append(entry, style=style)
    if hidden > 0:
        if shown:
            text.append(", ", style=COLOR_PLAN_SUMMARY)
        text.append(f"+{hidden} more", style=COLOR_PLAN_EMPTY)
    return text


def plan_phase_metadata(phase: PlanDisplayPhase) -> Text:
    """Build one phase's id/dependency/model metadata."""
    text = Text(phase.id, style=PLAN_PHASE_ID_STYLE)
    text.append(" · ", style=COLOR_PLAN_SUMMARY)
    if phase.depends_on:
        text.append(
            f"after {', '.join(phase.depends_on)}",
            style=COLOR_PLAN_SUMMARY,
        )
    else:
        text.append("no dependencies", style=COLOR_PLAN_SUMMARY)
    if phase.model:
        text.append(" · model ", style=COLOR_PLAN_SUMMARY)
        text.append(phase.model, style=PLAN_PHASE_MODEL_STYLE)
    text.overflow = "fold"
    text.no_wrap = False
    return text


def plan_phase_logical_text(ordinal: int, phase: PlanDisplayPhase) -> Text:
    """Build one complete, unwrapped logical phase block."""
    text = Text()
    text.append(f"  {ordinal} ", style=COLOR_PLAN_SUMMARY)
    text.append("◆ ", style=COLOR_PLAN_SUBHEADER)
    text.append(phase.title, style=COLOR_PLAN_PRIMARY)
    text.append_text(phase_size_chip(phase.size, width=PHASE_SIZE_CHIP_WIDTH))
    text.append("\n")
    text.append("    ")
    text.append_text(plan_phase_metadata(phase))
    text.append("\n")
    if phase.description:
        text.append("    ")
        text.append(phase.description, style=COLOR_PLAN_REASON)
        text.append("\n")
    return text


def plan_logical_text(
    summary: PlanDisplay,
    *,
    hint_number: int | None = None,
) -> Text:
    """Return the canonical unwrapped PLAN document used for search/copy."""
    text = plan_lane_header(summary)
    rows = (
        *plan_field_rows(summary, hint_number=hint_number),
        *plan_provenance_rows(summary),
    )
    for label, value in rows:
        text.append(label, style=COLOR_PLAN_SUMMARY)
        text.append_text(value)
        text.append("\n")
    if summary.phase_availability == "available":
        for ordinal, phase in enumerate(summary.phases, start=1):
            text.append_text(plan_phase_logical_text(ordinal, phase))
    return text


def render_plan_document(
    summary: PlanDisplay,
    *,
    width: int,
    hint_number: int | None = None,
) -> _RenderedPlanDocument:
    """Render complete Rich lines at ``width`` without filesystem access."""
    width = max(width, PLAN_FIELD_LABEL_WIDTH + 1)
    header = plan_lane_header(summary)
    header.rstrip()
    intro: list[Text] = [header]
    field_rows = plan_field_rows(summary, hint_number=hint_number)
    for index, (label, value) in enumerate(field_rows):
        preferred_break_before: int | None = None
        preferred_segment_width: int | None = None
        if index == len(field_rows) - 1:
            preferred_break_before, preferred_segment_width = _path_basename_wrap_hint(
                summary, hint_number=hint_number
            )
        intro.extend(
            _render_field_lines(
                label,
                value,
                width=width,
                preferred_break_before=preferred_break_before,
                preferred_segment_width=preferred_segment_width,
            )
        )
    for label, value in plan_provenance_rows(summary):
        intro.extend(_render_field_lines(label, value, width=width))

    phase_blocks: list[tuple[Text, ...]] = []
    if summary.phase_availability == "available":
        for ordinal, phase in enumerate(summary.phases, start=1):
            phase_blocks.append(_render_phase_block(ordinal, phase, width=width))
    return _RenderedPlanDocument(tuple(intro), tuple(phase_blocks))


def render_plan_lines(
    summary: PlanDisplay,
    *,
    width: int,
    hint_number: int | None = None,
) -> tuple[Text, ...]:
    """Return all width-aware PLAN lines in canonical order."""
    return render_plan_document(
        summary,
        width=width,
        hint_number=hint_number,
    ).lines


def _title_value(summary: PlanDisplay) -> Text:
    if summary.title:
        text = Text()
        text.append(summary.title, style=COLOR_PLAN_PRIMARY)
        return text
    return Text("unavailable", style=COLOR_PLAN_EMPTY)


def _goal_value(summary: PlanDisplay) -> Text:
    if summary.goal:
        return Text(summary.goal, style=COLOR_PLAN_REASON)
    return Text("unavailable", style=COLOR_PLAN_EMPTY)


def _path_value(summary: PlanDisplay, *, hint_number: int | None) -> Text:
    text = Text()
    if hint_number is not None:
        text.append(f"[{hint_number}] ", style="bold #FFFF00")
    path_style = COLOR_PLAN_PATH if summary.exists else f"dim {COLOR_PLAN_PATH}"
    basename_style = (
        COLOR_PLAN_PATH_BASENAME
        if summary.exists
        else f"dim {COLOR_PLAN_PATH_BASENAME}"
    )
    dirname, basename = os.path.split(summary.display_path)
    if dirname:
        text.append(dirname + "/", style=path_style)
    text.append(basename or summary.display_path, style=basename_style)
    if not summary.exists:
        text.append(" (missing)", style=PLAN_MISSING_SUFFIX_STYLE)
    return text


def _path_basename_wrap_hint(
    summary: PlanDisplay,
    *,
    hint_number: int | None,
) -> tuple[int, int]:
    """Return the character offset and cell width of the displayed basename."""
    hint_prefix = f"[{hint_number}] " if hint_number is not None else ""
    dirname, basename = os.path.split(summary.display_path)
    directory_prefix = dirname + "/" if dirname else ""
    displayed_basename = basename or summary.display_path
    return (
        len(hint_prefix) + len(directory_prefix),
        cell_len(displayed_basename),
    )


def _render_field_lines(
    label: str,
    value: Text,
    *,
    width: int,
    preferred_break_before: int | None = None,
    preferred_segment_width: int | None = None,
) -> tuple[Text, ...]:
    value_width = max(width - PLAN_FIELD_LABEL_WIDTH, 1)
    wrapped = _wrap(
        value,
        width=value_width,
        preferred_break_before=preferred_break_before,
        preferred_segment_width=preferred_segment_width,
    )
    if not wrapped:
        wrapped = [Text()]
    lines: list[Text] = []
    for index, value_line in enumerate(wrapped):
        line = Text()
        line.append(
            label if index == 0 else " " * PLAN_FIELD_LABEL_WIDTH,
            style=COLOR_PLAN_SUMMARY,
        )
        line.append_text(value_line)
        lines.append(line)
    return tuple(lines)


def _render_phase_block(
    ordinal: int,
    phase: PlanDisplayPhase,
    *,
    width: int,
) -> tuple[Text, ...]:
    ordinal_text = f"  {ordinal} "
    glyph = "◆ "
    prefix_width = cell_len(ordinal_text) + cell_len(glyph)
    title_width = max(width - prefix_width - PHASE_SIZE_CHIP_WIDTH, 1)
    title = Text(phase.title, style=COLOR_PLAN_PRIMARY)
    title_lines = _wrap(title, width=title_width) or [Text()]
    lines: list[Text] = []
    for index, title_line in enumerate(title_lines):
        line = Text()
        if index == 0:
            line.append(ordinal_text, style=COLOR_PLAN_SUMMARY)
            line.append(glyph, style=COLOR_PLAN_SUBHEADER)
        else:
            line.append(" " * prefix_width)
        line.append_text(title_line)
        if index == 0:
            padding = max(title_width - cell_len(title_line.plain), 0)
            line.append(" " * padding)
            line.append_text(phase_size_chip(phase.size, width=PHASE_SIZE_CHIP_WIDTH))
        lines.append(line)

    lines.extend(_render_indented_line(plan_phase_metadata(phase), width=width))
    if phase.description:
        lines.extend(
            _render_indented_line(
                Text(phase.description, style=COLOR_PLAN_REASON),
                width=width,
            )
        )
    return tuple(lines)


def _render_indented_line(value: Text, *, width: int) -> tuple[Text, ...]:
    indent = "    "
    wrapped = _wrap(value, width=max(width - cell_len(indent), 1)) or [Text()]
    lines: list[Text] = []
    for value_line in wrapped:
        line = Text(indent)
        line.append_text(value_line)
        lines.append(line)
    return tuple(lines)


def _wrap(
    value: Text,
    *,
    width: int,
    preferred_break_before: int | None = None,
    preferred_segment_width: int | None = None,
) -> list[Text]:
    if (
        preferred_break_before is not None
        and preferred_segment_width is not None
        and 0 < preferred_break_before < len(value)
        and preferred_segment_width <= width
        and cell_len(value.plain) > width
    ):
        before = _wrap(value[:preferred_break_before], width=width)
        after = _wrap(value[preferred_break_before:], width=width)
        return before + after

    copied = value.copy()
    copied.overflow = "fold"
    copied.no_wrap = False
    return list(copied.wrap(_console(width), width, overflow="fold"))


def _console(width: int) -> Console:
    return Console(
        width=max(width, 1),
        color_system=None,
        force_terminal=False,
        force_interactive=False,
        highlight=False,
        markup=False,
        emoji=False,
    )


def _count_phrase(count: int, singular: str) -> str:
    suffix = "" if count == 1 else "s"
    return f"{count} {singular}{suffix}"


__all__ = [
    "COLOR_PLAN_EMPTY",
    "COLOR_PLAN_PRIMARY",
    "COLOR_PLAN_REASON",
    "COLOR_PLAN_SUBHEADER",
    "COLOR_PLAN_SUMMARY",
    "PLAN_FIELD_LABEL_WIDTH",
    "PLAN_MISSING_SUFFIX_STYLE",
    "PLAN_PHASE_ID_STYLE",
    "PLAN_PHASE_MODEL_STYLE",
    "PLAN_PROVENANCE_AGENT_STYLE",
    "PLAN_PROVENANCE_COMMIT_STYLE",
    "PLAN_PROVENANCE_ENTRY_LIMIT",
    "PLAN_SECTION_LABEL",
    "PLAN_SECTION_MAX_WIDTH",
    "plan_field_rows",
    "plan_lane_details",
    "plan_lane_header",
    "plan_logical_text",
    "plan_phase_logical_text",
    "plan_phase_metadata",
    "plan_provenance_rows",
    "render_plan_document",
    "render_plan_lines",
]
