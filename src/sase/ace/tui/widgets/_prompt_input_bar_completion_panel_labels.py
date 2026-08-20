"""Border title and subtitle text for the prompt completion panel."""

from __future__ import annotations

from rich.cells import cell_len
from rich.text import Text

from sase.ace.tui._agent_completion_models import AgentCompletionCandidate
from sase.ace.tui.widgets._prompt_input_bar_completion_panel_kinds import (
    CompletionPanelKinds,
)
from sase.ace.tui.widgets._prompt_input_bar_completion_rows import (
    at_reference_directory_display,
)
from sase.ace.tui.widgets._ranking_signal_rows import ranking_signal_legend
from sase.ace.tui.widgets.artifact_ref_completion import (
    AtReferenceFileCompletionMetadata,
    AtReferenceLoadingCompletionMetadata,
    ArtifactRefKindCompletionMetadata,
    ArtifactRefPayloadCompletionMetadata,
    ArtifactRefSyncCompletionMetadata,
)
from sase.ace.tui.widgets.directive_completion import ModelCompletionMetadata
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.history_word_completion import (
    HISTORY_WORD_COMPLETION_KIND,
    HistoryWordCompletionMetadata,
    HistoryWordCompletionPlaceholder,
)
from sase.ace.tui.widgets.placeholder_completion import (
    PLACEHOLDER_COMPLETION_KIND,
    PlaceholderCompletionMetadata,
    PlaceholderRankingMetadata,
)

_PLACEHOLDER_SOURCE_LEGEND = "<> prompt   ◆ saved"
_SYNC_TITLE_STATUS = {
    "running": "syncing",
    "settled_ok": "synced",
    "settled_error": "sync failed",
}


def completion_panel_title(
    kinds: CompletionPanelKinds,
    token: str,
    rows: list[CompletionCandidate],
    group_directory: str,
) -> str:
    """Return the provider-specific title; path completion shows its directory."""
    if kinds.xprompt:
        return "xprompts"
    if kinds.directive:
        return "directives"
    if kinds.bead:
        return "beads"
    if kinds.directive_arg_agent:
        return "wait targets"
    if kinds.model:
        if scoped_title := _model_completion_provider_scope_title(token, rows):
            return scoped_title
        return "model aliases" if token.startswith("@") else "%model values"
    if kinds.directive_arg:
        return "directive values"
    if kinds.vcs_project:
        return "projects & PRs"
    if kinds.vcs_ref:
        return token
    if kinds.vcs_repo:
        return token
    if kinds.artifact_ref:
        return _at_reference_panel_title(token, rows, group_directory)
    if kinds.xprompt_arg_agent:
        return "fork targets"
    if kinds.kind == "xprompt_arg_name":
        return "xprompt arg names"
    if kinds.kind == "xprompt_arg_value":
        return "xprompt arg values"
    if kinds.kind == "xprompt_arg_path":
        return "xprompt path"
    if kinds.jinja:
        return "jinja"
    if kinds.placeholder:
        return "placeholder"
    if kinds.prompt_word:
        return "prompt words"
    if kinds.history_word:
        return "history words"
    if kinds.history:
        return "recent files"
    if "/" in token:
        return token[: token.rindex("/") + 1]
    return token


def _at_reference_panel_title(
    token: str,
    rows: list[CompletionCandidate],
    directory: str,
) -> str:
    """Return the adaptive title for an ``@`` Kind-stage menu."""
    sync_metadata = next(
        (
            candidate.metadata
            for candidate in rows
            if isinstance(candidate.metadata, ArtifactRefSyncCompletionMetadata)
        ),
        None,
    )
    if sync_metadata is not None:
        status = _SYNC_TITLE_STATUS.get(sync_metadata.phase, sync_metadata.phase)
        return f"@ {sync_metadata.kind} · {status}"
    has_artifacts = any(
        isinstance(candidate.metadata, ArtifactRefKindCompletionMetadata)
        for candidate in rows
    )
    has_files = any(
        isinstance(candidate.metadata, AtReferenceFileCompletionMetadata)
        for candidate in rows
    )
    is_loading = any(
        isinstance(candidate.metadata, AtReferenceLoadingCompletionMetadata)
        for candidate in rows
    )
    if has_artifacts and has_files:
        return "@ reference"
    if has_artifacts:
        return "@ artifact kinds"
    if has_files or is_loading:
        return f"@ {at_reference_directory_display(directory)}"
    return token


