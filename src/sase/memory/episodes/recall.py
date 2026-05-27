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
class _EpisodeRecallMatch:
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

    def to_json_dict(self) -> dict[str, Any]:
        """Return a deterministic JSON-safe projection."""

        return {
            "episode_id": self.episode_id,
            "excerpt": self.excerpt,
            "last_event_at": self.last_event_at,
            "lesson_ids": self.lesson_ids,
            "lesson_path": self.lesson_path,
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
) -> list[_EpisodeRecallMatch]:
    """Return stable lexical recall matches for ``query`` over stored rows."""

    query_terms = _token_set(query)
    if not query_terms:
        raise ValueError("query must include at least one token")

    matches = [
        match
        for row in rows
        if (match := _recall_match(row, query_terms, projects_root=projects_root))
        is not None
    ]
    matches.sort(key=_recall_sort_key)
    return matches[:limit]


def _recall_match(
    row: EpisodeStorageIndexRowWire,
    query_terms: set[str],
    *,
    projects_root: Path | str | None,
) -> _EpisodeRecallMatch | None:
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
    token_counts = Counter(_token_list(_recall_corpus(row, episode, lesson_text)))
    matched_terms = sorted(term for term in query_terms if token_counts.get(term, 0))
    if not matched_terms:
        return None

    return _EpisodeRecallMatch(
        episode_id=row.episode_id,
        title=row.title,
        score=sum(token_counts[term] for term in matched_terms),
        matched_terms=matched_terms,
        excerpt=_recall_excerpt(episode, lesson_text, query_terms),
        lesson_ids=lesson_ids[:8],
        lesson_path=row.lesson_path,
        last_event_at=row.last_event_at,
        outcome=row.outcome,
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
) -> str:
    parts: list[str] = [
        row.episode_id,
        row.title,
        row.changespec_name or "",
        row.outcome or "",
        " ".join(row.root_agent_names),
        " ".join(row.bead_ids),
        episode.title,
        episode.summary,
        lesson_text,
    ]
    for lesson in episode.lessons:
        parts.extend(
            [lesson.id, lesson.kind, lesson.text, " ".join(lesson.evidence_ids)]
        )
    for source in episode.sources:
        parts.extend([source.id, source.kind, source.label or "", source.path])
    for key, value in sorted(episode.metadata.items()):
        parts.extend([key, value])
    return "\n".join(parts)


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


def _recall_sort_key(match: _EpisodeRecallMatch) -> tuple[int, int, int, str]:
    return (
        -match.score,
        -_outcome_rank(match.outcome),
        -_timestamp_sort_value(match.last_event_at),
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
    return tokens


def _truncate_excerpt(text: str) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= _EXCERPT_MAX_CHARS:
        return collapsed
    return collapsed[: _EXCERPT_MAX_CHARS - 3].rstrip() + "..."


__all__ = [
    "recall_episode_rows",
]
