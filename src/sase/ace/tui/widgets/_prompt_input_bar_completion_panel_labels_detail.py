"""Selected-row detail subtitles for the prompt completion panel."""

from __future__ import annotations

from rich.cells import cell_len
from rich.text import Text

from sase.ace.tui._agent_completion_models import AgentCompletionCandidate
from sase.ace.tui.widgets.directive_completion import (
    FinalizerCompletionMetadata,
    ModelCompletionMetadata,
)
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.jinja_completion import JinjaCompletionMetadata
from sase.ace.tui.widgets.macro_arg_assist import MacroArgNameMetadata


def jinja_completion_subtitle(
    rows: list[CompletionCandidate],
    selected_index: int,
    inner_width: int,
) -> Text:
    """Return the selected Jinja2 row's summary and details as a subtitle."""
    if not 0 <= selected_index < len(rows):
        return Text()
    metadata = rows[selected_index].metadata
    if not isinstance(metadata, JinjaCompletionMetadata):
        return Text()
    parts: list[str] = []
    if metadata.summary:
        parts.append(metadata.summary)
    if metadata.source == "input":
        if metadata.required:
            parts.append("required")
        elif metadata.default_display:
            parts.append(f"Default: {metadata.default_display}")
        if metadata.choices:
            parts.append(f"Choices: {', '.join(metadata.choices)}")
    if metadata.availability == "conditional" and metadata.hint:
        parts.append(f"⚠ {metadata.hint}")
    if metadata.legacy_for:
        parts.append(f"legacy → {metadata.legacy_for}")
    if metadata.closes:
        parts.append(f"Closes {{% {metadata.closes} %}}")
    subtitle = " · ".join(part for part in parts if part)
    text = Text(subtitle, no_wrap=True, overflow="ellipsis")
    if inner_width <= 0:
        return text
    text.truncate(inner_width, overflow="ellipsis")
    return text


def finalizer_completion_subtitle(
    rows: list[CompletionCandidate],
    selected_index: int,
    inner_width: int,
) -> Text:
    """Return the selected ``%final`` row's documentation as a subtitle."""
    if not 0 <= selected_index < len(rows):
        return Text()
    metadata = rows[selected_index].metadata
    if not isinstance(metadata, FinalizerCompletionMetadata):
        return Text()
    subtitle = metadata.documentation.replace("\n\n", " · ").replace("\n", " ")
    text = Text(subtitle, no_wrap=True, overflow="ellipsis")
    if inner_width <= 0:
        return text
    text.truncate(inner_width, overflow="ellipsis")
    return text


def macro_arg_name_completion_subtitle(
    rows: list[CompletionCandidate],
    selected_index: int,
    inner_width: int,
) -> Text:
    """Return the selected macro input description as a subtitle."""
    if not 0 <= selected_index < len(rows):
        return Text()
    metadata = rows[selected_index].metadata
    if not isinstance(metadata, MacroArgNameMetadata):
        return Text()
    description = metadata.input_hint.description or ""
    text = Text(description, no_wrap=True, overflow="ellipsis")
    if inner_width <= 0:
        return text
    text.truncate(inner_width, overflow="ellipsis")
    return text


def model_completion_subtitle(
    rows: list[CompletionCandidate],
    selected_index: int,
    inner_width: int,
    *,
    alias_shortcut: bool = False,
    explicit_shortcut: bool = False,
) -> Text:
    """Return the contextual subtitle for an enriched model menu."""
    if not 0 <= selected_index < len(rows):
        return Text()
    metadata = rows[selected_index].metadata
    if not isinstance(metadata, ModelCompletionMetadata):
        return Text()
    if alias_shortcut:
        return _model_alias_completion_subtitle(metadata, inner_width)
    if explicit_shortcut:
        return _model_explicit_completion_subtitle(metadata, inner_width)
    elif metadata.kind == "model":
        subtitle = "[@] model aliases"
    elif metadata.kind == "provider":
        label = metadata.provider_display or metadata.description or metadata.provider
        subtitle = f"[Ctrl+F] show {label} models"
    elif metadata.description:
        subtitle = metadata.description
    elif metadata.alias_kind == "user":
        alias = metadata.value.lstrip("@")
        subtitle = f"set llm_provider.model_aliases.custom.{alias}.description"
    else:
        subtitle = ""
    text = Text(subtitle, no_wrap=True, overflow="ellipsis")
    if inner_width <= 0:
        return text
    text.truncate(inner_width, overflow="ellipsis")
    return text


