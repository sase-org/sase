"""Row rendering for smart-ranked history words."""

from __future__ import annotations

from rich.cells import cell_len
from rich.text import Text

from sase.ace.tui.widgets._prompt_input_bar_completion_rows_simple import (
    append_prompt_word_completion_row,
)
from sase.ace.tui.widgets._ranking_signal_rows import (
    build_score_meter,
    format_reason_chip,
    ranking_label_width,
)
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.history_word_completion import (
    HistoryWordCompletionMetadata,
    HistoryWordCompletionPlaceholder,
)

_LABEL_WIDTH_CAP = 28


def history_word_label_width(candidate: CompletionCandidate) -> int:
    """Visible width for the word column in a smart-ranked history-word row."""
    if isinstance(candidate.metadata, HistoryWordCompletionPlaceholder):
        return 0
    return ranking_label_width(candidate.display, badge_cells=0, cap=_LABEL_WIDTH_CAP)


def append_history_word_completion_row(
    content: Text,
    candidate: CompletionCandidate,
    is_selected: bool,
    *,
    label_width: int,
    inner_width: int,
    signals_enabled: bool,
) -> None:
    """Append one history-word row, degrading by width without clipping.

    The word is always shown in full; the meter is dropped when it would not
    fit, and the chip is dropped before the meter. Falls back to the plain
    word row used by the ``prompt_word`` menu for the loading placeholder,
    ``recent`` ranking (no metadata), and when ``word_ranking_signals`` is
    off.
    """
    if isinstance(candidate.metadata, HistoryWordCompletionPlaceholder):
        content.append(candidate.display, style="dim italic")
        return

    metadata = (
        candidate.metadata
        if isinstance(candidate.metadata, HistoryWordCompletionMetadata)
        else None
    )
    if metadata is None or not signals_enabled:
        append_prompt_word_completion_row(content, candidate, is_selected)
        return

    content.append(candidate.display, style="bold" if is_selected else "")
    word_width = cell_len(candidate.display)
    available = inner_width - 2 if inner_width > 0 else None

    meter = build_score_meter(metadata)
    gap_and_padding = label_width - word_width + 2
    used = word_width + gap_and_padding + meter.cell_len
    if available is not None and used > available:
        return
    content.append(" " * gap_and_padding)
    content.append_text(meter)

    chip = format_reason_chip(metadata)
    used += 2 + chip.cell_len
    if available is not None and used > available:
        return
    content.append("  ")
    content.append_text(chip)
