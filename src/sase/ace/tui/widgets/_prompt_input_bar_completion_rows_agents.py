"""Agent and agent-group rows for the prompt input completion panel."""

from __future__ import annotations

from rich.text import Text

from sase.agent_family_plan_preview import (
    AgentFamilyPlanPreview,
    agent_family_plan_preview_accent,
    agent_family_plan_preview_label,
    agent_family_plan_structure_text,
)
from sase.ace.tui.agent_completion import (
    AgentCompletionCandidate,
    neutral_vcs_workflow,
    status_style,
)
from sase.ace.tui.models.tribe_display import (
    TRIBE_IDENTITY_FALLBACK_COLOR,
    compose_tribe_identity_style,
)
from sase.ace.tui.widgets._agent_list_styling import (
    _CLAN_NAME_STYLE,
    _FAMILY_NAME_STYLE,
)
from sase.ace.tui.widgets._prompt_input_bar_completion_rows_utils import (
    truncate_cell,
)
from sase.ace.tui.widgets.file_completion import CompletionCandidate


def is_agent_completion_candidate(candidate: CompletionCandidate) -> bool:
    return isinstance(candidate.metadata, AgentCompletionCandidate)


def append_agent_completion_row(
    content: Text,
    candidate: CompletionCandidate,
    is_selected: bool,
    *,
    tribe_colors: dict[str, str] | None = None,
    inner_width: int = 0,
) -> None:
    """Append one kind-aware wait/fork target row."""
    metadata = (
        candidate.metadata
        if isinstance(candidate.metadata, AgentCompletionCandidate)
        else None
    )
    if metadata is None:
        content.append(candidate.display, style="bold" if is_selected else "")
        return

    if metadata.kind != "agent":
        _append_group_completion_row(
            content,
            metadata,
            is_selected,
            tribe_colors=tribe_colors,
            inner_width=inner_width,
        )
        return

    workflow = metadata.vcs_workflow or neutral_vcs_workflow()
    name = truncate_cell(metadata.name, 26)
    badge = truncate_cell(workflow.display, 14)
    snippet = truncate_cell(metadata.prompt_snippet or metadata.label, 64)

    content.append("● ", style=status_style(metadata.status))
    content.append(f"{name:<26}", style="bold")
    content.append("  ")
    content.append(f"{badge:<14}", style=workflow.style)
    if snippet:
        content.append("  ")
        content.append(snippet, style="dim")


def _append_group_completion_row(
    content: Text,
    metadata: AgentCompletionCandidate,
    is_selected: bool,
    *,
    tribe_colors: dict[str, str] | None = None,
    inner_width: int = 0,
) -> None:
    """Append one family, clan, or tribe using the shared row anatomy."""
    glyphs = {"family": "F", "clan": "C", "tribe": "@"}
    styles = {
        "family": _FAMILY_NAME_STYLE,
        "clan": _CLAN_NAME_STYLE,
    }
    if metadata.kind == "tribe":
        tribe_name = metadata.name.removeprefix("@")
        identity_style = compose_tribe_identity_style(
            (
                tribe_colors.get(tribe_name, TRIBE_IDENTITY_FALLBACK_COLOR)
                if tribe_colors is not None
                else TRIBE_IDENTITY_FALLBACK_COLOR
            ),
            bold=True,
        )
        badge_style = compose_tribe_identity_style(
            TRIBE_IDENTITY_FALLBACK_COLOR,
            bold=True,
        )
    else:
        identity_style = styles[metadata.kind]
        badge_style = identity_style
    name = truncate_cell(metadata.name, 26)
    count = metadata.member_count or 0
    if metadata.kind == "tribe" and metadata.agent_count is not None:
        carrier_counts = f"{metadata.agent_count}a"
        if metadata.clan_count:
            carrier_counts += f"/{metadata.clan_count}c"
        badge = truncate_cell(f"tribe · {carrier_counts}", 14)
    else:
        badge = truncate_cell(f"{metadata.kind} · {count}", 14)
    if metadata.kind == "family":
        preview = _family_preview(metadata, _family_preview_budget(inner_width))
    else:
        preview = Text(_member_preview(metadata.member_names, count), style="dim")

    content.append(f"{glyphs[metadata.kind]} ", style=identity_style)
    content.append(
        f"{name:<26}",
        style=(
            f"bold {identity_style}"
            if is_selected and not identity_style.startswith("bold ")
            else identity_style
        ),
    )
    content.append("  ")
    content.append(f"{badge:<14}", style=badge_style)
    content.append("  ")
    content.append(
        "● ", style=status_style(metadata.aggregate_status or metadata.status)
    )
    if preview:
        content.append_text(preview)