def _model_alias_completion_subtitle(
    metadata: ModelCompletionMetadata,
    inner_width: int,
) -> Text:
    preview = Text(f"Ctrl+F → %m:{metadata.value}", no_wrap=True, overflow="ellipsis")
    if inner_width <= 0:
        if metadata.description:
            preview.append(f" · {metadata.description}")
        return preview
    if preview.cell_len >= inner_width:
        preview.truncate(inner_width, overflow="ellipsis")
        return preview
    if not metadata.description:
        return preview

    separator = " · "
    remaining = inner_width - preview.cell_len
    separator_width = cell_len(separator)
    if remaining <= separator_width:
        return preview

    description = Text(metadata.description, no_wrap=True, overflow="ellipsis")
    description.truncate(remaining - separator_width, overflow="ellipsis")
    preview.append(separator)
    preview.append_text(description)
    return preview


def _model_explicit_completion_subtitle(
    metadata: ModelCompletionMetadata,
    inner_width: int,
) -> Text:
    preview = Text(f"Ctrl+F → %m:{metadata.value}", no_wrap=True, overflow="ellipsis")
    details = _model_explicit_completion_details(metadata)
    if inner_width <= 0:
        if details:
            preview.append(f" · {details}")
        return preview
    if preview.cell_len >= inner_width:
        preview.truncate(inner_width, overflow="ellipsis")
        return preview
    if not details:
        return preview

    separator = " · "
    remaining = inner_width - preview.cell_len
    separator_width = cell_len(separator)
    if remaining <= separator_width:
        return preview

    detail_text = Text(details, no_wrap=True, overflow="ellipsis")
    detail_text.truncate(remaining - separator_width, overflow="ellipsis")
    preview.append(separator)
    preview.append_text(detail_text)
    return preview


def _model_explicit_completion_details(metadata: ModelCompletionMetadata) -> str:
    provider = metadata.provider_display or metadata.provider
    details: list[str] = []
    if metadata.short_alias:
        provider = (
            f"{provider} ({metadata.short_alias})" if provider else metadata.short_alias
        )
    if provider:
        details.append(provider)
    if metadata.advisory_label:
        from sase.llm_provider.registry import model_advisory_marker

        details.append(
            f"{model_advisory_marker(metadata.advisory_severity)} "
            f"{metadata.advisory_label}"
        )
    if metadata.provenance in {"priority", "backup", "soft"}:
        details.append(metadata.provenance)
    return " · ".join(details)


def agent_completion_subtitle(
    rows: list[CompletionCandidate],
    selected_index: int,
    inner_width: int,
) -> Text:
    """Return contextual detail for a selected session completion candidate."""
    if not 0 <= selected_index < len(rows):
        return Text()
    metadata = rows[selected_index].metadata
    if not isinstance(metadata, AgentCompletionCandidate) or metadata.kind != "session":
        return Text()

    preview = metadata.plan_preview
    if preview is None or preview.kind is None:
        subtitle = _agent_session_members_subtitle(metadata)
    elif preview.kind == "epic":
        subtitle = _epic_phase_subtitle(metadata)
    elif preview.kind in {"tale", "plan"}:
        subtitle = Text(preview.goal or "", no_wrap=True, overflow="ellipsis")
    else:
        subtitle = Text(
            preview.parent_title or preview.description or "",
            no_wrap=True,
            overflow="ellipsis",
        )

    if inner_width > 0:
        subtitle.truncate(inner_width, overflow="ellipsis")
    return subtitle


def _epic_phase_subtitle(metadata: AgentCompletionCandidate) -> Text:
    preview = metadata.plan_preview
    if preview is None or preview.kind != "epic":
        return Text()
    phase_text = _limited_join(
        preview.phase_titles,
        preview.phase_count or len(preview.phase_titles),
        separator=" · ",
    )
    if not phase_text:
        return Text(preview.goal or "", no_wrap=True, overflow="ellipsis")
    text = Text(no_wrap=True, overflow="ellipsis")
    text.append("◆ ", style="bold #AF87FF")
    text.append(phase_text)
    return text


def _agent_session_members_subtitle(metadata: AgentCompletionCandidate) -> Text:
    member_count = metadata.member_count or len(metadata.member_names)
    return Text(
        _limited_join(metadata.member_names, member_count, separator=", "),
        no_wrap=True,
        overflow="ellipsis",
    )


def _limited_join(
    values: tuple[str, ...],
    total: int,
    *,
    separator: str,
) -> str:
    visible = values[:3]
    text = separator.join(visible)
    hidden = max(0, total - len(visible))
    if hidden:
        text = f"{text} +{hidden}" if text else f"+{hidden}"
    return text
