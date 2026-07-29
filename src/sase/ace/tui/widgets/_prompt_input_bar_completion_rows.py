"""Rich row rendering helpers for the prompt input completion panel."""

from __future__ import annotations

from rich.text import Text

from sase.ace.tui.agent_completion import (
    AgentCompletionCandidate,
    neutral_vcs_workflow,
    status_style,
)
from sase.ace.tui.model_alias_styles import (
    MODEL_ALIAS_KIND_STYLES,
    alias_kind_label,
    alias_state_text,
    provider_model_text,
)
from sase.ace.tui.models.tribe_display import (
    TRIBE_IDENTITY_FALLBACK_COLOR,
    compose_tribe_identity_style,
)
from sase.ace.tui.widgets.directive_completion import (
    DirectiveArgCompletionMetadata,
    DirectiveCompletionMetadata,
    ModelCompletionMetadata,
)
from sase.ace.tui.widgets.artifact_ref_completion import (
    AtReferenceLoadingCompletionMetadata,
    ArtifactRefKindCompletionMetadata,
    ArtifactRefPayloadCompletionMetadata,
)
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.jinja_completion import JinjaCompletionMetadata
from sase.ace.tui.widgets.placeholder_completion import PlaceholderCompletionMetadata
from sase.ace.tui.widgets.vcs_repo_completion import VcsRepoCompletionPlaceholder
from sase.ace.tui.widgets.xprompt_arg_assist import (
    XPromptAssistEntry,
    append_input_hints,
)
from sase.ace.tui.widgets._agent_list_styling import (
    _CLAN_NAME_STYLE,
    _FAMILY_NAME_STYLE,
)
from sase.project_display_names import project_display_name_for
from sase.ace.tui.provider_styles import provider_name_style
from sase.workspace_provider import VcsNamespaceEntry, VcsRepoEntry
from sase.xprompt.vcs_project_completion import VcsProjectEntry

_PROMPT_PLACEHOLDER_BADGE = "<> "
_PROMPT_PLACEHOLDER_STYLE = "cyan"
_COMMON_PLACEHOLDER_BADGE = "◆  "
_COMMON_PLACEHOLDER_STYLE = "#D7AF5F"
_MODEL_NAME_CELL_MAX = 30
_MODEL_KIND_CELL = 7
_MODEL_TARGET_CELL_MAX = 34

_ARTIFACT_SOURCE_BADGES = {
    "document": ("[D] ", "bold #87D7FF"),
    "file": ("[F] ", "bold #D7AF5F"),
    "chat": ("[C] ", "bold #5FD7AF"),
    "commit": ("[G] ", "bold #AF87FF"),
    "bug": ("[B] ", "bold #FF875F"),
}


def vcs_project_label_width(candidate: CompletionCandidate) -> int:
    """Visible width for the badge + primary label in a VCS completion row."""
    entry = (
        candidate.metadata if isinstance(candidate.metadata, VcsProjectEntry) else None
    )
    if entry is None:
        return len(candidate.display)
    badge_width = 5 if entry.kind == "changespec" else 4
    return badge_width + len(entry.name)


def vcs_repo_label_width(candidate: CompletionCandidate) -> int:
    """Visible width for the primary label in a repo completion row."""
    entry = candidate.metadata if isinstance(candidate.metadata, VcsRepoEntry) else None
    if entry is None:
        return len(candidate.display)
    return len(entry.name)


def vcs_ref_label_width(candidate: CompletionCandidate) -> int:
    """Visible width for the badge + primary label in a VCS ref row."""
    metadata = candidate.metadata
    if isinstance(metadata, VcsProjectEntry):
        badge_width = 5 if metadata.kind == "changespec" else 4
        return badge_width + len(metadata.name)
    if isinstance(metadata, VcsNamespaceEntry):
        badge_width = len(f"[{metadata.kind_label.upper()}] ")
        return badge_width + len(metadata.name.rstrip("/") + "/")
    return len(candidate.display)


def is_agent_completion_candidate(candidate: CompletionCandidate) -> bool:
    return isinstance(candidate.metadata, AgentCompletionCandidate)


def model_completion_column_widths(
    visible: list[CompletionCandidate],
) -> tuple[int, int]:
    """Return capped name/target widths for visible ``%model`` rows."""
    names = [
        Text(candidate.display).cell_len
        for candidate in visible
        if isinstance(candidate.metadata, ModelCompletionMetadata)
    ]
    targets = [
        _model_completion_target_text(metadata).cell_len
        for candidate in visible
        if isinstance(
            (metadata := candidate.metadata),
            ModelCompletionMetadata,
        )
        and not _model_completion_is_degraded_alias(metadata)
    ]
    return (
        min(max(names, default=0), _MODEL_NAME_CELL_MAX),
        min(max(targets, default=0), _MODEL_TARGET_CELL_MAX),
    )


