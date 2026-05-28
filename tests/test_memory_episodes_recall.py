from __future__ import annotations

import hashlib
from pathlib import Path

from sase.core.episode_wire import (
    EPISODE_WIRE_SCHEMA_VERSION,
    EpisodeEventWire,
    EpisodeImportanceFactorWire,
    EpisodeLessonWire,
    EpisodeNodeWire,
    EpisodeSafetyWire,
    EpisodeSourceRefWire,
    EpisodeWeakRefsWire,
    EpisodeWire,
)
from sase.memory.episodes.index import read_episode_index
from sase.memory.episodes.recall import recall_episode_rows
from sase.memory.episodes.storage import write_project_episode


def test_recall_returns_lesson_cards_with_evidence_links(tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    source = _source(tmp_path, "retry-feedback.md", "retry feedback source\n")
    episode = _episode(
        "ep-evidence",
        source,
        title="Retry Feedback Episode",
        summary="Captured retry feedback.",
        lessons=[
            EpisodeLessonWire(
                id="lesson-feedback",
                kind="feedback",
                text="Retry feedback should link evidence sources.",
                evidence_ids=[source.id],
            )
        ],
    )
    write_project_episode(episode, projects_root=projects_root)

    matches = recall_episode_rows(
        read_episode_index("proj", projects_root=projects_root),
        "retry feedback",
        projects_root=projects_root,
    )

    assert [match.episode_id for match in matches] == ["ep-evidence"]
    payload = matches[0].to_json_dict()
    assert payload["lessons"][0]["lesson_id"] == "lesson-feedback"
    assert payload["lessons"][0]["evidence"][0]["source_id"] == source.id
    assert payload["lessons"][0]["evidence"][0]["path"] == source.path


def test_recall_does_not_match_outcome_only_text(tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    source = _source(tmp_path, "planning.md", "planning source\n")
    episode = _episode(
        "ep-outcome",
        source,
        title="Planning Episode",
        summary="Captured planning context.",
        outcome="completed",
        lessons=[
            EpisodeLessonWire(
                id="lesson-planning",
                kind="implementation",
                text="Planning context was recorded.",
                evidence_ids=[source.id],
            )
        ],
    )
    write_project_episode(
        episode,
        lesson_markdown="# Planning Episode\n\nPlanning context only.\n",
        projects_root=projects_root,
    )

    assert (
        recall_episode_rows(
            read_episode_index("proj", projects_root=projects_root),
            "completed",
            projects_root=projects_root,
        )
        == []
    )


def test_recall_matches_v2_episode_without_lesson_records(tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    source = _source(tmp_path, "component-source.md", "source-linked evidence\n")
    episode = EpisodeWire(
        schema_version=EPISODE_WIRE_SCHEMA_VERSION,
        episode_id="ep-v2-recall",
        project="proj",
        title="Connected Retry Evidence",
        summary="Factual component summary for source-linked retry recovery.",
        root_source_id=source.id,
        component_key="component/retry",
        component_root_kind="artifact",
        importance_score=72,
        importance_band="high",
        importance_factors=[
            EpisodeImportanceFactorWire(
                kind="retry_recovered",
                label="Retry or failed attempt later succeeded",
                score=18,
                evidence_ids=[source.id],
            )
        ],
        safety=EpisodeSafetyWire(warnings=["missing-source:src-missing"]),
        weak_refs=EpisodeWeakRefsWire(
            changespec_names=["episode-v2-cl"],
            bead_ids=["sase-48.4"],
            touched_paths=["sdd/research/episode_v2.md"],
        ),
        sources=[source],
        nodes=[],
        edges=[],
        events=[
            EpisodeEventWire(
                id="event-retry",
                kind="retry",
                title="Retry recovered",
                timestamp="2026-05-26T12:00:00Z",
                evidence_ids=[source.id],
            )
        ],
        lessons=[],
    )
    write_project_episode(episode, projects_root=projects_root)

    matches = recall_episode_rows(
        read_episode_index("proj", projects_root=projects_root),
        "retry recovered sase-48.4 episode-v2-cl",
        projects_root=projects_root,
    )

    assert [match.episode_id for match in matches] == ["ep-v2-recall"]
    payload = matches[0].to_json_dict()
    assert payload["lesson_ids"] == []
    assert payload["lesson_path"] == ""
    assert payload["lessons"] == []
    assert payload["excerpt"] in {
        "Factual component summary for source-linked retry recovery.",
        "Retry recovered",
        "Retry or failed attempt later succeeded",
    }


def test_recall_uses_recency_before_outcome_as_tiebreaker(tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    old_source = _source(tmp_path, "old.md", "old source\n")
    new_source = _source(tmp_path, "new.md", "new source\n")
    lesson_text = "Cache invalidation was recorded."
    old_episode = _episode(
        "ep-old",
        old_source,
        title="Cache Episode Old",
        summary="Cache topic.",
        outcome="completed",
        last_event_at="2026-05-25T12:00:00Z",
        lessons=[
            EpisodeLessonWire(
                id="lesson-cache-old",
                kind="implementation",
                text=lesson_text,
                evidence_ids=[old_source.id],
            )
        ],
    )
    new_episode = _episode(
        "ep-new",
        new_source,
        title="Cache Episode New",
        summary="Cache topic.",
        outcome="failed",
        last_event_at="2026-05-26T12:00:00Z",
        lessons=[
            EpisodeLessonWire(
                id="lesson-cache-new",
                kind="implementation",
                text=lesson_text,
                evidence_ids=[new_source.id],
            )
        ],
    )
    write_project_episode(old_episode, projects_root=projects_root)
    write_project_episode(new_episode, projects_root=projects_root)

    matches = recall_episode_rows(
        read_episode_index("proj", projects_root=projects_root),
        "cache",
        projects_root=projects_root,
    )

    assert [match.episode_id for match in matches] == ["ep-new", "ep-old"]


def _source(tmp_path: Path, name: str, content: str) -> EpisodeSourceRefWire:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    data = content.encode("utf-8")
    return EpisodeSourceRefWire(
        id=f"src-{path.stem}",
        kind="chat",
        path=str(path.resolve(strict=False)),
        label=name,
        exists=True,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )


def _episode(
    episode_id: str,
    source: EpisodeSourceRefWire,
    *,
    title: str,
    summary: str,
    lessons: list[EpisodeLessonWire],
    outcome: str = "completed",
    last_event_at: str = "2026-05-26T12:00:00Z",
) -> EpisodeWire:
    return EpisodeWire(
        schema_version=EPISODE_WIRE_SCHEMA_VERSION,
        episode_id=episode_id,
        project="proj",
        title=title,
        summary=summary,
        root_source_id=source.id,
        sources=[source],
        nodes=[
            EpisodeNodeWire(
                id=f"node-{episode_id}",
                kind="agent_run",
                label=f"agent-{episode_id}",
                metadata={"outcome": outcome},
            )
        ],
        edges=[],
        events=[
            EpisodeEventWire(
                id=f"event-{episode_id}",
                kind="agent_finish",
                title="Agent finished",
                timestamp=last_event_at,
                evidence_ids=[source.id],
            )
        ],
        lessons=lessons,
    )
