"""Shared rendering language for tribe detail documents."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from rich.text import Text

from ...models.fold_scale import TRIBE_FOLD_SCALE
from ...models.fold_state import FoldLevel
from ...models.tribe_display import TRIBE_IDENTITY_FALLBACK_COLOR
from ._fold_language import append_fold_glyph, fold_count_style
from ._helpers import append_major_section_divider, append_section_heading

TRIBE_IDENTITY_COLOR = TRIBE_IDENTITY_FALLBACK_COLOR

FIELD_LABEL_STYLE = "bold #87D7FF"
SECTION_HEADING_STYLE = f"bold {TRIBE_IDENTITY_COLOR} underline"
BODY_STYLE = "#D7D7FF"
TRIAGE_LIMIT = 8
STATUS_STYLES: dict[str, str] = {
    "Stopped": "bold #FFAF5F",
    "Starting": "bold #87D7FF",
    "Running": "bold #FFD700",
    "Queued": "bold #5F87FF",
    "Waiting": "bold #AF87FF",
    "Failed": "bold #FF5F5F",
    "Done": "bold #5FD75F",
}


@dataclass(frozen=True, slots=True)
class _TribeSectionIds:
    attention: str = "tribe:needs-attention"
    members: str = "tribe:members"
    errors: str = "tribe:errors"
    output_variables: str = "tribe:output-variables"
    workflow_variables: str = "tribe:workflow-variables"
    replies: str = "tribe:replies"
    slow_tool_calls: str = "tribe:slow-tool-calls"
    runtime_statistics: str = "tribe:runtime-statistics"


SECTIONS = _TribeSectionIds()


def effective_level(
    section_id: str,
    panel_level: FoldLevel,
    overrides: Mapping[str, FoldLevel],
) -> FoldLevel:
    from ...models.fold_scale import effective_fold_level

    return effective_fold_level(
        overrides.get(section_id, panel_level),
        TRIBE_FOLD_SCALE,
    )


def append_fold_heading(
    text: Text,
    *,
    title: str,
    section_id: str,
    level: FoldLevel,
    count: int | None,
) -> None:
    append_major_section_divider(text)
    heading = Text()
    append_fold_glyph(heading, level)
    heading.append(title, style=SECTION_HEADING_STYLE)
    if count is not None:
        heading.append(f" · {count}", style=fold_count_style(title))
    append_section_heading(text, heading, section_id=section_id)


def append_more_tail(text: Text, total: int, shown: int) -> None:
    hidden = total - min(total, shown)
    if hidden > 0:
        text.append(f"  +{hidden} more\n", style="dim italic")