def append_xprompt_completion_row(
    content: Text,
    candidate: CompletionCandidate,
    is_selected: bool,
) -> None:
    """Append one xprompt completion row using assist metadata when present."""
    content.append(
        candidate.display,
        style="bold green" if is_selected else "green",
    )
    entry = (
        candidate.metadata
        if isinstance(candidate.metadata, XPromptAssistEntry)
        else None
    )
    if entry is None:
        return

    kind = "skill" if entry.is_skill else entry.kind
    content.append(f"  {kind}", style="dim")
    if entry.description:
        content.append(f"  {entry.description}", style="dim")
    append_input_hints(content, entry.inputs)


def append_directive_completion_row(
    content: Text,
    candidate: CompletionCandidate,
    is_selected: bool,
) -> None:
    """Append one prompt directive completion row."""
    content.append(
        candidate.display,
        style="bold magenta" if is_selected else "magenta",
    )
    metadata = (
        candidate.metadata
        if isinstance(candidate.metadata, DirectiveCompletionMetadata)
        else None
    )
    if metadata is None:
        return

    details: list[str] = []
    if metadata.argument_hint:
        details.append(metadata.argument_hint)
    if metadata.aliases:
        details.append("alias " + ", ".join(f"%{alias}" for alias in metadata.aliases))
    if metadata.description:
        details.append(metadata.description)
    if details:
        content.append(f"  {'  '.join(details)}", style="dim")


def append_artifact_ref_completion_row(
    content: Text,
    candidate: CompletionCandidate,
    is_selected: bool,
) -> None:
    """Append one kind or provider-specific artifact payload row."""
    metadata = candidate.metadata
    if isinstance(metadata, AtReferenceLoadingCompletionMetadata):
        content.append(candidate.display, style="dim")
        return
    if isinstance(metadata, ArtifactRefKindCompletionMetadata):
        content.append("@ ", style="bold #5FD7AF")
        content.append(
            metadata.kind,
            style="bold green" if is_selected else "green",
        )
        content.append(f"  {metadata.source_label}", style="dim")
        return
    if not isinstance(metadata, ArtifactRefPayloadCompletionMetadata):
        content.append(candidate.display, style="bold" if is_selected else "")
        return

    badge, badge_style = _ARTIFACT_SOURCE_BADGES[metadata.source]
    content.append(badge, style=badge_style)
    content.append(
        candidate.display,
        style="bold" if is_selected else "",
    )
    details = [
        value
        for value in (metadata.label, metadata.detail, metadata.age)
        if value and value != candidate.display
    ]
    if details:
        content.append(f"  {'  ·  '.join(details)}", style="dim")


def append_directive_arg_completion_row(
    content: Text,
    candidate: CompletionCandidate,
    is_selected: bool,
    tribe_colors: dict[str, str] | None = None,
    model_widths: tuple[int, int] | None = None,
) -> None:
    """Append one prompt directive argument completion row."""
    if is_agent_completion_candidate(candidate):
        append_agent_completion_row(
            content,
            candidate,
            is_selected,
            tribe_colors=tribe_colors,
        )
        return

    if isinstance(candidate.metadata, ModelCompletionMetadata):
        append_model_completion_row(
            content,
            candidate,
            is_selected,
            model_widths or model_completion_column_widths([candidate]),
        )
        return

    content.append(
        candidate.display,
        style="bold magenta" if is_selected else "magenta",
    )
    metadata = (
        candidate.metadata
        if isinstance(candidate.metadata, DirectiveArgCompletionMetadata)
        else None
    )
    if metadata is not None and metadata.description:
        content.append(f"  {metadata.description}", style="dim")


def append_model_completion_row(
    content: Text,
    candidate: CompletionCandidate,
    is_selected: bool,
    widths: tuple[int, int],
) -> None:
    """Append one model or alias in the shared four-column grid."""
    metadata = candidate.metadata
    if not isinstance(metadata, ModelCompletionMetadata):
        content.append(
            candidate.display, style="bold magenta" if is_selected else "magenta"
        )
        return
    if _model_completion_is_degraded_alias(metadata):
        content.append(
            candidate.display,
            style="bold magenta" if is_selected else "magenta",
        )
        if metadata.description:
            content.append(f"  {metadata.description}", style="dim")
        return

    name_width, target_width = widths
    if metadata.kind == "model":
        name_style = "bold magenta" if is_selected else "magenta"
        kind_label = "model"
        kind_style = "bold magenta"
        state = Text(metadata.short_alias, style="dim")
    else:
        kind_style = MODEL_ALIAS_KIND_STYLES.get(metadata.alias_kind, "bold magenta")
        name_style = _selected_style(kind_style, is_selected)
        kind_label = alias_kind_label(metadata.alias_kind)
        state = alias_state_text(
            metadata.provenance,
            metadata.reference,
            metadata.reference_effort,
            metadata.pool_available,
            metadata.pool_total,
        )

    name = Text(candidate.display, style=name_style)
    name.truncate(name_width, overflow="ellipsis", pad=True)
    content.append_text(name)
    content.append("  ")

    kind = Text(kind_label, style=kind_style)
    kind.truncate(_MODEL_KIND_CELL, overflow="ellipsis", pad=True)
    content.append_text(kind)
    content.append("  ")

    target = _model_completion_target_text(metadata)
    target.truncate(target_width, overflow="ellipsis", pad=True)
    content.append_text(target)
    if state:
        content.append("  ")
        content.append_text(state)


