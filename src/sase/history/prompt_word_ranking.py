"""Ranking for prompt-history word completions."""

from __future__ import annotations

from dataclasses import dataclass
import math
import time
from typing import Literal

from sase.history.prompt_word_index import _PROMPT_WORD_RE, PromptWordIndex

# The ranking policy lives here: relation is the strongest single signal, while
# recency plus frequency can still beat weak or stale relation evidence.
RELATION_WEIGHT = 0.50
RECENCY_WEIGHT = 0.30
FREQUENCY_WEIGHT = 0.20
RECENCY_HALF_LIFE_SECONDS = 7 * 86400
PROMPT_RECENCY_HALF_LIFE_SECONDS = 30 * 86400
RELATION_LIFT_CAP = 8.0
RELATION_SHRINKAGE = 2.0
RELATION_MIN_PROMPTS = 8
CONTEXT_STOPWORD_RATIO = 0.20
CONTEXT_MAX_WORDS = 24
CONTEXT_MAX_POSTINGS_PER_WORD = 2000
RELATED_PROMPT_LIMIT = 250
HISTORY_WORD_MAX_ROWS = 200

RankingReason = Literal["relation", "recency", "frequency"]


@dataclass(frozen=True, slots=True)
class RankedWord:
    """A scored prompt-history word and the evidence needed by completion rows."""

    word: str
    score: float
    relation: float
    recency: float
    frequency: float
    reason: RankingReason
    related_to: str
    use_count: int
    age_seconds: float


@dataclass(frozen=True, slots=True)
class _WordRankingContext:
    """Prompt-derived relation scores memoized against one prompt-word index."""

    context_key: tuple[int, ...]
    relation_by_word_id: dict[int, float]
    related_context_by_word_id: dict[int, int]


def build_word_ranking_context(
    index: PromptWordIndex,
    text: str,
    *,
    exclude_range: tuple[int, int] | None,
    now: float,
) -> _WordRankingContext:
    """Return relation scores for the prompt context surrounding the cursor word."""
    context_key = _context_word_key(index, text, exclude_range=exclude_range)
    cached = index._ranking_memo
    if isinstance(cached, _WordRankingContext) and cached.context_key == context_key:
        return cached

    relation_by_word_id: dict[int, float] = {}
    related_context_by_word_id: dict[int, int] = {}
    if index.prompt_count >= RELATION_MIN_PROMPTS and context_key:
        relation_by_word_id, related_context_by_word_id = _build_relation_scores(
            index,
            context_key,
            now=now,
        )

    context = _WordRankingContext(
        context_key=context_key,
        relation_by_word_id=relation_by_word_id,
        related_context_by_word_id=related_context_by_word_id,
    )
    object.__setattr__(index, "_ranking_memo", context)
    return context


def rank_history_words(
    index: PromptWordIndex,
    context: _WordRankingContext,
    *,
    prefix: str,
    deleted: set[str] | frozenset[str],
    exclude_exact: str | None,
    now: float,
    limit: int = HISTORY_WORD_MAX_ROWS,
) -> tuple[list[RankedWord], list[str]]:
    """Return smart-ranked prefix matches and the full extension source list."""
    ranked = [
        _ranked_word(index, context, word_id, now=now)
        for word_id in _prefix_candidate_word_ids(
            index,
            prefix=prefix,
            deleted=deleted,
            exclude_exact=exclude_exact,
        )
    ]
    ranked.sort(key=lambda item: (-item.score, item.word.casefold(), item.word))
    return ranked[: max(0, limit)], [item.word for item in ranked]


def rank_recent_history_words(
    index: PromptWordIndex,
    *,
    prefix: str,
    deleted: set[str] | frozenset[str],
    exclude_exact: str | None,
    now: float | None = None,
    limit: int = HISTORY_WORD_MAX_ROWS,
) -> tuple[list[RankedWord], list[str]]:
    """Return MRU prefix matches as zero-score ranked words."""
    timestamp = time.time() if now is None else now
    prefix_folded = prefix.casefold()
    ranked: list[RankedWord] = []
    for word_id in index.mru:
        word = index.spelling(word_id)
        if word in deleted:
            continue
        if exclude_exact is not None and word == exclude_exact:
            continue
        if not word.casefold().startswith(prefix_folded):
            continue
        ranked.append(
            RankedWord(
                word=word,
                score=0.0,
                relation=0.0,
                recency=0.0,
                frequency=0.0,
                reason="recency",
                related_to="",
                use_count=index.document_frequency[word_id],
                age_seconds=_word_age_seconds(index, word_id, now=timestamp),
            )
        )
    return ranked[: max(0, limit)], [item.word for item in ranked]


