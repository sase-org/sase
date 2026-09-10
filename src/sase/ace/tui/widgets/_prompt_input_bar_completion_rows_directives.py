"""Directive and model rows for the prompt input completion panel."""

from __future__ import annotations

from rich.cells import cell_len
from rich.text import Text

from sase.ace.tui.model_alias_styles import (
    MODEL_ALIAS_KIND_STYLES,
    alias_kind_label,
    alias_state_text,
    model_advisory_text,
    provider_model_text,
)
from sase.ace.tui.provider_styles import provider_name_style
from sase.ace.tui.widgets._prompt_input_bar_completion_rows_agents import (
    append_agent_completion_row,
    is_agent_completion_candidate,
)
from sase.ace.tui.widgets.directive_completion import (
    BeadCompletionMetadata,
    DirectiveArgCompletionMetadata,
    DirectiveCatalogPlaceholder,
    DirectiveCompletionMetadata,
    FinalizerCompletionMetadata,
    MachineCompletionMetadata,
    ModelCompletionMetadata,
)
from sase.ace.tui.widgets._completion_match_highlight import append_highlighted
from sase.bead_status_presentation import bead_status_presentation
from sase.ace.tui.widgets.file_completion import CompletionCandidate

_MODEL_NAME_CELL_MAX = 30
_MODEL_KIND_CELL = 7
_MODEL_TARGET_CELL_MAX = 34
_FINALIZER_SELECTOR_CELL_MAX = 24
_FINALIZER_STATE_CELL = 8
_FINALIZER_PROVIDER_CELL_MAX = 28
_FINALIZER_STATE_STYLES = {
    "required": "bold cyan",
    "default": "cyan",
    "optional": "dim",
    "remove": "bold",
    "clear": "bold #D7AF5F",
}
_MODEL_PRIORITY_STYLE = "bold #87D7FF"
_MODEL_BACKUP_STYLE = "#87AFC7"
_MODEL_SOFT_STYLE = "bold #FFD75F"


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
    finalizer_widths: tuple[int, int] | None = None,
    inner_width: int = 0,
) -> None:
    """Append one prompt directive argument completion row."""
    if is_agent_completion_candidate(candidate):
        append_agent_completion_row(
            content,
            candidate,
            is_selected,
            tribe_colors=tribe_colors,
            inner_width=inner_width,
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

    if isinstance(candidate.metadata, DirectiveCatalogPlaceholder):
        content.append(candidate.display, style="dim")
        return

    if isinstance(candidate.metadata, FinalizerCompletionMetadata):
        append_finalizer_completion_row(
            content,
            candidate,
            is_selected,
            finalizer_widths or finalizer_completion_column_widths([candidate]),
        )
        return

    if isinstance(candidate.metadata, MachineCompletionMetadata):
        style = "bold magenta" if is_selected else "magenta"
        content.append(candidate.display, style=style)
        details = [
            value
            for value in (
                candidate.metadata.status,
                candidate.metadata.provider_ref,
                candidate.metadata.installation_id,
            )
            if value
        ]
        if details:
            content.append(f"  {'  '.join(details)}", style="dim")
        return

    if isinstance(candidate.metadata, BeadCompletionMetadata):
        _append_bead_completion_row(content, candidate.metadata, is_selected)
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
    *,
    match_query: str = "",
    available_width: int = 0,
) -> None:
    """Append one model or alias in the shared four-column grid."""
    metadata = candidate.metadata
    if not isinstance(metadata, ModelCompletionMetadata):
        content.append(
            candidate.display, style="bold magenta" if is_selected else "magenta"
        )
        return
    if metadata.kind == "provider":
        _append_provider_completion_row(
            content, candidate, metadata, is_selected, widths
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

    if (match_query or available_width > 0) and metadata.kind in {
        "implicit_alias",
        "user_alias",
    }:
        _append_model_alias_shortcut_row(
            content,
            candidate,
            metadata,
            is_selected,
            widths,
            match_query=match_query,
            available_width=available_width,
        )
        return

    name_width, target_width = widths
    if metadata.kind == "model":
        name_style = "bold magenta" if is_selected else "magenta"
        kind_label = "model"
        kind_style = "bold magenta"
        state = Text(metadata.short_alias, style="dim")
        _append_model_advisory_state(state, metadata)
        _append_model_routing_state(state, metadata)
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


def append_model_shortcut_completion_row(
    content: Text,
    candidate: CompletionCandidate,
    is_selected: bool,
    widths: tuple[int, int],
    *,
    match_query: str,
    available_width: int,
) -> None:
    """Append a compact ``==model`` row with the typed prefix highlighted."""
    metadata = candidate.metadata
    if not isinstance(metadata, ModelCompletionMetadata) or metadata.kind != "model":
        content.append(candidate.display, style="dim")
        return

    name_width, provider_width = widths
    name_style = "bold magenta" if is_selected else "magenta"
    provider = _model_completion_target_text(metadata)
    provider.truncate(provider_width, overflow="ellipsis", pad=True)
    hint = _model_shortcut_hint_text(metadata, match_query)
    advisory = model_advisory_text(
        metadata.advisory_label,
        metadata.advisory_severity,
    )
    state = _model_routing_state_text(metadata)
    pieces: list[Text] = [provider]
    if hint:
        pieces.append(hint)
    if advisory:
        pieces.append(advisory)
    if state:
        pieces.append(state)

    if available_width > 0:
        detail_width = _model_shortcut_detail_width(pieces)
        while pieces and name_width + detail_width > available_width:
            pieces.pop()
            detail_width = _model_shortcut_detail_width(pieces)
        name_width = max(1, min(name_width, available_width - detail_width))

    name = _model_shortcut_name_text(
        candidate.display,
        name_style,
        metadata=metadata,
        match_query=match_query,
    )
    name.truncate(name_width, overflow="ellipsis", pad=True)
    content.append_text(name)
    for piece in pieces:
        content.append("  ")
        content.append_text(piece)


def _model_shortcut_detail_width(pieces: list[Text]) -> int:
    """Return the cell width consumed by explicit-model detail columns."""
    return sum(2 + piece.cell_len for piece in pieces)


def _model_shortcut_name_text(
    display: str,
    style: str,
    *,
    metadata: ModelCompletionMetadata,
    match_query: str,
) -> Text:
    """Return a model label with the typed canonical prefix highlighted."""
    head, separator, scoped_query = match_query.partition("/")
    if separator and head:
        scoped_prefix = f"{head}/"
        if display.casefold().startswith(scoped_prefix.casefold()):
            ranges = [(0, len(head))]
            tail_start = len(scoped_prefix)
            tail = display[tail_start:]
            hint_matched = bool(
                scoped_query
                and metadata.short_alias.casefold().startswith(scoped_query.casefold())
            )
            if (
                scoped_query
                and not hint_matched
                and tail.casefold().startswith(scoped_query.casefold())
            ):
                ranges.append((tail_start, tail_start + len(scoped_query)))
            text = Text(no_wrap=True, overflow="ellipsis")
            append_highlighted(text, display, ranges, base_style=style)
            return text

    if not match_query or not display.casefold().startswith(match_query.casefold()):
        return Text(display, style=style)
    text = Text(no_wrap=True, overflow="ellipsis")
    append_highlighted(
        text,
        display,
        [(0, len(match_query))],
        base_style=style,
    )
    return text


def _model_shortcut_hint_text(
    metadata: ModelCompletionMetadata,
    match_query: str,
) -> Text:
    """Return the short-name hint, highlighting only when the hint matched."""
    if not metadata.short_alias:
        return Text("")
    style = "dim"
    query = match_query
    _provider, separator, scoped_query = match_query.partition("/")
    if separator:
        query = scoped_query
    if query and metadata.short_alias.casefold().startswith(query.casefold()):
        text = Text(no_wrap=True, overflow="ellipsis")
        append_highlighted(
            text,
            metadata.short_alias,
            [(0, len(query))],
            base_style=style,
        )
        return text
    return Text(metadata.short_alias, style=style)


def _append_model_alias_shortcut_row(
    content: Text,
    candidate: CompletionCandidate,
    metadata: ModelCompletionMetadata,
    is_selected: bool,
    widths: tuple[int, int],
    *,
    match_query: str,
    available_width: int,
) -> None:
    """Append a width-aware ``=alias`` row with the typed prefix highlighted."""
    name_width, target_width = widths
    kind_style = MODEL_ALIAS_KIND_STYLES.get(metadata.alias_kind, "bold magenta")
    name_style = _selected_style(kind_style, is_selected)
    kind_label = alias_kind_label(metadata.alias_kind)
    target = _model_completion_target_text(metadata)
    target.truncate(target_width, overflow="ellipsis", pad=True)
    state = alias_state_text(
        metadata.provenance,
        metadata.reference,
        metadata.reference_effort,
        metadata.pool_available,
        metadata.pool_total,
    )

    kind = Text(kind_label, style=kind_style)
    kind.truncate(_MODEL_KIND_CELL, overflow="ellipsis", pad=True)
    pieces = [
        ("kind", kind),
        ("target", target),
    ]
    if state:
        pieces.append(("state", state))

    if available_width > 0:
        detail_width = _model_alias_detail_width(pieces)
        if name_width + detail_width > available_width:
            detail_width = _model_alias_detail_width(pieces[:1])
            if name_width + detail_width > available_width:
                pieces = []
                detail_width = 0
            else:
                pieces = pieces[:1]
        name_width = max(1, min(name_width, available_width - detail_width))

    name = _model_alias_name_text(
        candidate.display,
        name_style,
        match_query=match_query,
    )
    name.truncate(name_width, overflow="ellipsis", pad=True)
    content.append_text(name)
    for _kind, piece in pieces:
        content.append("  ")
        content.append_text(piece)


def _model_alias_detail_width(pieces: list[tuple[str, Text]]) -> int:
    """Return the cell width consumed by model-alias detail columns."""
    return sum(2 + piece.cell_len for _kind, piece in pieces)


def _model_alias_name_text(
    display: str,
    style: str,
    *,
    match_query: str,
) -> Text:
    """Return an alias label with the typed post-``@`` prefix highlighted."""
    query = match_query.lstrip("@")
    label_start = 1 if display.startswith("@") else 0
    label = display[label_start:]
    if not query or not label.casefold().startswith(query.casefold()):
        return Text(display, style=style)

    text = Text(no_wrap=True, overflow="ellipsis")
    if label_start:
        text.append(display[:label_start], style=style)
    append_highlighted(
        text,
        label,
        [(0, len(query))],
        base_style=style,
    )
    return text


def _append_provider_completion_row(
    content: Text,
    candidate: CompletionCandidate,
    metadata: ModelCompletionMetadata,
    is_selected: bool,
    widths: tuple[int, int],
) -> None:
    name_width, target_width = widths
    provider_style = provider_name_style(metadata.provider)
    name = Text(
        candidate.display,
        style=provider_style if is_selected else provider_style.removeprefix("bold "),
    )
    name.truncate(name_width, overflow="ellipsis", pad=True)
    content.append_text(name)
    content.append("  ")

    kind = Text("models", style="bold magenta")
    kind.truncate(_MODEL_KIND_CELL, overflow="ellipsis", pad=True)
    content.append_text(kind)
    content.append("  ")

    target = _model_completion_target_text(metadata)
    target.truncate(target_width, overflow="ellipsis", pad=True)
    content.append_text(target)
    route_state = _model_routing_state_text(metadata)
    if route_state:
        content.append("  ")
        content.append_text(route_state)


def _model_completion_target_text(metadata: ModelCompletionMetadata) -> Text:
    if metadata.kind == "provider":
        label = metadata.provider_display or metadata.description or metadata.provider
        if metadata.provider_model_count:
            noun = "model" if metadata.provider_model_count == 1 else "models"
            label = f"{label} ({metadata.provider_model_count} {noun})"
        return Text(label, style=provider_name_style(metadata.provider))
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


def _append_model_routing_state(text: Text, metadata: ModelCompletionMetadata) -> None:
    """Append routing provenance to an existing completion state cell."""
    state = _model_routing_state_text(metadata)
    if not state:
        return
    if text:
        text.append(" · ", style="dim")
    text.append_text(state)


def _append_model_advisory_state(text: Text, metadata: ModelCompletionMetadata) -> None:
    """Append an advisory chip to the model state cell."""
    advisory = model_advisory_text(
        metadata.advisory_label,
        metadata.advisory_severity,
    )
    if not advisory:
        return
    if text:
        text.append(" · ", style="dim")
    text.append_text(advisory)


def _model_routing_state_text(metadata: ModelCompletionMetadata) -> Text:
    """Return the provider-routing state tag for a model completion row."""
    if metadata.provenance == "priority":
        return Text("priority", style=_MODEL_PRIORITY_STYLE)
    if metadata.provenance == "backup":
        return Text("backup", style=_MODEL_BACKUP_STYLE)
    if metadata.provenance == "soft":
        return Text("soft", style=_MODEL_SOFT_STYLE)
    return Text("")


def _model_completion_is_degraded_alias(
    metadata: ModelCompletionMetadata,
) -> bool:
    return metadata.kind not in {"model", "provider"} and not (
        metadata.alias_kind and metadata.target_model and metadata.provenance
    )


def _selected_style(style: str, selected: bool) -> str:
    """Use a kind's color without bolding unselected alias names."""
    unselected = style.removeprefix("bold ")
    return style if selected else unselected


def finalizer_completion_column_widths(
    visible: list[CompletionCandidate],
) -> tuple[int, int]:
    """Return capped selector/provider widths for visible ``%final`` rows."""
    selectors = [
        Text(candidate.display).cell_len
        for candidate in visible
        if isinstance(candidate.metadata, FinalizerCompletionMetadata)
    ]
    providers = [
        Text(metadata.provider).cell_len
        for candidate in visible
        if isinstance(
            (metadata := candidate.metadata),
            FinalizerCompletionMetadata,
        )
        and metadata.provider
    ]
    return (
        min(max(selectors, default=0), _FINALIZER_SELECTOR_CELL_MAX),
        min(max(providers, default=0), _FINALIZER_PROVIDER_CELL_MAX),
    )


def append_finalizer_completion_row(
    content: Text,
    candidate: CompletionCandidate,
    is_selected: bool,
    widths: tuple[int, int],
) -> None:
    """Append one aligned ``%final`` selector, policy state, and provider."""
    metadata = candidate.metadata
    if not isinstance(metadata, FinalizerCompletionMetadata):
        content.append(
            candidate.display,
            style="bold magenta" if is_selected else "magenta",
        )
        return

    selector_width, provider_width = widths
    state_label = metadata.state_label
    name_style = _finalizer_selector_style(metadata, is_selected)
    name = Text(candidate.display or metadata.value, style=name_style)
    if selector_width:
        name.truncate(selector_width, overflow="ellipsis", pad=True)
    content.append_text(name)
    content.append("  ")

    state = Text(
        state_label,
        style=_FINALIZER_STATE_STYLES.get(state_label, "dim"),
    )
    state.truncate(_FINALIZER_STATE_CELL, overflow="ellipsis", pad=True)
    content.append_text(state)

    if metadata.provider and provider_width:
        content.append("  ")
        provider = Text(metadata.provider, style="dim")
        provider.truncate(provider_width, overflow="ellipsis", pad=True)
        content.append_text(provider)


def _finalizer_selector_style(
    metadata: FinalizerCompletionMetadata,
    is_selected: bool,
) -> str:
    if metadata.kind == "finalizer_remove":
        return "bold magenta strike" if is_selected else "magenta strike"
    if metadata.kind == "finalizer_clear":
        return "bold #D7AF5F" if is_selected else "#D7AF5F"
    return "bold magenta" if is_selected else "magenta"


def _append_bead_completion_row(
    content: Text,
    metadata: BeadCompletionMetadata,
    is_selected: bool,
) -> None:
    presentation = bead_status_presentation(metadata.status)
    content.append(f"{presentation.tui_glyph} ", style=presentation.rich_style)
    content.append(
        metadata.bead_id,
        style="bold magenta" if is_selected else "magenta",
    )
    details: list[str] = []
    if metadata.title:
        details.append(metadata.title)
    status_label = presentation.label
    type_label = metadata.task_type or metadata.type_label
    extras = " · ".join(part for part in (status_label, type_label) if part)
    if extras:
        details.append(extras)
    if details:
        content.append(f"  {'  '.join(details)}", style="dim")
