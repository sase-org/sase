"""Ranking for saved common-placeholder completions."""

from __future__ import annotations

import calendar
import math
import time
from dataclasses import dataclass
from typing import Literal, Protocol

from sase.history.prompt_placeholders import (
    CommonPlaceholderIndex,
    prompt_context_tokens,
)

# The ranking policy lives here: relation is the strongest single signal, while
# recency plus frequency can still beat weak or stale relation evidence.
# Recency uses a 14-day half-life (not the history-word engine's 7) because
# this store is a small LRU whose median entry is weeks old.
RELATION_WEIGHT = 0.50
RECENCY_WEIGHT = 0.30
FREQUENCY_WEIGHT = 0.20
RECENCY_HALF_LIFE_SECONDS = 14 * 86400
RELATION_LIFT_CAP = 8.0
RELATION_SHRINKAGE = 2.0
RELATION_MIN_PROMPTS = 8
CONTEXT_MAX_TOKENS = 24

RankingReason = Literal["relation", "recency", "frequency"]


@dataclass(frozen=True, slots=True)
class RankedPlaceholder:
    """A scored saved placeholder and the evidence needed by completion rows."""

    text: str
    score: float
    relation: float
    recency: float
    frequency: float
    reason: RankingReason
    related_to: str
    use_count: int
    age_seconds: float


class _PlaceholderSignals(Protocol):
    """The store entry fields the ranker reads."""

    text: str
    count: int
    last_used: str
    context_uses: int
    context: dict[str, int]


@dataclass(frozen=True, slots=True)
class _PlaceholderRankingContext:
    """Prompt-derived context tokens and IDF weights memoized on one index."""

    tokens: tuple[str, ...]
    idf: dict[str, float]


def build_placeholder_ranking_context(
    index: CommonPlaceholderIndex,
    text: str,
    *,
    now: float,
) -> _PlaceholderRankingContext:
    """Tokenize *text* the same way the store records context.

    ``now`` is accepted so callers capture the ranking instant once; recency
    is applied later in :func:`rank_common_placeholders`.  The result is
    memoized on *index* and keyed by the context token tuple.
    """
    tokens = prompt_context_tokens(
        text,
        context_frequency=index.context_frequency,
        prompt_count=index.prompt_count,
    )[:CONTEXT_MAX_TOKENS]
    cached = index._ranking_memo
    if isinstance(cached, _PlaceholderRankingContext) and cached.tokens == tokens:
        return cached

    idf: dict[str, float] = {}
    prompt_count = index.prompt_count
    if prompt_count > 0:
        for token in tokens:
            document_frequency = index.context_frequency.get(token, 0)
            if document_frequency <= 0:
                continue
            weight = math.log(prompt_count / document_frequency)
            if weight > 0.0:
                idf[token] = weight

    context = _PlaceholderRankingContext(tokens=tokens, idf=idf)
    object.__setattr__(index, "_ranking_memo", context)
    return context


def rank_common_placeholders(
    index: CommonPlaceholderIndex,
    context: _PlaceholderRankingContext,
    *,
    now: float,
) -> list[RankedPlaceholder]:
    """Return every saved placeholder scored for *context* and *now*."""
    ranked = [
        _ranked_placeholder(index, entry, context, now=now) for entry in index.entries
    ]
    ranked.sort(key=lambda item: (-item.score, item.text.casefold(), item.text))
    return ranked


def rank_recent_common_placeholders(
    index: CommonPlaceholderIndex,
    *,
    now: float,
) -> list[RankedPlaceholder]:
    """Return saved placeholders in stored display order with no ranking evidence."""
    return [
        RankedPlaceholder(
            text=entry.text,
            score=0.0,
            relation=0.0,
            recency=0.0,
            frequency=0.0,
            reason="recency",
            related_to="",
            use_count=entry.count,
            age_seconds=_age_seconds(entry.last_used, now=now),
        )
        for entry in index.entries
    ]