def _context_word_key(
    index: PromptWordIndex,
    text: str,
    *,
    exclude_range: tuple[int, int] | None,
) -> tuple[int, ...]:
    context_word_ids: set[int] = set()
    for match in _PROMPT_WORD_RE.finditer(text):
        if exclude_range is not None and _ranges_overlap(match.span(), exclude_range):
            continue
        for word_id in index.word_ids_for_spelling(match.group(0)):
            context_word_ids.add(word_id)

    if not context_word_ids or index.prompt_count <= 0:
        return ()

    informative = [
        word_id
        for word_id in context_word_ids
        if (
            index.document_frequency[word_id] > 0
            and index.document_frequency[word_id] / index.prompt_count
            <= CONTEXT_STOPWORD_RATIO
        )
    ]
    rarest = sorted(
        informative,
        key=lambda word_id: (
            index.document_frequency[word_id],
            index.spelling(word_id).casefold(),
            index.spelling(word_id),
            word_id,
        ),
    )[:CONTEXT_MAX_WORDS]
    return tuple(sorted(rarest))


def _ranges_overlap(first: tuple[int, int], second: tuple[int, int]) -> bool:
    return first[0] < second[1] and second[0] < first[1]


def _build_relation_scores(
    index: PromptWordIndex,
    context_key: tuple[int, ...],
    *,
    now: float,
) -> tuple[dict[int, float], dict[int, int]]:
    prompt_weights: dict[int, float] = {}
    prompt_contexts: dict[int, tuple[float, int]] = {}
    for context_word_id in context_key:
        document_frequency = index.document_frequency[context_word_id]
        if document_frequency <= 0:
            continue
        inverse_document_frequency = math.log(index.prompt_count / document_frequency)
        if inverse_document_frequency <= 0.0:
            continue
        prompt_ids = index.word_prompt_ids(context_word_id)[
            :CONTEXT_MAX_POSTINGS_PER_WORD
        ]
        for prompt_id in prompt_ids:
            prompt_weight = inverse_document_frequency * _decay(
                _prompt_age_seconds(index, prompt_id, now=now),
                half_life_seconds=PROMPT_RECENCY_HALF_LIFE_SECONDS,
            )
            if prompt_weight <= 0.0:
                continue
            prompt_weights[prompt_id] = prompt_weights.get(prompt_id, 0.0) + (
                prompt_weight
            )
            current = prompt_contexts.get(prompt_id)
            if current is None or (
                inverse_document_frequency,
                -context_word_id,
            ) > (current[0], -current[1]):
                prompt_contexts[prompt_id] = (
                    inverse_document_frequency,
                    context_word_id,
                )

    if not prompt_weights:
        return {}, {}

    related_prompts = sorted(
        prompt_weights.items(),
        key=lambda item: (-item[1], item[0]),
    )[:RELATED_PROMPT_LIMIT]
    total_weight = sum(weight for _, weight in related_prompts)
    if total_weight <= 0.0:
        return {}, {}

    mass_by_word_id: dict[int, float] = {}
    hits_by_word_id: dict[int, int] = {}
    related_context_by_word_id: dict[int, int] = {}
    evidence_rank_by_word_id: dict[int, tuple[float, int]] = {}
    for prompt_id, prompt_weight in related_prompts:
        context_word_id = prompt_contexts[prompt_id][1]
        for word_id in index.prompt_word_ids(prompt_id):
            mass_by_word_id[word_id] = mass_by_word_id.get(word_id, 0.0) + prompt_weight
            hits_by_word_id[word_id] = hits_by_word_id.get(word_id, 0) + 1
            evidence_rank = (prompt_weight, -prompt_id)
            current_rank = evidence_rank_by_word_id.get(word_id)
            if current_rank is None or evidence_rank > current_rank:
                evidence_rank_by_word_id[word_id] = evidence_rank
                related_context_by_word_id[word_id] = context_word_id

    relation_by_word_id: dict[int, float] = {}
    for word_id, mass in mass_by_word_id.items():
        document_frequency = index.document_frequency[word_id]
        if document_frequency <= 0:
            continue
        observed = mass / total_weight
        background = document_frequency / index.prompt_count
        if observed <= 0.0 or background <= 0.0:
            continue
        lift = observed / background
        if lift <= 1.0:
            continue
        capped_lift = min(1.0, math.log2(lift) / math.log2(RELATION_LIFT_CAP))
        hits = hits_by_word_id[word_id]
        shrinkage = hits / (hits + RELATION_SHRINKAGE)
        relation = max(0.0, min(1.0, capped_lift * shrinkage))
        if relation > 0.0:
            relation_by_word_id[word_id] = relation

    return relation_by_word_id, related_context_by_word_id


