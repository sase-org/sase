"""Explicit next-word menu model for the prompt input chain.

When the chain is armed but no ghost can be shown (gate failed, mid-line, or
no width), ``Ctrl+T`` opens this menu instead of hinting. Candidates come
from the gated :class:`PromptPredictionResult`: only words with evidence at
order 1 or higher are offered, each carrying its gated continuation preview.
Accepting a row inserts the word with its separator and arms the chain again.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.prompt_word_completion import word_range_at_cursor
from sase.core.prompt_prediction_wire import (
    PromptPredictionCandidate,
    PromptPredictionResult,
)

#: Completion kind for the explicit next-word menu.
NEXT_WORD_COMPLETION_KIND = "next_word"

#: Rows offered per explicit next-word request.
NEXT_WORD_MENU_LIMIT = 5


@dataclass(frozen=True, slots=True)
class NextWordCompletionMetadata:
    """Ranking evidence carried by one next-word menu candidate."""

    score: float
    probability: float
    support: int
    order: int
    continuation: list[str] = field(default_factory=list)
    context_words: list[str] = field(default_factory=list)


def build_next_word_completion_candidates(
    result: PromptPredictionResult,
    *,
    limit: int = NEXT_WORD_MENU_LIMIT,
) -> list[CompletionCandidate]:
    """Return menu rows for *result*'s predicted words.

    Only candidates with evidence at order 1 or higher are offered; a word
    with unigram evidence only is never shown. Each row carries its gated
    continuation preview and the evidence context for the menu title.
    """
    rows: list[CompletionCandidate] = []
    for candidate in result.candidates:
        if not _is_offerable_next_word(candidate):
            continue
        rows.append(_next_word_candidate(candidate, result.context_words))
        if len(rows) >= max(1, limit):
            break
    return rows


def _is_offerable_next_word(candidate: PromptPredictionCandidate) -> bool:
    """Return whether *candidate* has non-unigram evidence and a word."""
    return bool(candidate.word) and candidate.order >= 1


def _next_word_candidate(
    candidate: PromptPredictionCandidate,
    context_words: list[str],
) -> CompletionCandidate:
    """Return one menu row for *candidate* with its continuation preview."""
    return CompletionCandidate(
        display=candidate.word,
        insertion=candidate.word,
        is_dir=False,
        name=candidate.word,
        metadata=NextWordCompletionMetadata(
            score=candidate.score,
            probability=candidate.probability,
            support=candidate.support,
            order=candidate.order,
            continuation=list(candidate.continuation[:3]),
            context_words=list(context_words),
        ),
    )


def next_word_menu_title(context_words: list[str]) -> str:
    """Return the menu title naming the last ``<=3`` evidence context words."""
    tail = [word for word in context_words[-3:] if word]
    if not tail:
        return "next word"
    return f"next word ⇢ “{' '.join(tail)}”"


def next_word_menu_context(rows: list[CompletionCandidate]) -> list[str]:
    """Return the evidence context words carried by the first menu row."""
    for candidate in rows:
        metadata = candidate.metadata
        if isinstance(metadata, NextWordCompletionMetadata):
            return list(metadata.context_words)
    return []


def next_word_fallback_at_word_end(text: str, cursor_offset: int) -> bool:
    """Return whether the cursor ends a prose word for the row-4b fallback.

    The explicit next-word request runs instead of clearing only when the
    cursor sits at the end of an identifier-like word; anywhere else the
    press stays a no-op.
    """
    word_range = word_range_at_cursor(text, cursor_offset)
    if word_range is None:
        return False
    _start, end = word_range
    return end == cursor_offset


__all__ = [
    "NEXT_WORD_COMPLETION_KIND",
    "NEXT_WORD_MENU_LIMIT",
    "NextWordCompletionMetadata",
    "build_next_word_completion_candidates",
    "next_word_fallback_at_word_end",
    "next_word_menu_context",
    "next_word_menu_title",
]