def _model_completion_target_text(metadata: ModelCompletionMetadata) -> Text:
    if metadata.kind == "model":
        return Text(
            metadata.provider_display or metadata.description,
            style=provider_name_style(metadata.provider),
        )
    return provider_model_text(
        metadata.target_provider,
        metadata.target_model,
        metadata.target_effort,
    )


def _model_completion_is_degraded_alias(
    metadata: ModelCompletionMetadata,
) -> bool:
    return metadata.kind != "model" and not (
        metadata.alias_kind and metadata.target_model and metadata.provenance
    )


def _selected_style(style: str, selected: bool) -> str:
    """Use a kind's color without bolding unselected alias names."""
    unselected = style.removeprefix("bold ")
    return style if selected else unselected


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
    name = _truncate_cell(metadata.name, 26)
    badge = _truncate_cell(workflow.display, 14)
    snippet = _truncate_cell(metadata.prompt_snippet or metadata.label, 64)

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
    name = _truncate_cell(metadata.name, 26)
    count = metadata.member_count or 0
    if metadata.kind == "tribe" and metadata.agent_count is not None:
        carrier_counts = f"{metadata.agent_count}a"
        if metadata.clan_count:
            carrier_counts += f"/{metadata.clan_count}c"
        badge = _truncate_cell(f"tribe · {carrier_counts}", 14)
    else:
        badge = _truncate_cell(f"{metadata.kind} · {count}", 14)
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
    return _truncate_cell(preview, 58)


def append_vcs_project_completion_row(
    content: Text,
    candidate: CompletionCandidate,
    is_selected: bool,
    label_width: int = 0,
) -> None:
    """Append one ``+`` project/PR completion row.

    Project and ChangeSpec rows use the same badges as the ProjectSelect modal.
    The empty-catalog placeholder (no :class:`VcsProjectEntry` metadata) renders
    as a single dim row.
    """
    entry = (
        candidate.metadata if isinstance(candidate.metadata, VcsProjectEntry) else None
    )
    if entry is None:
        content.append(candidate.display, style="dim italic")
        return

    if entry.kind == "changespec":
        badge = "[PR] "
        badge_style = "bold #00D7AF"
        name_style = "bold #00D7AF" if is_selected else "#00D7AF"
    else:
        badge = "[P] "
        badge_style = "bold #87D7FF"
        name_style = "bold #87D7FF" if is_selected else "#87D7FF"

    content.append(badge, style=badge_style)
    content.append(entry.name, style=name_style)
    padding = max(0, label_width - (len(badge) + len(entry.name)))
    if padding:
        content.append(" " * padding)

    content.append(f"  {entry.display_tag}", style="dim green")
    if entry.kind == "changespec":
        if entry.status:
            content.append(f"  {entry.status}", style="dim")
        if entry.project:
            content.append(
                f"  · {project_display_name_for(entry.project)}",
                style="dim",
            )
    else:
        content.append(f"  {entry.provider_display}", style="dim")
        if entry.description:
            content.append(f"  {entry.description}", style="dim")


def append_vcs_repo_completion_row(
    content: Text,
    candidate: CompletionCandidate,
    is_selected: bool,
    label_width: int = 0,
) -> None:
    """Append one repository completion row or placeholder state."""
    entry = candidate.metadata if isinstance(candidate.metadata, VcsRepoEntry) else None
    if entry is None:
        placeholder = (
            candidate.metadata
            if isinstance(candidate.metadata, VcsRepoCompletionPlaceholder)
            else None
        )
        style = "dim italic"
        if placeholder is not None and placeholder.kind == "error":
            style = "bold red" if is_selected else "red"
        content.append(candidate.display, style=style)
        return

    name_style = "bold #87D7FF" if is_selected else "#87D7FF"
    content.append(entry.name, style=name_style)
    padding = max(0, label_width - len(entry.name))
    if padding:
        content.append(" " * padding)

    badges: list[tuple[str, str]] = []
    if entry.visibility.casefold() == "private":
        badges.append(("[private]", "bold #D7AF5F"))
    if entry.is_fork:
        badges.append(("[fork]", "bold #00D7AF"))
    if entry.is_archived:
        badges.append(("[archived]", "bold #808080"))
    for label, style in badges:
        content.append("  ")
        content.append(label, style=style)

    if entry.description:
        content.append(f"  {_truncate_cell(entry.description, 72)}", style="dim")


