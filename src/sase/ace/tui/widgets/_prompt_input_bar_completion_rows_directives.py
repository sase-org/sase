"""Directive and model rows for the prompt input completion panel."""

from __future__ import annotations

from rich.text import Text

from sase.ace.tui.model_alias_styles import (
    MODEL_ALIAS_KIND_STYLES,
    alias_kind_label,
    alias_state_text,
    provider_model_text,
)
from sase.ace.tui.provider_styles import provider_name_style
from sase.ace.tui.widgets._prompt_input_bar_completion_rows_agents import (
    append_agent_completion_row,
    is_agent_completion_candidate,
)
from sase.ace.tui.widgets.directive_completion import (
    DirectiveArgCompletionMetadata,
    DirectiveCompletionMetadata,
    ModelCompletionMetadata,
)
from sase.ace.tui.widgets.file_completion import CompletionCandidate

_MODEL_NAME_CELL_MAX = 30
_MODEL_KIND_CELL = 7
_MODEL_TARGET_CELL_MAX = 34


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