def model_completion_subtitle(
    rows: list[CompletionCandidate],
    selected_index: int,
    inner_width: int,
) -> Text:
    """Return the contextual subtitle for an enriched model menu."""
    if not 0 <= selected_index < len(rows):
        return Text()
    metadata = rows[selected_index].metadata
    if not isinstance(metadata, ModelCompletionMetadata):
        return Text()
    if metadata.kind == "model":
        subtitle = "[@] model aliases"
    elif metadata.kind == "provider":
        label = metadata.provider_display or metadata.description or metadata.provider
        subtitle = f"[Enter] show {label} models"
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


def agent_completion_subtitle(
    rows: list[CompletionCandidate],
    selected_index: int,
    inner_width: int,
) -> Text:
    """Return contextual detail for a selected family completion candidate."""
    if not 0 <= selected_index < len(rows):
        return Text()
    metadata = rows[selected_index].metadata
    if not isinstance(metadata, AgentCompletionCandidate) or metadata.kind != "family":
        return Text()

    preview = metadata.plan_preview
    if preview is None or preview.kind is None:
        subtitle = _family_members_subtitle(metadata)
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


def _family_members_subtitle(metadata: AgentCompletionCandidate) -> Text:
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


def _model_completion_provider_scope_title(
    token: str,
    rows: list[CompletionCandidate],
) -> str:
    head, separator, _remainder = token.partition("/")
    if not separator or not head:
        return ""
    scoped_prefix = f"{head.casefold()}/"
    for candidate in rows:
        metadata = candidate.metadata
        if (
            isinstance(metadata, ModelCompletionMetadata)
            and metadata.kind == "model"
            and metadata.provider.casefold() == head.casefold()
            and metadata.value.casefold().startswith(scoped_prefix)
        ):
            return f"{metadata.provider}/ models"
    return ""


def artifact_ref_completion_subtitle(
    visible: list[CompletionCandidate],
    payload_count: int,
    payload_total: int,
    truncated_payloads: int,
    inner_width: int,
    files_suppressed: bool = False,
) -> Text:
    """Return match-mode and catalog-coverage context for an ``@`` menu."""
    fuzzy = any(
        isinstance(
            candidate.metadata,
            (
                ArtifactRefKindCompletionMetadata,
                AtReferenceFileCompletionMetadata,
                ArtifactRefPayloadCompletionMetadata,
            ),
        )
        and candidate.metadata.match_tier >= 2
        for candidate in visible
    )
    subtitle = Text(no_wrap=True, overflow="ellipsis")
    if fuzzy:
        subtitle.append("~ fuzzy")
    if payload_total:
        if subtitle:
            subtitle.append(" · ")
        subtitle.append(f"{payload_count} of {payload_total}")
    if truncated_payloads:
        if subtitle:
            subtitle.append(" · ")
        subtitle.append(
            f"⚠ {truncated_payloads} not scanned",
            style="bold #FF8C00",
        )
    if files_suppressed:
        if subtitle:
            subtitle.append(" · ")
        subtitle.append("[^T] files", style="dim")

    sync_metadata = next(
        (
            candidate.metadata
            for candidate in visible
            if isinstance(candidate.metadata, ArtifactRefSyncCompletionMetadata)
        ),
        None,
    )
    if sync_metadata is not None:
        combined = _sync_subtitle_segment(sync_metadata)
        if subtitle:
            combined.append(" · ", style="dim")
            combined.append_text(subtitle)
        if inner_width <= 0 or combined.cell_len <= inner_width:
            return combined
        # Narrow panel: drop the sync segment first, keep the base subtitle.

    if inner_width > 0:
        subtitle.truncate(inner_width, overflow="ellipsis")
    return subtitle


def _sync_subtitle_segment(metadata: ArtifactRefSyncCompletionMetadata) -> Text:
    """Return the ``syncing``/``synced``/``sync failed`` subtitle segment."""
    text = Text(no_wrap=True, overflow="ellipsis")
    text.append(_SYNC_TITLE_STATUS.get(metadata.phase, metadata.phase), style="dim")
    if metadata.detail:
        text.append(f" · {metadata.detail}", style="dim")
    return text


