"""Read-only event-readiness exports for stored episode evidence."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from sase.core.episode_wire import (
    EpisodeWire,
    episode_wire_from_dict,
)
from sase.memory.episodes.index import project_episodes_dir
from sase.memory.episodes.inventory import (
    EpisodeInventoryItem,
    EpisodeInventoryOrder,
    query_episode_inventory,
)
from sase.memory.episodes.storage import EPISODE_JSON_FILE_NAME

DEFAULT_EPISODE_EXPORT_LIMIT = 50
EPISODE_EXPORT_FACTOR_LIMIT = 10
EPISODE_EXPORT_SOURCE_LIMIT = 20
EPISODE_EXPORT_SAFETY_LIMIT = 20


@dataclass(frozen=True)
class _EpisodeExportResult:
    """A bounded, deterministic export payload for future event review."""

    project: str
    filters: dict[str, Any]
    order: str
    limit: int
    limits: dict[str, int]
    episodes: list[dict[str, Any]]

    def to_json_dict(self) -> dict[str, Any]:
        """Return a deterministic JSON-safe projection."""

        return {
            "episodes": self.episodes,
            "filters": self.filters,
            "limit": self.limit,
            "limits": self.limits,
            "order": self.order,
            "project": self.project,
            "writes_events": False,
        }


def export_episode_summaries(
    project: str,
    *,
    projects_root: Path | str | None = None,
    since: str | None = None,
    until: str | None = None,
    band: str | None = None,
    agent: str | None = None,
    changespec: str | None = None,
    bead: str | None = None,
    query: str | None = None,
    order: EpisodeInventoryOrder = "importance",
    limit: int | None = DEFAULT_EPISODE_EXPORT_LIMIT,
) -> _EpisodeExportResult:
    """Return compact episode summaries without writing event proposals."""

    effective_limit = limit or DEFAULT_EPISODE_EXPORT_LIMIT
    items = query_episode_inventory(
        project,
        projects_root=projects_root,
        since=since,
        until=until,
        band=band,
        agent=agent,
        changespec=changespec,
        bead=bead,
        query=query,
        order=order,
        limit=effective_limit,
    )
    episodes_dir = project_episodes_dir(project, projects_root=projects_root)
    episodes = [
        _episode_export_item(
            item, _load_episode_or_none(episodes_dir / item.row.episode_id)
        )
        for item in items
    ]
    return _EpisodeExportResult(
        project=project,
        filters={
            "agent": agent,
            "band": band,
            "bead": bead,
            "changespec": changespec,
            "query": query,
            "since": since,
            "until": until,
        },
        order=order,
        limit=effective_limit,
        limits={
            "importance_factors_per_episode": EPISODE_EXPORT_FACTOR_LIMIT,
            "safety_items_per_field": EPISODE_EXPORT_SAFETY_LIMIT,
            "source_refs_per_episode": EPISODE_EXPORT_SOURCE_LIMIT,
        },
        episodes=episodes,
    )


def _episode_export_item(
    item: EpisodeInventoryItem,
    episode: EpisodeWire | None,
) -> dict[str, Any]:
    row = item.row
    if episode is None:
        return {
            "agent_names": list(row.root_agent_names),
            "aliases": [alias.alias_episode_id for alias in item.aliases],
            "bead_ids": list(row.bead_ids),
            "changespec_name": row.changespec_name,
            "component_key": row.component_key,
            "episode_id": row.episode_id,
            "importance": {
                "band": row.importance_band,
                "factors": [],
                "score": row.importance_score,
            },
            "safety": {"warnings": item.warnings},
            "source_refs": [],
            "status": row.status,
            "summary": row.summary_excerpt,
            "time_span": {
                "first_event_at": row.first_event_at,
                "last_event_at": row.last_event_at,
            },
            "title": row.title,
        }

    return {
        "agent_names": list(row.root_agent_names),
        "aliases": [alias.alias_episode_id for alias in item.aliases],
        "bead_ids": list(row.bead_ids),
        "changespec_name": row.changespec_name,
        "component_key": episode.component_key,
        "component_root_kind": episode.component_root_kind,
        "counts": {
            "agents": row.agent_count,
            "chats": row.chat_count,
            "events": len(episode.events),
            "sources": len(episode.sources),
        },
        "episode_id": episode.episode_id,
        "importance": {
            "band": episode.importance_band,
            "factors": [
                {
                    "evidence_ids": sorted(factor.evidence_ids),
                    "kind": factor.kind,
                    "label": factor.label,
                    "score": factor.score,
                }
                for factor in sorted(
                    episode.importance_factors,
                    key=lambda factor: (-factor.score, factor.kind, factor.label),
                )[:EPISODE_EXPORT_FACTOR_LIMIT]
            ],
            "score": episode.importance_score,
        },
        "safety": _safety_export(episode),
        "source_refs": [
            {
                "exists": source.exists,
                "id": source.id,
                "kind": source.kind,
                "label": source.label,
                "path": source.path,
                "sha256": source.sha256,
            }
            for source in sorted(
                episode.sources,
                key=lambda source: (source.kind, source.path, source.id),
            )[:EPISODE_EXPORT_SOURCE_LIMIT]
        ],
        "status": episode.status,
        "summary": episode.summary,
        "time_span": {
            "first_event_at": row.first_event_at,
            "last_event_at": row.last_event_at,
        },
        "title": episode.title,
        "weak_refs": {
            "agent_families": sorted(set(episode.weak_refs.agent_families)),
            "bead_ids": sorted(set(episode.weak_refs.bead_ids)),
            "changespec_names": sorted(set(episode.weak_refs.changespec_names)),
            "metadata": {
                key: sorted(set(values))
                for key, values in sorted(episode.weak_refs.metadata.items())
            },
            "touched_paths": sorted(set(episode.weak_refs.touched_paths)),
        },
    }


def _safety_export(episode: EpisodeWire) -> dict[str, Any]:
    safety = episode.safety
    return {
        "private_or_missing_source_flags": sorted(
            set(safety.private_or_missing_source_flags)
        )[:EPISODE_EXPORT_SAFETY_LIMIT],
        "prompt_injection_phrase_hits": sorted(
            set(safety.prompt_injection_phrase_hits)
        )[:EPISODE_EXPORT_SAFETY_LIMIT],
        "redaction_hits": sorted(set(safety.redaction_hits))[
            :EPISODE_EXPORT_SAFETY_LIMIT
        ],
        "untrusted_transcript_text": safety.untrusted_transcript_text,
        "warnings": sorted(set(safety.warnings))[:EPISODE_EXPORT_SAFETY_LIMIT],
    }


def _load_episode_or_none(episode_dir: Path) -> EpisodeWire | None:
    try:
        data = json.loads(
            (episode_dir / EPISODE_JSON_FILE_NAME).read_text(encoding="utf-8")
        )
        return episode_wire_from_dict(data)
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


__all__ = [
    "DEFAULT_EPISODE_EXPORT_LIMIT",
    "export_episode_summaries",
]
