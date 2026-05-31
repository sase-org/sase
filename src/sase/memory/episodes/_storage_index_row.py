"""Index-row projection for stored episodes."""

from __future__ import annotations

from pathlib import Path

from sase.core.episode_wire import (
    EPISODE_WIRE_SCHEMA_VERSION,
    EpisodeStorageIndexRowWire,
    EpisodeWire,
)


def build_episode_index_row(
    episode: EpisodeWire,
    *,
    lesson_path: Path | None,
    content_sha256: str,
) -> EpisodeStorageIndexRowWire:
    """Build the deterministic index row for a stored episode."""

    event_timestamps = sorted(
        {event.timestamp for event in episode.events if event.timestamp}
    )
    return EpisodeStorageIndexRowWire(
        schema_version=EPISODE_WIRE_SCHEMA_VERSION,
        episode_id=episode.episode_id,
        project=episode.project,
        title=episode.title,
        component_key=_component_key(episode),
        status=episode.status or "active",
        summary_excerpt=_summary_excerpt(episode.summary),
        root_agent_names=_root_agent_names(episode),
        changespec_name=_changespec_name(episode),
        bead_ids=_bead_ids(episode),
        outcome=_outcome(episode),
        first_event_at=event_timestamps[0] if event_timestamps else None,
        last_event_at=event_timestamps[-1] if event_timestamps else None,
        importance_score=episode.importance_score,
        importance_band=episode.importance_band or "unknown",
        source_count=len(episode.sources),
        chat_count=_chat_count(episode),
        agent_count=_agent_count(episode),
        lesson_path=(
            str(lesson_path.resolve(strict=False)) if lesson_path is not None else ""
        ),
        legacy_lesson_path=(
            str(lesson_path.resolve(strict=False))
            if lesson_path is not None
            and (
                episode.schema_version < EPISODE_WIRE_SCHEMA_VERSION
                or episode.status == "legacy"
            )
            else None
        ),
        content_sha256=content_sha256,
    )


def _root_agent_names(episode: EpisodeWire) -> list[str]:
    explicit = _metadata_list(episode.metadata.get("root_agent_names")) or (
        _metadata_list(episode.metadata.get("root_agents"))
    )
    if explicit:
        return explicit
    names = {
        node.label
        for node in episode.nodes
        if node.kind == "agent_run" and node.label is not None and node.label
    }
    return sorted(names)


def _component_key(episode: EpisodeWire) -> str:
    return (
        episode.component_key
        or episode.metadata.get("component_key")
        or episode.root_source_id
    )


def _summary_excerpt(summary: str) -> str:
    collapsed = " ".join(summary.split())
    if len(collapsed) <= 240:
        return collapsed
    return collapsed[:237].rstrip() + "..."


def _chat_count(episode: EpisodeWire) -> int:
    explicit = episode.metadata.get("chat_count")
    if explicit and explicit.isdigit():
        return int(explicit)
    return sum(1 for node in episode.nodes if node.kind == "chat")


def _agent_count(episode: EpisodeWire) -> int:
    explicit = episode.metadata.get("agent_count") or episode.metadata.get(
        "agent_record_count"
    )
    if explicit and explicit.isdigit():
        return int(explicit)
    return sum(1 for node in episode.nodes if node.kind == "agent_run")


def _changespec_name(episode: EpisodeWire) -> str | None:
    if episode.weak_refs.changespec_names:
        return ", ".join(sorted(set(episode.weak_refs.changespec_names)))
    explicit = episode.metadata.get("changespec_name")
    if explicit:
        return explicit
    names = {
        node.metadata.get("name") or node.label
        for node in episode.nodes
        if node.kind == "changespec"
    }
    clean = sorted({name for name in names if name})
    return ", ".join(clean) if clean else None


def _bead_ids(episode: EpisodeWire) -> list[str]:
    if episode.weak_refs.bead_ids:
        return sorted(set(episode.weak_refs.bead_ids))
    explicit = _metadata_list(episode.metadata.get("bead_ids"))
    if explicit:
        return explicit
    bead_ids = {
        node.metadata.get("id") or node.label
        for node in episode.nodes
        if node.kind == "bead"
    }
    return sorted({bead_id for bead_id in bead_ids if bead_id})


def _outcome(episode: EpisodeWire) -> str | None:
    explicit = episode.metadata.get("outcome")
    if explicit:
        return explicit
    outcomes = sorted(
        {
            node.metadata["outcome"]
            for node in episode.nodes
            if node.kind == "agent_run" and node.metadata.get("outcome")
        }
    )
    return ", ".join(outcomes) if outcomes else None


def _metadata_list(value: str | None) -> list[str]:
    if not value:
        return []
    return sorted({item.strip() for item in value.split(",") if item.strip()})