def history_word_completion_subtitle(
    visible: list[CompletionCandidate],
    inner_width: int,
) -> Text | str:
    """Return the signal-color legend for a smart-ranked history-word menu.

    Falls back to the plain ``[^L] accept  [^D] delete`` hint when the panel
    is too narrow for the legend or no visible row carries ranking metadata
    (``recent`` ranking, the loading placeholder, or an empty menu).
    """
    plain_hint = completion_delete_subtitle(HISTORY_WORD_COMPLETION_KIND, visible)
    if not plain_hint:
        return plain_hint
    has_metadata = any(
        isinstance(candidate.metadata, HistoryWordCompletionMetadata)
        for candidate in visible
    )
    if not has_metadata:
        return plain_hint

    legend = ranking_signal_legend()
    legend.append("   ", style="dim")
    legend.append(plain_hint, style="dim")

    if inner_width > 0 and legend.cell_len > inner_width:
        return plain_hint
    return legend


def placeholder_completion_subtitle(
    visible: list[CompletionCandidate],
    inner_width: int,
) -> Text | str:
    """Return the placeholder panel's border subtitle, width-ladder ranked.

    Widest to narrowest: the source legend plus the ranking-signal legend
    plus the delete hint; the ranking-signal legend alone (the badges
    already appear in the rows, so the source legend is the first thing
    dropped) plus the delete hint; today's plain subtitle (the source
    legend, when both groups are visible, plus the delete hint) with no
    signal legend; and the delete hint alone. The source legend only
    appears when both groups are visible, and the signal legend only when
    some visible row carries ranking metadata.
    """
    delete_hint = "[^D] delete"
    has_source_legend = _visible_placeholder_sources(visible) == {"prompt", "common"}
    has_signal_legend = any(
        isinstance(candidate.metadata, PlaceholderCompletionMetadata)
        and isinstance(candidate.metadata.ranking, PlaceholderRankingMetadata)
        for candidate in visible
    )

    rungs: list[Text | str] = []
    if has_source_legend and has_signal_legend:
        combined = Text(_PLACEHOLDER_SOURCE_LEGEND, no_wrap=True)
        combined.append("  ")
        combined.append_text(ranking_signal_legend())
        combined.append("  ", style="dim")
        combined.append(delete_hint, style="dim")
        rungs.append(combined)
    if has_signal_legend:
        signal_only = ranking_signal_legend()
        signal_only.append("  ", style="dim")
        signal_only.append(delete_hint, style="dim")
        rungs.append(signal_only)
    rungs.append(completion_delete_subtitle(PLACEHOLDER_COMPLETION_KIND, visible))
    rungs.append(delete_hint)

    for rung in rungs:
        width = rung.cell_len if isinstance(rung, Text) else cell_len(rung)
        if inner_width <= 0 or width <= inner_width:
            return rung
    return delete_hint


def completion_delete_subtitle(
    completion_kind: str,
    visible: list[CompletionCandidate],
) -> str:
    """Return the delete affordance for durable completion providers."""
    delete_hint = "[^L] accept  [^D] delete"
    if completion_kind == "file_history":
        return delete_hint
    if completion_kind == HISTORY_WORD_COMPLETION_KIND:
        if visible and all(
            not isinstance(candidate.metadata, HistoryWordCompletionPlaceholder)
            for candidate in visible
        ):
            return delete_hint
        return ""
    if completion_kind == PLACEHOLDER_COMPLETION_KIND:
        legend = (
            _PLACEHOLDER_SOURCE_LEGEND
            if _visible_placeholder_sources(visible) == {"prompt", "common"}
            else ""
        )
        return f"{legend}  [^D] delete".strip()
    return ""


def _visible_placeholder_sources(
    visible: list[CompletionCandidate],
) -> set[str]:
    sources: set[str] = set()
    for candidate in visible:
        metadata = (
            candidate.metadata
            if isinstance(candidate.metadata, PlaceholderCompletionMetadata)
            else None
        )
        sources.add(
            "common"
            if metadata is not None and metadata.source == "common"
            else "prompt"
        )
    return sources
