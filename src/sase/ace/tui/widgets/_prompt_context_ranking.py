"""Context promotion for current-word menus from n-gram rank matches.

When the prompt prediction model is warm, the prompt-word and history-word
menus promote the candidates the model predicts for the words before the
cursor (``PromptPredictionModel.rank_prefix``). Promoted rows sort first and
carry ``"context"`` ranking evidence so they render the sequence signal:
a violet meter share, a dashed-arrow context chip, and a legend entry.
Without model matches this is a strict no-op: candidates keep their order
and their metadata is untouched.
"""

from __future__ import annotations

from collections.abc import Container, Sequence
from dataclasses import replace

from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.history_word_completion import (
    HistoryWordCompletionMetadata,
)
from sase.core.prompt_prediction_wire import (
    PromptPrefixRankMatch,
    PromptPrefixRankResult,
)

#: Matches requested per menu refresh; covers the visible window plus scroll.
CONTEXT_RANK_LIMIT = 100

#: Meter weight for the sequence contribution, paralleling RELATION_WEIGHT
#: in ``sase.history.prompt_word_ranking``: preceding-word n-gram evidence
#: is at least as strong as co-occurrence relation evidence.
CONTEXT_METER_WEIGHT = 0.5

#: Evidence context words named by one context chip, mirroring the
#: next-word menu title's last-``<=3`` convention.
CONTEXT_CHIP_WORDS = 3


def _context_promotion_lookup(
    matches: Sequence[PromptPrefixRankMatch],
    *,
    deleted: Container[str],
) -> dict[str, PromptPrefixRankMatch]:
    """Index *matches* by folded key, dropping history-deleted words.

    *deleted* holds casefolded words (the history-word deletions store), so
    ``Ctrl+D`` forgets a word from context promotion without waiting for a
    corpus rebuild. The first match wins on duplicate keys.
    """
    lookup: dict[str, PromptPrefixRankMatch] = {}
    for match in matches:
        key = match.key.casefold()
        if not key or key in deleted:
            continue
        lookup.setdefault(key, match)
    return lookup


def _context_chip_text(context_words: Sequence[str]) -> str:
    """Return the evidence context named by one context chip."""
    return " ".join(word for word in context_words[-CONTEXT_CHIP_WORDS:] if word)


def has_context_promotion(candidates: Sequence[CompletionCandidate]) -> bool:
    """Return whether any candidate carries context-promotion evidence."""
    return any(
        isinstance(candidate.metadata, HistoryWordCompletionMetadata)
        and candidate.metadata.reason == "context"
        for candidate in candidates
    )


def apply_context_promotion(
    candidates: list[CompletionCandidate],
    result: PromptPrefixRankResult | None,
    *,
    deleted: Container[str] = frozenset(),
) -> list[CompletionCandidate]:
    """Promote model-predicted candidates and mark them with context evidence.

    Candidates whose folded name the model predicts for the preceding words
    sort before every other row (by model score, then key, so the order is
    fully deterministic) and carry ``"context"`` ranking metadata. A cold or
    missing *result*, or one with no surviving matches, returns *candidates*
    unchanged.
    """
    if result is None:
        return candidates
    lookup = _context_promotion_lookup(result.matches, deleted=deleted)
    if not lookup:
        return candidates
    chip_text = _context_chip_text(result.context_words)

    promoted: list[tuple[CompletionCandidate, PromptPrefixRankMatch, int]] = []
    rest: list[CompletionCandidate] = []
    for index, candidate in enumerate(candidates):
        match = lookup.get(candidate.name.casefold())
        if match is None:
            rest.append(candidate)
            continue
        promoted.append(
            (_with_context_evidence(candidate, match, chip_text), match, index)
        )
    if not promoted:
        return candidates
    promoted.sort(key=lambda item: (-item[1].score, item[1].key, item[2]))

    ordered = [candidate for candidate, _match, _index in promoted]
    ordered.extend(rest)
    return ordered


def _with_context_evidence(
    candidate: CompletionCandidate,
    match: PromptPrefixRankMatch,
    chip_text: str,
) -> CompletionCandidate:
    """Return *candidate* carrying the sequence evidence from *match*."""
    contribution = CONTEXT_METER_WEIGHT * min(1.0, max(0.0, match.score))
    metadata = candidate.metadata
    if isinstance(metadata, HistoryWordCompletionMetadata):
        evidence = replace(
            metadata,
            reason="context",
            score=min(1.0, metadata.score + contribution),
            context=contribution,
            context_order=match.order,
            context_support=match.support,
            context_words=chip_text,
        )
    else:
        evidence = HistoryWordCompletionMetadata(
            reason="context",
            related_to="",
            use_count=0,
            age_seconds=0.0,
            score=min(1.0, contribution),
            relation=0.0,
            recency=0.0,
            frequency=0.0,
            context=contribution,
            context_order=match.order,
            context_support=match.support,
            context_words=chip_text,
        )
    return replace(candidate, metadata=evidence)


__all__ = [
    "CONTEXT_CHIP_WORDS",
    "CONTEXT_METER_WEIGHT",
    "CONTEXT_RANK_LIMIT",
    "apply_context_promotion",
    "has_context_promotion",
]
