"""Provider-neutral score meter, reason chip, and legend for ranked rows.

Shared by every completion provider that ranks candidates by relation,
recency, and frequency (history words today, saved placeholders once phase
``signals`` lands) so they render identical evidence from one small
structural protocol rather than each provider's own metadata dataclass.
"""

from __future__ import annotations

import math
from typing import Protocol, runtime_checkable

from rich.cells import cell_len
from rich.text import Text

from sase.ace.tui.widgets._prompt_input_bar_completion_rows_utils import (
    truncate_cell,
)

RELATION_COLOR = "#5FD7D7"
RECENCY_COLOR = "#87D787"
FREQUENCY_COLOR = "#D7AF5F"
RELATION_GLYPH = "⇄"
RECENCY_GLYPH = "◷"
FREQUENCY_GLYPH = "✦"

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


@runtime_checkable
class _RankingSignals(Protocol):
    """Structural contract for one ranked candidate's meter/chip evidence."""

    @property
    def reason(self) -> str: ...
    @property
    def related_to(self) -> str: ...
    @property
    def use_count(self) -> int: ...
    @property
    def age_seconds(self) -> float: ...
    @property
    def score(self) -> float: ...
    @property
    def relation(self) -> float: ...
    @property
    def recency(self) -> float: ...
    @property
    def frequency(self) -> float: ...


def ranking_label_width(display: str, *, badge_cells: int, cap: int) -> int:
    """Visible width for the label column of one ranked row, badge included."""
    return min(cap, badge_cells + cell_len(display))


def build_score_meter(signals: _RankingSignals) -> Text:
    """Return the 5-cell stacked composite-score meter for one ranked row.

    Filled length tracks ``signals.score``; the filled cells are colored by
    signal, largest-remainder distributed in a fixed relation -> recency ->
    frequency order so the colors never shuffle between repaints.
    """
    filled = (
        0
        if signals.score <= 0
        else max(1, min(_METER_CELLS, round(signals.score * _METER_CELLS)))
    )
    meter = Text(no_wrap=True)
    for color in _meter_cell_colors(signals, filled):
        meter.append(_METER_FILLED, style=f"bold {color}")
    for _ in range(_METER_CELLS - filled):
        meter.append(_METER_EMPTY, style="dim")
    return meter


def _meter_cell_colors(signals: _RankingSignals, filled: int) -> list[str]:
    if filled <= 0:
        return []
    contributions = (
        (signals.relation, RELATION_COLOR),
        (signals.recency, RECENCY_COLOR),
        (signals.frequency, FREQUENCY_COLOR),
    )
    total = signals.relation + signals.recency + signals.frequency
    if total <= 0:
        return [_REASON_COLORS.get(signals.reason, RECENCY_COLOR)] * filled

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


def format_reason_chip(signals: _RankingSignals) -> Text:
    """Return the dominant-reason chip for one ranked row."""
    glyph = _REASON_GLYPHS.get(signals.reason, RECENCY_GLYPH)
    color = _REASON_COLORS.get(signals.reason, RECENCY_COLOR)
    chip = Text(no_wrap=True)
    chip.append(glyph, style=f"bold {color}")
    chip.append(" ")
    if signals.reason == "relation" and signals.related_to:
        chip.append(truncate_cell(signals.related_to, _CONTEXT_WORD_MAX_CELLS))
    elif signals.reason == "frequency":
        chip.append(f"{signals.use_count}×")
    else:
        chip.append(_format_age(signals.age_seconds))
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


def ranking_signal_legend() -> Text:
    """Return the colored relation/recency/frequency legend for ranked menus."""
    legend = Text(no_wrap=True)
    legend.append(RELATION_GLYPH, style=f"bold {RELATION_COLOR}")
    legend.append(" related", style="dim")
    legend.append(" · ", style="dim")
    legend.append(RECENCY_GLYPH, style=f"bold {RECENCY_COLOR}")
    legend.append(" recent", style="dim")
    legend.append(" · ", style="dim")
    legend.append(FREQUENCY_GLYPH, style=f"bold {FREQUENCY_COLOR}")
    legend.append(" frequent", style="dim")
    return legend
