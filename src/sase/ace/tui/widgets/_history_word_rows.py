"""Score meter, reason chip, and row rendering for smart-ranked history words."""

from __future__ import annotations

import math

from rich.cells import cell_len
from rich.text import Text

from sase.ace.tui.widgets._prompt_input_bar_completion_rows_simple import (
    append_prompt_word_completion_row,
)
from sase.ace.tui.widgets._prompt_input_bar_completion_rows_utils import (
    truncate_cell,
)
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.history_word_completion import (
    HistoryWordCompletionMetadata,
    HistoryWordCompletionPlaceholder,
)

RELATION_COLOR = "#5FD7D7"
RECENCY_COLOR = "#87D787"
FREQUENCY_COLOR = "#D7AF5F"
RELATION_GLYPH = "⇄"
RECENCY_GLYPH = "◷"
FREQUENCY_GLYPH = "✦"

_LABEL_WIDTH_CAP = 28
_METER_CELLS = 5
_METER_FILLED = "▰"
_METER_EMPTY = "▱"
_CONTEXT_WORD_MAX_CELLS = 16

_REASON_GLYPHS = {
    "relation": RELATION_GLYPH,
    "recency": RECENCY_GLYPH,
    "frequency": FREQUENCY_GLYPH,
}
_REASON_COLORS = {
    "relation": RELATION_COLOR,
    "recency": RECENCY_COLOR,
    "frequency": FREQUENCY_COLOR,
}


def history_word_label_width(candidate: CompletionCandidate) -> int:
    """Visible width for the word column in a smart-ranked history-word row."""
    if isinstance(candidate.metadata, HistoryWordCompletionPlaceholder):
        return 0
    return min(_LABEL_WIDTH_CAP, cell_len(candidate.display))


def _build_score_meter(metadata: HistoryWordCompletionMetadata) -> Text:
    """Return the 5-cell stacked composite-score meter for one ranked row.

    Filled length tracks ``metadata.score``; the filled cells are colored by
    signal, largest-remainder distributed in a fixed relation -> recency ->
    frequency order so the colors never shuffle between repaints.
    """
    filled = (
        0
        if metadata.score <= 0
        else max(1, min(_METER_CELLS, round(metadata.score * _METER_CELLS)))
    )
    meter = Text(no_wrap=True)
    for color in _meter_cell_colors(metadata, filled):
        meter.append(_METER_FILLED, style=f"bold {color}")
    for _ in range(_METER_CELLS - filled):
        meter.append(_METER_EMPTY, style="dim")
    return meter


def _meter_cell_colors(
    metadata: HistoryWordCompletionMetadata,
    filled: int,
) -> list[str]:
    if filled <= 0:
        return []
    contributions = (
        (metadata.relation, RELATION_COLOR),
        (metadata.recency, RECENCY_COLOR),
        (metadata.frequency, FREQUENCY_COLOR),
    )
    total = metadata.relation + metadata.recency + metadata.frequency
    if total <= 0:
        return [_REASON_COLORS.get(metadata.reason, RECENCY_COLOR)] * filled

    shares = [value / total * filled for value, _color in contributions]
    bases = [math.floor(share) for share in shares]
    remainders = [share - base for share, base in zip(shares, bases, strict=True)]

    remaining = filled - sum(bases)
    remainder_order = sorted(range(3), key=lambda i: (-remainders[i], i))
    for index in remainder_order[:remaining]:
        bases[index] += 1

    colors: list[str] = []
    for (_value, color), count in zip(contributions, bases, strict=True):
        colors.extend([color] * count)
    return colors


def _format_reason_chip(metadata: HistoryWordCompletionMetadata) -> Text:
    """Return the dominant-reason chip for one smart-ranked history-word row."""
    glyph = _REASON_GLYPHS.get(metadata.reason, RECENCY_GLYPH)
    color = _REASON_COLORS.get(metadata.reason, RECENCY_COLOR)
    chip = Text(no_wrap=True)
    chip.append(glyph, style=f"bold {color}")
    chip.append(" ")
    if metadata.reason == "relation" and metadata.related_to:
        chip.append(truncate_cell(metadata.related_to, _CONTEXT_WORD_MAX_CELLS))
    elif metadata.reason == "frequency":
        chip.append(f"{metadata.use_count}×")
    else:
        chip.append(_format_age(metadata.age_seconds))
    return chip


def _format_age(age_seconds: float) -> str:
    """Return a compact ``s``/``m``/``h``/``d``/``w`` age label."""
    age = max(0.0, age_seconds)
    if age < 60:
        return f"{int(age)}s"
    minutes = age / 60
    if minutes < 60:
        return f"{int(minutes)}m"
    hours = minutes / 60
    if hours < 24:
        return f"{int(hours)}h"
    days = hours / 24
    if days < 7:
        return f"{int(days)}d"
    return f"{int(days / 7)}w"


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

    meter = _build_score_meter(metadata)
    gap_and_padding = label_width - word_width + 2
    used = word_width + gap_and_padding + meter.cell_len
    if available is not None and used > available:
        return
    content.append(" " * gap_and_padding)
    content.append_text(meter)

    chip = _format_reason_chip(metadata)
    used += 2 + chip.cell_len
    if available is not None and used > available:
        return
    content.append("  ")
    content.append_text(chip)
