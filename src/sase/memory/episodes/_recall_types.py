"""Data shapes for episodic-memory recall results."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EpisodeRecallEvidence:
    """A compact source link attached to a recalled card."""

    source_id: str
    kind: str
    label: str
    path: str
    exists: bool

    def to_json_dict(self) -> dict[str, Any]:
        """Return a deterministic JSON-safe projection."""

        return {
            "exists": self.exists,
            "kind": self.kind,
            "label": self.label,
            "path": self.path,
            "source_id": self.source_id,
        }


@dataclass(frozen=True)
class EpisodeRecallLessonCard:
    """A compact recalled lesson with traceable evidence links."""

    lesson_id: str
    kind: str
    text: str
    evidence: list[EpisodeRecallEvidence]

    def to_json_dict(self) -> dict[str, Any]:
        """Return a deterministic JSON-safe projection."""

        return {
            "evidence": [item.to_json_dict() for item in self.evidence],
            "kind": self.kind,
            "lesson_id": self.lesson_id,
            "text": self.text,
        }


@dataclass(frozen=True)
class EpisodeRecallEvidenceCard:
    """A compact v2 evidence card with traceable source links."""

    card_id: str
    kind: str
    title: str
    text: str
    evidence: list[EpisodeRecallEvidence]

    def to_json_dict(self) -> dict[str, Any]:
        """Return a deterministic JSON-safe projection."""

        return {
            "card_id": self.card_id,
            "evidence": [item.to_json_dict() for item in self.evidence],
            "kind": self.kind,
            "text": self.text,
            "title": self.title,
        }


@dataclass(frozen=True)
class EpisodeRecallMatch:
    """One deterministic recall match against a stored episode."""

    episode_id: str
    title: str
    score: int
    matched_terms: list[str]
    excerpt: str
    lesson_ids: list[str]
    lesson_path: str
    last_event_at: str | None
    outcome: str | None
    lessons: list[EpisodeRecallLessonCard]
    evidence_cards: list[EpisodeRecallEvidenceCard]

    def to_json_dict(self) -> dict[str, Any]:
        """Return a deterministic JSON-safe projection."""

        return {
            "episode_id": self.episode_id,
            "excerpt": self.excerpt,
            "last_event_at": self.last_event_at,
            "lesson_ids": self.lesson_ids,
            "lesson_path": self.lesson_path,
            "lessons": [lesson.to_json_dict() for lesson in self.lessons],
            "evidence_cards": [card.to_json_dict() for card in self.evidence_cards],
            "matched_terms": self.matched_terms,
            "outcome": self.outcome,
            "score": self.score,
            "title": self.title,
        }
