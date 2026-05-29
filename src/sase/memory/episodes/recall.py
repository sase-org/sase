"""Deterministic lexical recall for stored episodic-memory records."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
import json
from pathlib import Path

from sase.core.episode_wire import (
    EpisodeStorageIndexRowWire,
    EpisodeWire,
    episode_wire_from_dict,
)
from sase.memory.episodes._recall_cards import (
    is_v2_evidence_episode,
    recall_evidence_cards,
    recall_lesson_cards,
)
from sase.memory.episodes._recall_text import (
    importance_recall_terms,
    metadata_recall_terms,
    recall_excerpt,
    recall_sort_key,
    safety_recall_terms,
    token_list,
    token_set,
    weak_refs_recall_terms,
)
from sase.memory.episodes._recall_types import EpisodeRecallMatch
from sase.memory.episodes.identity import (
    EpisodeAliasIndexRow,
    read_episode_alias_rows,
    resolve_alias_episode_id,
)
from sase.memory.episodes.index import project_episodes_dir
from sase.memory.episodes.render import render_lesson_markdown
from sase.memory.episodes.storage import (
    EPISODE_JSON_FILE_NAME,
    EPISODE_LESSON_FILE_NAME,
)


def recall_episode_rows(
    rows: Iterable[EpisodeStorageIndexRowWire],
    query: str,
    *,
    projects_root: Path | str | None = None,
    limit: int = 10,
) -> list[EpisodeRecallMatch]:
    """Return stable lexical recall matches for ``query`` over stored rows."""

    query_terms = token_set(query)
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
    matches.sort(key=recall_sort_key)
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
        if query_terms & token_set(lesson.text)
    ]
    token_counts = Counter(
        token_list(_recall_corpus(row, episode, lesson_text, alias_episode_ids))
    )
    matched_terms = sorted(term for term in query_terms if token_counts.get(term, 0))
    if not matched_terms:
        return None

    is_v2 = is_v2_evidence_episode(episode)
    lesson_cards = [] if is_v2 else recall_lesson_cards(episode, query_terms)
    evidence_cards = recall_evidence_cards(episode, query_terms) if is_v2 else []
    return EpisodeRecallMatch(
        episode_id=row.episode_id,
        title=row.title,
        score=sum(token_counts[term] for term in matched_terms),
        matched_terms=matched_terms,
        excerpt=recall_excerpt(episode, lesson_text, query_terms),
        lesson_ids=lesson_ids[:8],
        lesson_path=row.lesson_path,
        last_event_at=row.last_event_at,
        outcome=row.outcome,
        lessons=lesson_cards,
        evidence_cards=evidence_cards,
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
        row.component_key,
        row.status,
        row.summary_excerpt,
        row.importance_band,
        row.changespec_name or "",
        " ".join(row.root_agent_names),
        " ".join(row.bead_ids),
        episode.title,
        episode.summary,
        lesson_text,
        metadata_recall_terms(episode.metadata),
        weak_refs_recall_terms(episode),
        importance_recall_terms(episode),
        safety_recall_terms(episode),
    ]
    for lesson in episode.lessons:
        parts.extend([lesson.kind, lesson.text])
    for event in episode.events:
        parts.extend([event.kind, event.title, event.description or ""])
    for node in episode.nodes:
        parts.extend(
            [node.kind, node.label or "", metadata_recall_terms(node.metadata)]
        )
    for source in episode.sources:
        parts.extend([source.kind, source.label or "", source.path])
    return "\n".join(parts)


def _alias_ids_for_row(
    row: EpisodeStorageIndexRowWire,
    alias_rows: list[EpisodeAliasIndexRow],
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
    paths = [Path(path) for path in (row.lesson_path, row.legacy_lesson_path) if path]
    paths.append(episode_dir / EPISODE_LESSON_FILE_NAME)
    for path in paths:
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            continue
    if not episode.lessons:
        return ""
    return render_lesson_markdown(episode)


__all__ = [
    "EpisodeRecallMatch",
    "recall_episode_rows",
]
