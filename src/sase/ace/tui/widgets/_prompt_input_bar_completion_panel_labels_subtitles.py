"""Menu-context border subtitles for the prompt completion panel."""

from __future__ import annotations

from rich.cells import cell_len
from rich.text import Text

from sase.ace.tui.widgets._prompt_context_ranking import has_context_promotion
from sase.ace.tui.widgets._prompt_input_bar_completion_panel_labels_shared import (
    SYNC_TITLE_STATUS,
)
from sase.ace.tui.widgets._ranking_signal_rows import ranking_signal_legend
from sase.ace.tui.widgets.artifact_ref_completion import (
    AtReferenceFileCompletionMetadata,
    ArtifactRefKindCompletionMetadata,
    ArtifactRefPayloadCompletionMetadata,
    ArtifactRefSyncCompletionMetadata,
)
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.history_word_completion import (
    HISTORY_WORD_COMPLETION_KIND,
    HistoryWordCompletionMetadata,
    HistoryWordCompletionPlaceholder,
)
from sase.ace.tui.widgets.next_word_menu import NEXT_WORD_COMPLETION_KIND
from sase.ace.tui.widgets.prompt_word_completion import PROMPT_WORD_COMPLETION_KIND
from sase.ace.tui.widgets.placeholder_completion import (
    PLACEHOLDER_COMPLETION_KIND,
    PlaceholderCompletionMetadata,
    PlaceholderRankingMetadata,
)

_PLACEHOLDER_SOURCE_LEGEND = "<> prompt   ◆ saved"


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
    text.append(SYNC_TITLE_STATUS.get(metadata.phase, metadata.phase), style="dim")
    if metadata.detail:
        text.append(f" · {metadata.detail}", style="dim")
    return text


def history_word_completion_subtitle(
    visible: list[CompletionCandidate],
    inner_width: int,
) -> Text | str:
    """Return the signal-color legend for a smart-ranked history-word menu.

    Falls back to the plain ``[^T] accept  [^D] delete`` hint when the panel
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

    legend = ranking_signal_legend(with_context=has_context_promotion(visible))
    legend.append("   ", style="dim")
    legend.append(plain_hint, style="dim")

    if inner_width > 0 and legend.cell_len > inner_width:
        return plain_hint
    return legend


def prompt_word_completion_subtitle(
    visible: list[CompletionCandidate],
    inner_width: int,
) -> Text | str:
    """Return the prompt-word menu's border subtitle.

    Menus with a context-promoted row name the sequence signal in the
    legend; every other menu keeps exactly today's accept hint.
    """
    plain_hint = completion_delete_subtitle(PROMPT_WORD_COMPLETION_KIND, visible)
    if not has_context_promotion(visible):
        return plain_hint

    legend = ranking_signal_legend(with_context=True)
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
    if completion_kind == PROMPT_WORD_COMPLETION_KIND:
        return "[^T] accept"
    if completion_kind == HISTORY_WORD_COMPLETION_KIND:
        if visible and all(
            not isinstance(candidate.metadata, HistoryWordCompletionPlaceholder)
            for candidate in visible
        ):
            return "[^T] accept  [^D] delete"
        return ""
    if completion_kind == NEXT_WORD_COMPLETION_KIND:
        return "[^T] accept  [^D] delete"
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
