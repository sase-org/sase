"""Deterministic lexical recall for stored episodic-memory records."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any

from sase.core.episode_wire import (
    EpisodeStorageIndexRowWire,
    EpisodeWire,
    episode_wire_from_dict,
)
from sase.memory.episodes.identity import (
    read_episode_alias_rows,
    resolve_alias_episode_id,
)
from sase.memory.episodes.index import project_episodes_dir
from sase.memory.episodes.render import render_lesson_markdown
from sase.memory.episodes.storage import (
    EPISODE_JSON_FILE_NAME,
    EPISODE_LESSON_FILE_NAME,
)

_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]*")
_EXCERPT_MAX_CHARS = 180
_SUCCESS_OUTCOMES = {"completed", "noop", "success", "succeeded"}


@dataclass(frozen=True)
class _EpisodeRecallEvidence:
    """A compact source link attached to a recalled lesson."""

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
class _EpisodeRecallLessonCard:
    """A compact recalled lesson with traceable evidence links."""

    lesson_id: str
    kind: str
    text: str
    evidence: list[_EpisodeRecallEvidence]

    def to_json_dict(self) -> dict[str, Any]:
        """Return a deterministic JSON-safe projection."""

        return {
            "evidence": [item.to_json_dict() for item in self.evidence],
            "kind": self.kind,
            "lesson_id": self.lesson_id,
            "text": self.text,
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
    lessons: list[_EpisodeRecallLessonCard]

    def to_json_dict(self) -> dict[str, Any]:
        """Return a deterministic JSON-safe projection."""

        return {
            "episode_id": self.episode_id,
            "excerpt": self.excerpt,
            "last_event_at": self.last_event_at,
            "lesson_ids": self.lesson_ids,
            "lesson_path": self.lesson_path,
            "lessons": [lesson.to_json_dict() for lesson in self.lessons],
            "matched_terms": self.matched_terms,
            "outcome": self.outcome,
            "score": self.score,
            "title": self.title,
        }


def recall_episode_rows(
    rows: Iterable[EpisodeStorageIndexRowWire],
    query: str,
    *,
    projects_root: Path | str | None = None,
    limit: int = 10,
) -> list[EpisodeRecallMatch]:
    """Return stable lexical recall matches for ``query`` over stored rows."""

    query_terms = _token_set(query)
    if not query_terms:
        raise ValueError("query must include at least one token")

    row_list = list(rows)
    alias_rows_by_project = {
        project: read_episode_alias_rows(project, projects_root=projects_root)
        for project in sorted({row.project for row in row_list})
    }
    matches = [
        match
        for row in row_list
        if resolve_alias_episode_id(
            row.episode_id,
            alias_rows_by_project.get(row.project, []),
        )
        == row.episode_id
        if (
            match := _recall_match(
                row,
                query_terms,
                projects_root=projects_root,
                alias_episode_ids=_alias_ids_for_row(
                    row,
                    alias_rows_by_project.get(row.project, []),
                ),
            )
        )
        is not None
    ]
    matches.sort(key=_recall_sort_key)
    return matches[:limit]


def _recall_match(
    row: EpisodeStorageIndexRowWire,
    query_terms: set[str],
    *,
    projects_root: Path | str | None,
    alias_episode_ids: list[str],
) -> EpisodeRecallMatch | None:
    episode_dir = project_episodes_dir(row.project, projects_root=projects_root) / (
        row.episode_id
    )
    episode = _load_episode_or_none(episode_dir)
    if episode is None:
        return None

    lesson_text = _lesson_text(row, episode, episode_dir)
    lesson_ids = [
        lesson.id
        for lesson in sorted(episode.lessons, key=lambda item: item.id)
        if query_terms & _token_set(lesson.text)
    ]
    token_counts = Counter(
        _token_list(_recall_corpus(row, episode, lesson_text, alias_episode_ids))
    )
    matched_terms = sorted(term for term in query_terms if token_counts.get(term, 0))
    if not matched_terms:
        return None

    lesson_cards = _recall_lesson_cards(episode, query_terms)
    return EpisodeRecallMatch(
        episode_id=row.episode_id,
        title=row.title,
        score=sum(token_counts[term] for term in matched_terms),
        matched_terms=matched_terms,
        excerpt=_recall_excerpt(episode, lesson_text, query_terms),
        lesson_ids=lesson_ids[:8],
        lesson_path=row.lesson_path,
        last_event_at=row.last_event_at,
        outcome=row.outcome,
        lessons=lesson_cards,
    )


def _load_episode_or_none(episode_dir: Path) -> EpisodeWire | None:
    try:
        data = json.loads((episode_dir / EPISODE_JSON_FILE_NAME).read_text("utf-8"))
        return episode_wire_from_dict(data)
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def _recall_corpus(
    row: EpisodeStorageIndexRowWire,
    episode: EpisodeWire,
    lesson_text: str,
    alias_episode_ids: list[str],
) -> str:
    parts: list[str] = [
        row.episode_id,
        " ".join(alias_episode_ids),
        row.title,
        row.changespec_name or "",
        " ".join(row.root_agent_names),
        " ".join(row.bead_ids),
        episode.title,
        episode.summary,
        lesson_text,
        _metadata_recall_terms(episode.metadata),
    ]
    for lesson in episode.lessons:
        parts.extend([lesson.kind, lesson.text])
    for source in episode.sources:
        parts.extend([source.kind, source.label or "", source.path])
    return "\n".join(parts)


def _alias_ids_for_row(
    row: EpisodeStorageIndexRowWire, alias_rows: list[Any]
) -> list[str]:
    return sorted(
        row_alias.alias_episode_id
        for row_alias in alias_rows
        if resolve_alias_episode_id(row_alias.canonical_episode_id, alias_rows)
        == row.episode_id
    )


def _lesson_text(
    row: EpisodeStorageIndexRowWire,
    episode: EpisodeWire,
    episode_dir: Path,
) -> str:
    for path in (Path(row.lesson_path), episode_dir / EPISODE_LESSON_FILE_NAME):
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            continue
    return render_lesson_markdown(episode)


def _recall_excerpt(
    episode: EpisodeWire,
    lesson_text: str,
    query_terms: set[str],
) -> str:
    for lesson in sorted(episode.lessons, key=lambda item: item.id):
        if query_terms & _token_set(lesson.text):
            return _truncate_excerpt(lesson.text)
    if query_terms & _token_set(episode.summary):
        return _truncate_excerpt(episode.summary)
    for line in lesson_text.splitlines():
        if query_terms & _token_set(line):
            return _truncate_excerpt(line)
    return ""


def _recall_lesson_cards(
    episode: EpisodeWire,
    query_terms: set[str],
) -> list[_EpisodeRecallLessonCard]:
    source_by_id = {source.id: source for source in episode.sources}
    cards: list[_EpisodeRecallLessonCard] = []
    for lesson in sorted(episode.lessons, key=lambda item: item.id):
        if not (query_terms & _token_set(lesson.text)):
            continue
        cards.append(
            _EpisodeRecallLessonCard(
                lesson_id=lesson.id,
                kind=lesson.kind,
                text=_truncate_excerpt(lesson.text),
                evidence=_recall_evidence_links(lesson.evidence_ids, source_by_id),
            )
        )
    return cards[:3]


def _recall_evidence_links(
    evidence_ids: list[str],
    source_by_id: dict[str, Any],
) -> list[_EpisodeRecallEvidence]:
    links: list[_EpisodeRecallEvidence] = []
    for source_id in sorted({item for item in evidence_ids if item}):
        source = source_by_id.get(source_id)
        if source is None:
            links.append(
                _EpisodeRecallEvidence(
                    source_id=source_id,
                    kind="unknown",
                    label=source_id,
                    path="",
                    exists=False,
                )
            )
            continue
        links.append(
            _EpisodeRecallEvidence(
                source_id=source.id,
                kind=source.kind,
                label=source.label or Path(source.path).name or source.path,
                path=source.path,
                exists=source.exists,
            )
        )
    return links[:5]


_TAG_METADATA_KEYS = {
    "keyword",
    "keywords",
    "label",
    "labels",
    "tag",
    "tags",
    "topic",
    "topics",
}
_LOOKUP_METADATA_KEYS = {
    "bead_id",
    "bead_ids",
    "changespec_name",
    "changespec_names",
}


def _metadata_recall_terms(metadata: dict[str, str]) -> str:
    parts: list[str] = []
    for key, value in sorted(metadata.items()):
        normalized = key.lower()
        if (
            normalized in _TAG_METADATA_KEYS
            or normalized in _LOOKUP_METADATA_KEYS
            or normalized.endswith("_tags")
            or normalized.endswith("_keywords")
        ):
            parts.append(value)
    return "\n".join(parts)


def _recall_sort_key(match: EpisodeRecallMatch) -> tuple[int, int, int, str]:
    return (
        -match.score,
        -_timestamp_sort_value(match.last_event_at),
        -_outcome_rank(match.outcome),
        match.episode_id,
    )


def _outcome_rank(outcome: str | None) -> int:
    if outcome is None:
        return 0
    values = {item.strip().lower() for item in outcome.split(",")}
    return 1 if values & _SUCCESS_OUTCOMES else 0


def _timestamp_sort_value(value: str | None) -> int:
    if not value:
        return 0
    digits = re.sub(r"\D", "", value)
    return int(digits[:14]) if digits else 0


def _token_set(text: str) -> set[str]:
    return set(_token_list(text))


def _token_list(text: str) -> list[str]:
    tokens: list[str] = []
    for match in _TOKEN_RE.finditer(text.lower()):
        token = match.group(0).strip("`'\".,;()[]{}<>")
        if token:
            tokens.append(token)
            for part in re.split(r"[._:/-]+", token):
                if part and part != token:
                    tokens.append(part)
    return tokens


def _truncate_excerpt(text: str) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= _EXCERPT_MAX_CHARS:
        return collapsed
    return collapsed[: _EXCERPT_MAX_CHARS - 3].rstrip() + "..."


__all__ = [
    "EpisodeRecallMatch",
    "recall_episode_rows",
]
