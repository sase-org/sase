"""Row rendering for the explicit next-word menu."""

from __future__ import annotations

from rich.cells import cell_len
from rich.text import Text

from sase.ace.tui.widgets._prompt_input_bar_completion_rows_utils import (
    truncate_cell,
)
from sase.ace.tui.widgets._ranking_signal_rows import (
    SEQUENCE_COLOR,
    SEQUENCE_GLYPH,
    build_sequence_meter,
    ranking_label_width,
)
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.next_word_menu import NextWordCompletionMetadata

_LABEL_WIDTH_CAP = 28
_CONTINUATION_MAX_CELLS = 24


def next_word_label_width(candidate: CompletionCandidate) -> int:
    """Visible width for the word column in a next-word menu row."""
    return ranking_label_width(candidate.display, badge_cells=0, cap=_LABEL_WIDTH_CAP)


def append_next_word_completion_row(
    content: Text,
    candidate: CompletionCandidate,
    is_selected: bool,
    *,
    label_width: int,
    inner_width: int,
) -> None:
    """Append one next-word row, degrading by width without clipping.

    The word is always shown in full; the confidence meter is dropped when it
    would not fit, and the continuation preview is dropped before the meter.
    Rows without metadata fall back to the plain word rendering.
    """
    metadata = (
        candidate.metadata
        if isinstance(candidate.metadata, NextWordCompletionMetadata)
        else None
    )
    if metadata is None:
        content.append(candidate.display, style="bold" if is_selected else "")
        return

    content.append(candidate.display, style="bold" if is_selected else "")
    word_width = cell_len(candidate.display)
    available = inner_width - 2 if inner_width > 0 else None

    meter = build_sequence_meter(metadata.probability)
    gap_and_padding = label_width - word_width + 2
    used = word_width + gap_and_padding + meter.cell_len
    if available is not None and used > available:
        return
    content.append(" " * gap_and_padding)
    content.append_text(meter)

    continuation = " ".join(metadata.continuation)
    if not continuation:
        return
    chip = Text(no_wrap=True)
    chip.append(SEQUENCE_GLYPH, style=f"bold {SEQUENCE_COLOR}")
    chip.append(" ")
    chip.append(truncate_cell(continuation, _CONTINUATION_MAX_CELLS), style="dim")
    used += 2 + chip.cell_len
    if available is not None and used > available:
        return
    content.append("  ")
    content.append_text(chip)
