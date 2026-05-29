"""Evidence and lesson card construction for episode recall."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from sase.core.episode_wire import (
    EPISODE_WIRE_SCHEMA_VERSION,
    EpisodeSourceRefWire,
    EpisodeWire,
)
from sase.memory.episodes._recall_text import (
    safety_flags,
    safety_recall_terms,
    token_list,
    token_set,
    truncate_excerpt,
    weak_refs_recall_terms,
    weak_refs_summary,
)
from sase.memory.episodes._recall_types import (
    EpisodeRecallEvidence,
    EpisodeRecallEvidenceCard,
    EpisodeRecallLessonCard,
)


def recall_lesson_cards(
    episode: EpisodeWire,
    query_terms: set[str],
) -> list[EpisodeRecallLessonCard]:
    source_by_id = {source.id: source for source in episode.sources}
    cards: list[EpisodeRecallLessonCard] = []
    for lesson in sorted(episode.lessons, key=lambda item: item.id):
        if not (query_terms & token_set(lesson.text)):
            continue
        cards.append(
            EpisodeRecallLessonCard(
                lesson_id=lesson.id,
                kind=lesson.kind,
                text=truncate_excerpt(lesson.text),
                evidence=_recall_evidence_links(lesson.evidence_ids, source_by_id),
            )
        )
    return cards[:3]


def recall_evidence_cards(
    episode: EpisodeWire,
    query_terms: set[str],
) -> list[EpisodeRecallEvidenceCard]:
    source_by_id = {source.id: source for source in episode.sources}
    candidates: list[EpisodeRecallEvidenceCard] = []

    summary_text = " ".join(
        [
            episode.title,
            episode.summary,
            episode.status,
            episode.importance_band,
            str(episode.importance_score),
        ]
    )
    if query_terms & token_set(summary_text):
        candidates.append(
            EpisodeRecallEvidenceCard(
                card_id="summary",
                kind="summary",
                title=episode.title,
                text=truncate_excerpt(
                    f"{episode.summary} Status: {episode.status}. "
                    f"Importance: {episode.importance_band} "
                    f"({episode.importance_score})."
                ),
                evidence=[],
            )
        )

    for event in sorted(
        episode.events,
        key=lambda item: (item.timestamp is None, item.timestamp or "", item.id),
    ):
        event_text = " ".join(
            [
                event.kind,
                event.title,
                event.description or "",
                event.timestamp or "",
                " ".join(event.evidence_ids),
            ]
        )
        if not (query_terms & token_set(event_text)):
            continue
        text_parts = [event.timestamp or "undated", event.description or ""]
        candidates.append(
            EpisodeRecallEvidenceCard(
                card_id=event.id,
                kind=f"timeline:{event.kind}",
                title=event.title,
                text=truncate_excerpt(" ".join(part for part in text_parts if part)),
                evidence=_recall_evidence_links(event.evidence_ids, source_by_id),
            )
        )

    for factor in sorted(
        episode.importance_factors,
        key=lambda item: (-item.score, item.kind, item.label),
    ):
        factor_text = " ".join(
            [
                factor.kind,
                factor.label,
                str(factor.score),
                " ".join(factor.evidence_ids),
                " ".join(factor.metadata.values()),
            ]
        )
        if not (query_terms & token_set(factor_text)):
            continue
        candidates.append(
            EpisodeRecallEvidenceCard(
                card_id=f"importance:{factor.kind}",
                kind="importance_factor",
                title=factor.label,
                text=truncate_excerpt(f"{factor.kind} score={factor.score}"),
                evidence=_recall_evidence_links(factor.evidence_ids, source_by_id),
            )
        )

    for source in sorted(episode.sources, key=lambda item: (item.kind, item.path)):
        source_text = " ".join([source.kind, source.label or "", source.path])
        if not (query_terms & token_set(source_text)):
            continue
        status = "exists" if source.exists else "missing"
        candidates.append(
            EpisodeRecallEvidenceCard(
                card_id=f"source:{source.id}",
                kind=f"source:{source.kind}",
                title=source.label or Path(source.path).name or source.path,
                text=truncate_excerpt(f"{source.path} ({status})"),
                evidence=_recall_evidence_links([source.id], source_by_id),
            )
        )

    weak_text = weak_refs_recall_terms(episode)
    if query_terms & token_set(weak_text):
        candidates.append(
            EpisodeRecallEvidenceCard(
                card_id="weak_refs",
                kind="weak_refs",
                title="Weak metadata",
                text=truncate_excerpt(weak_refs_summary(episode)),
                evidence=[],
            )
        )

    safety_text = safety_recall_terms(episode)
    if query_terms & token_set(safety_text):
        candidates.append(
            EpisodeRecallEvidenceCard(
                card_id="safety",
                kind="safety",
                title="Safety flags",
                text=truncate_excerpt("; ".join(safety_flags(episode))),
                evidence=[],
            )
        )

    scored = [
        (_evidence_card_score(card, query_terms), card)
        for card in _dedupe_evidence_cards(candidates)
    ]
    scored = [(score, card) for score, card in scored if score > 0]
    scored.sort(key=lambda item: (-item[0], item[1].kind, item[1].card_id))
    return [card for _, card in scored[:5]]


def _recall_evidence_links(
    evidence_ids: list[str],
    source_by_id: dict[str, EpisodeSourceRefWire],
) -> list[EpisodeRecallEvidence]:
    links: list[EpisodeRecallEvidence] = []
    for source_id in sorted({item for item in evidence_ids if item}):
        source = source_by_id.get(source_id)
        if source is None:
            links.append(
                EpisodeRecallEvidence(
                    source_id=source_id,
                    kind="unknown",
                    label=source_id,
                    path="",
                    exists=False,
                )
            )
            continue
        links.append(
            EpisodeRecallEvidence(
                source_id=source.id,
                kind=source.kind,
                label=source.label or Path(source.path).name or source.path,
                path=source.path,
                exists=source.exists,
            )
        )
    return links[:5]


def _dedupe_evidence_cards(
    cards: list[EpisodeRecallEvidenceCard],
) -> list[EpisodeRecallEvidenceCard]:
    by_id: dict[str, EpisodeRecallEvidenceCard] = {}
    for card in cards:
        by_id.setdefault(card.card_id, card)
    return list(by_id.values())


def _evidence_card_score(
    card: EpisodeRecallEvidenceCard,
    query_terms: set[str],
) -> int:
    text = " ".join(
        [
            card.card_id,
            card.kind,
            card.title,
            card.text,
            " ".join(source.source_id for source in card.evidence),
            " ".join(source.label for source in card.evidence),
            " ".join(source.path for source in card.evidence),
        ]
    )
    token_counts = Counter(token_list(text))
    return sum(token_counts[term] for term in query_terms)


def is_v2_evidence_episode(episode: EpisodeWire) -> bool:
    return (
        episode.schema_version >= EPISODE_WIRE_SCHEMA_VERSION
        and episode.status != "legacy"
        and bool(episode.component_key)
    )