def _member_preview(member_names: tuple[str, ...], member_count: int) -> str:
    visible = member_names[:3]
    preview = ", ".join(visible)
    hidden = max(0, member_count - len(visible))
    if hidden:
        preview = f"{preview} +{hidden}" if preview else f"+{hidden}"
    return truncate_cell(preview, 58)


def _family_preview_budget(inner_width: int) -> int:
    if inner_width <= 0:
        return 58
    return max(24, inner_width - 50)


def _family_preview(
    metadata: AgentCompletionCandidate,
    budget: int,
) -> Text:
    preview = metadata.plan_preview
    if preview is None or preview.kind is None:
        return _truncated_preview_text(metadata.prompt_snippet, budget, style="dim")

    fallback = metadata.prompt_snippet
    title = preview.title or fallback
    if not title:
        return _family_preview_line(
            preview,
            structure=agent_family_plan_structure_text(preview, compact=True),
            title="",
            title_style="",
            budget=budget,
            truncate_title=False,
        )

    title_style = "" if preview.title else "dim"
    for structure in _structure_degradation(preview):
        line = _family_preview_line(
            preview,
            structure=structure,
            title=title,
            title_style=title_style,
            budget=budget,
            truncate_title=False,
        )
        if line.cell_len <= budget:
            return line

    return _family_preview_line(
        preview,
        structure="",
        title=title,
        title_style=title_style,
        budget=budget,
        truncate_title=True,
    )


def _structure_degradation(preview: AgentFamilyPlanPreview) -> tuple[str, ...]:
    variants: list[str] = []
    for value in (
        agent_family_plan_structure_text(preview, compact=False),
        _phase_count_structure(preview),
        agent_family_plan_structure_text(preview, compact=True),
        "",
    ):
        if value not in variants:
            variants.append(value)
    return tuple(variants)


def _phase_count_structure(preview: AgentFamilyPlanPreview) -> str:
    if preview.phase_count is None:
        return ""
    noun = "phase" if preview.phase_count == 1 else "phases"
    return f"{preview.phase_count} {noun}"


def _family_preview_line(
    preview: AgentFamilyPlanPreview,
    *,
    structure: str,
    title: str,
    title_style: str,
    budget: int,
    truncate_title: bool,
) -> Text:
    assert preview.kind is not None
    text = Text(no_wrap=True, overflow="ellipsis")
    label = agent_family_plan_preview_label(preview.kind)
    accent = agent_family_plan_preview_accent(preview.kind)
    text.append(label, style=f"bold {accent}")
    if structure:
        text.append(" · ", style="dim")
        text.append(structure, style="dim")
    if not title:
        return text

    text.append(" · ", style="dim")
    title_text = Text(title, style=title_style, no_wrap=True, overflow="ellipsis")
    if truncate_title:
        title_text.truncate(max(0, budget - text.cell_len), overflow="ellipsis")
    text.append_text(title_text)
    return text


def _truncated_preview_text(value: str, budget: int, *, style: str) -> Text:
    text = Text(value, style=style, no_wrap=True, overflow="ellipsis")
    if budget > 0:
        text.truncate(budget, overflow="ellipsis")
    return text
