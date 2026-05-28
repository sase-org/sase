"""Deterministic episode builder for collected source graphs."""

from __future__ import annotations

from dataclasses import replace

from sase.core.episode_facade import generate_episode_id, generate_v2_episode_id
from sase.core.episode_wire import (
    EPISODE_WIRE_SCHEMA_VERSION,
    EpisodeImportanceFactorWire,
    EpisodeLessonWire,
    EpisodeWire,
)
from sase.memory.episodes._builder_derivation import (
    derive_events,
    derive_metadata,
    derive_safety,
    derive_summary,
    derive_v2_summary,
    derive_weak_refs,
    is_v2_component_draft,
)
from sase.memory.episodes._builder_lessons import derive_lessons
from sase.memory.episodes.collector import EpisodeDraft
from sase.memory.episodes.importance import (
    EpisodeImportanceScore,
    score_episode_importance,
)
from sase.memory.episodes.source_refs import sort_source_refs
from sase.memory.episodes.title import derive_episode_goal, derive_episode_title


def build_episode(draft: EpisodeDraft) -> EpisodeWire:
    """Convert a collected draft graph into a canonical episode wire record."""

    sources = sort_source_refs(draft.sources)
    goal = derive_episode_goal(draft)
    title = derive_episode_title(draft)
    events = derive_events(draft)
    weak_refs = derive_weak_refs(draft)
    safety = derive_safety(draft)
    importance: EpisodeImportanceScore | None
    lessons: list[EpisodeLessonWire]
    if is_v2_component_draft(draft):
        lessons = []
        summary = derive_v2_summary(draft, goal, events, weak_refs, safety)
        importance = score_episode_importance(
            draft,
            events=events,
            weak_refs=weak_refs,
        )
    else:
        lessons = derive_lessons(draft, goal)
        summary = derive_summary(draft, goal, lessons)
        importance = None
    metadata = derive_metadata(
        draft,
        events,
        lessons,
        weak_refs=weak_refs,
        safety=safety,
        importance_score=importance.score if importance is not None else 0,
        importance_band=importance.band if importance is not None else "unknown",
    )
    component_key = draft.metadata.get("component_key", "")
    episode_id = (
        generate_v2_episode_id(draft.project, component_key)
        if component_key
        else generate_episode_id(draft.project, draft.root_source_id, sources)
    )
    return EpisodeWire(
        schema_version=EPISODE_WIRE_SCHEMA_VERSION,
        episode_id=episode_id,
        project=draft.project,
        title=title,
        summary=summary,
        root_source_id=draft.root_source_id,
        component_key=component_key,
        component_root_kind=draft.metadata.get("component_root_kind", ""),
        status="active" if component_key else "legacy",
        importance_score=importance.score if importance is not None else 0,
        importance_band=importance.band if importance is not None else "unknown",
        importance_factors=(
            _wire_safe_importance_factors(importance) if importance is not None else []
        ),
        safety=safety,
        weak_refs=weak_refs,
        sources=sources,
        nodes=sorted(draft.nodes, key=lambda node: node.id),
        edges=sorted(draft.edges, key=lambda edge: edge.id),
        events=events,
        lessons=lessons,
        metadata=metadata,
    )


def _wire_safe_importance_factors(
    importance: EpisodeImportanceScore,
) -> list[EpisodeImportanceFactorWire]:
    return [_wire_safe_importance_factor(factor) for factor in importance.factors]


def _wire_safe_importance_factor(
    factor: EpisodeImportanceFactorWire,
) -> EpisodeImportanceFactorWire:
    if factor.score >= 0:
        return factor
    metadata = {**factor.metadata, "penalty_score": str(factor.score)}
    return replace(factor, score=0, metadata=dict(sorted(metadata.items())))


__all__ = [
    "build_episode",
]
