"""Agent and agent-group rows for the prompt input completion panel."""

from __future__ import annotations

from rich.text import Text

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
    preview = _member_preview(metadata.member_names, count)

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
        content.append(preview, style="dim")


def _member_preview(member_names: tuple[str, ...], member_count: int) -> str:
    visible = member_names[:3]
    preview = ", ".join(visible)
    hidden = max(0, member_count - len(visible))
    if hidden:
        preview = f"{preview} +{hidden}" if preview else f"+{hidden}"
    return truncate_cell(preview, 58)