def append_vcs_ref_completion_row(
    content: Text,
    candidate: CompletionCandidate,
    is_selected: bool,
    label_width: int = 0,
) -> None:
    """Append one VCS ref-root completion row or placeholder state."""
    metadata = candidate.metadata
    if isinstance(metadata, VcsProjectEntry):
        _append_vcs_ref_project_row(
            content,
            metadata,
            is_selected,
            label_width,
        )
        return
    if isinstance(metadata, VcsNamespaceEntry):
        _append_vcs_ref_namespace_row(
            content,
            metadata,
            is_selected,
            label_width,
        )
        return

    content.append(candidate.display, style="dim italic")


def append_jinja_completion_row(
    content: Text,
    candidate: CompletionCandidate,
    is_selected: bool,
) -> None:
    """Append one Jinja2 completion row."""
    metadata = (
        candidate.metadata
        if isinstance(candidate.metadata, JinjaCompletionMetadata)
        else None
    )
    kind = metadata.kind if metadata is not None else "jinja"
    style_by_kind = {
        "variable": "cyan",
        "keyword": "magenta",
        "filter": "green",
    }
    style = style_by_kind.get(kind, "white")
    if is_selected:
        style = f"bold {style}"
    content.append(candidate.display, style=style)
    content.append(f"  {kind}", style="dim")


def append_placeholder_completion_row(
    content: Text,
    candidate: CompletionCandidate,
    is_selected: bool,
) -> None:
    """Append one reusable placeholder row with a source-specific badge."""
    metadata = (
        candidate.metadata
        if isinstance(candidate.metadata, PlaceholderCompletionMetadata)
        else None
    )
    is_common = metadata is not None and metadata.source == "common"
    badge = _COMMON_PLACEHOLDER_BADGE if is_common else _PROMPT_PLACEHOLDER_BADGE
    label_style = _COMMON_PLACEHOLDER_STYLE if is_common else _PROMPT_PLACEHOLDER_STYLE
    badge_style = _COMMON_PLACEHOLDER_STYLE if is_common else "dim cyan"

    content.append(badge, style=badge_style)
    content.append(
        candidate.display,
        style=f"bold {label_style}" if is_selected else label_style,
    )


def append_prompt_word_completion_row(
    content: Text,
    candidate: CompletionCandidate,
    is_selected: bool,
) -> None:
    """Append one prompt-local word without a file-type icon."""
    content.append(candidate.display, style="bold" if is_selected else "")


def _append_vcs_ref_project_row(
    content: Text,
    entry: VcsProjectEntry,
    is_selected: bool,
    label_width: int,
) -> None:
    """Append one project or ChangeSpec row in a VCS ref-root menu."""
    if entry.kind == "changespec":
        badge = "[PR] "
        badge_style = "bold #00D7AF"
        name_style = "bold #00D7AF" if is_selected else "#00D7AF"
    else:
        badge = "[P] "
        badge_style = "bold #87D7FF"
        name_style = "bold #87D7FF" if is_selected else "#87D7FF"

    content.append(badge, style=badge_style)
    content.append(entry.name, style=name_style)
    padding = max(0, label_width - (len(badge) + len(entry.name)))
    if padding:
        content.append(" " * padding)

    if entry.kind == "changespec":
        if entry.status:
            content.append(f"  {entry.status}", style="dim")
        if entry.project:
            content.append(
                f"  · {project_display_name_for(entry.project)}",
                style="dim",
            )
        return

    content.append(f"  {entry.provider_display}", style="dim")
    if entry.description:
        content.append(f"  {entry.description}", style="dim")


def _append_vcs_ref_namespace_row(
    content: Text,
    entry: VcsNamespaceEntry,
    is_selected: bool,
    label_width: int,
) -> None:
    """Append one namespace row in a VCS ref-root menu."""
    badge = f"[{entry.kind_label.upper()}] "
    label = entry.name.rstrip("/") + "/"
    badge_style = "bold #FFAF5F"
    name_style = "bold #FFAF5F" if is_selected else "#FFAF5F"

    content.append(badge, style=badge_style)
    content.append(label, style=name_style)
    padding = max(0, label_width - (len(badge) + len(label)))
    if padding:
        content.append(" " * padding)
    if entry.description:
        content.append(f"  {entry.description}", style="dim")


def _truncate_cell(value: str, width: int) -> str:
    if len(value) <= width:
        return value
    if width <= 3:
        return value[:width]
    return value[: width - 3].rstrip() + "..."