def _ranked_placeholder(
    index: CommonPlaceholderIndex,
    entry: _PlaceholderSignals,
    context: _PlaceholderRankingContext,
    *,
    now: float,
) -> RankedPlaceholder:
    age_seconds = _age_seconds(entry.last_used, now=now)
    relation_raw, related_to = _relation_signal(index, entry, context)
    relation = RELATION_WEIGHT * relation_raw
    recency = RECENCY_WEIGHT * _decay(age_seconds)
    frequency = FREQUENCY_WEIGHT * _frequency(index, entry.count)
    return RankedPlaceholder(
        text=entry.text,
        score=relation + recency + frequency,
        relation=relation,
        recency=recency,
        frequency=frequency,
        reason=_dominant_reason(
            relation=relation,
            recency=recency,
            frequency=frequency,
        ),
        related_to=related_to,
        use_count=entry.count,
        age_seconds=age_seconds,
    )


def _relation_signal(
    index: CommonPlaceholderIndex,
    entry: _PlaceholderSignals,
    context: _PlaceholderRankingContext,
) -> tuple[float, str]:
    if index.prompt_count < RELATION_MIN_PROMPTS or not context.tokens:
        return 0.0, ""
    if entry.context_uses <= 0:
        return 0.0, ""

    observed = 0.0
    background = 0.0
    hits = 0
    best_token = ""
    best_contribution = 0.0
    for token in context.tokens:
        inverse_document_frequency = context.idf.get(token)
        if inverse_document_frequency is None or inverse_document_frequency <= 0.0:
            continue
        document_frequency = index.context_frequency.get(token, 0)
        if document_frequency <= 0:
            continue
        background += inverse_document_frequency * (
            document_frequency / index.prompt_count
        )
        count = entry.context.get(token, 0)
        if count <= 0:
            continue
        hits += 1
        contribution = inverse_document_frequency * count / entry.context_uses
        observed += contribution
        if contribution > best_contribution or (
            contribution == best_contribution and (not best_token or token < best_token)
        ):
            best_contribution = contribution
            best_token = token

    if observed <= 0.0 or background <= 0.0 or hits <= 0:
        return 0.0, ""
    lift = observed / background
    if lift <= 1.0:
        return 0.0, ""
    capped_lift = min(1.0, math.log2(lift) / math.log2(RELATION_LIFT_CAP))
    shrinkage = hits / (hits + RELATION_SHRINKAGE)
    relation = max(0.0, min(1.0, capped_lift * shrinkage))
    if relation <= 0.0:
        return 0.0, ""
    return relation, best_token


def _frequency(index: CommonPlaceholderIndex, count: int) -> float:
    if index.max_count <= 0:
        return 0.0
    return min(1.0, math.log1p(count) / math.log1p(index.max_count))


def _age_seconds(last_used: str, *, now: float) -> float:
    return max(0.0, now - _last_used_epoch(last_used))


def _decay(age_seconds: float) -> float:
    if RECENCY_HALF_LIFE_SECONDS <= 0.0:
        return 0.0
    return min(1.0, max(0.0, 0.5 ** (age_seconds / RECENCY_HALF_LIFE_SECONDS)))


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


def _last_used_epoch(timestamp: str) -> float:
    """Parse a ``%y%m%d_%H%M%S`` local stamp; unparsable values are epoch 0."""
    raw = timestamp.strip()
    if len(raw) != 13 or raw[6] != "_":
        return 0.0
    try:
        year = _full_year(int(raw[0:2]))
        month = int(raw[2:4])
        day = int(raw[4:6])
        hour = int(raw[7:9])
        minute = int(raw[9:11])
        second = int(raw[11:13])
    except ValueError:
        return 0.0
    if (
        not 1 <= month <= 12
        or not 1 <= day <= calendar.monthrange(year, month)[1]
        or not 0 <= hour <= 23
        or not 0 <= minute <= 59
        or not 0 <= second <= 59
    ):
        return 0.0
    try:
        return time.mktime((year, month, day, hour, minute, second, -1, -1, -1))
    except (OverflowError, ValueError):
        return 0.0


def _full_year(two_digit_year: int) -> int:
    if two_digit_year <= 68:
        return 2000 + two_digit_year
    return 1900 + two_digit_year