def _prefix_candidate_word_ids(
    index: PromptWordIndex,
    *,
    prefix: str,
    deleted: set[str] | frozenset[str],
    exclude_exact: str | None,
) -> list[int]:
    word_ids: list[int] = []
    for row in index.word_ids_with_prefix(prefix):
        word_id = index.folded_order[row]
        word = index.spelling(word_id)
        if word in deleted:
            continue
        if exclude_exact is not None and word == exclude_exact:
            continue
        word_ids.append(word_id)
    return word_ids


def _ranked_word(
    index: PromptWordIndex,
    context: _WordRankingContext,
    word_id: int,
    *,
    now: float,
) -> RankedWord:
    relation = RELATION_WEIGHT * context.relation_by_word_id.get(word_id, 0.0)
    recency = RECENCY_WEIGHT * _word_recency(index, word_id, now=now)
    frequency = FREQUENCY_WEIGHT * _word_frequency(index, word_id)
    score = relation + recency + frequency
    related_context_id = context.related_context_by_word_id.get(word_id)
    return RankedWord(
        word=index.spelling(word_id),
        score=score,
        relation=relation,
        recency=recency,
        frequency=frequency,
        reason=_dominant_reason(
            relation=relation,
            recency=recency,
            frequency=frequency,
        ),
        related_to=(
            "" if related_context_id is None else index.spelling(related_context_id)
        ),
        use_count=index.document_frequency[word_id],
        age_seconds=_word_age_seconds(index, word_id, now=now),
    )


def _dominant_reason(
    *,
    relation: float,
    recency: float,
    frequency: float,
) -> RankingReason:
    best_reason: RankingReason = "recency"
    best_value = 0.0
    reason_values: tuple[tuple[RankingReason, float], ...] = (
        ("relation", relation),
        ("recency", recency),
        ("frequency", frequency),
    )
    for reason, value in reason_values:
        if value > best_value:
            best_reason = reason
            best_value = value
    return best_reason


def _word_frequency(index: PromptWordIndex, word_id: int) -> float:
    if index.max_document_frequency <= 0:
        return 0.0
    return min(
        1.0,
        math.log1p(index.document_frequency[word_id])
        / math.log1p(index.max_document_frequency),
    )


def _word_recency(index: PromptWordIndex, word_id: int, *, now: float) -> float:
    return _decay(
        _word_age_seconds(index, word_id, now=now),
        half_life_seconds=RECENCY_HALF_LIFE_SECONDS,
    )


def _word_age_seconds(index: PromptWordIndex, word_id: int, *, now: float) -> float:
    return max(0.0, now - index.last_used_epoch[word_id])


def _prompt_age_seconds(index: PromptWordIndex, prompt_id: int, *, now: float) -> float:
    return max(0.0, now - index.prompt_epoch[prompt_id])


def _decay(age_seconds: float, *, half_life_seconds: float) -> float:
    if half_life_seconds <= 0.0:
        return 0.0
    return min(1.0, max(0.0, 0.5 ** (age_seconds / half_life_seconds)))
