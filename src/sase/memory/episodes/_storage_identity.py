"""Episode identity resolution for storage writes."""

from __future__ import annotations

from pathlib import Path

from sase.core.episode_wire import EPISODE_WIRE_SCHEMA_VERSION, EpisodeWire
from sase.memory.episodes._storage_files import load_stored_episode_or_none
from sase.memory.episodes.identity import (
    EPISODE_IDENTITY_SCHEMA_VERSION,
    EpisodeAliasIndexRow,
    EpisodeMemberIndexRow,
    episode_member_keys,
    member_kind_from_key,
    merge_episode_alias_rows,
    merge_episode_member_rows,
    resolve_alias_episode_id,
    write_episode_alias_rows_unlocked,
    write_episode_member_rows_unlocked,
)


def resolve_episode_write_identity(
    episode: EpisodeWire,
    *,
    episodes_dir: Path,
    member_rows: list[EpisodeMemberIndexRow],
    alias_rows: list[EpisodeAliasIndexRow],
) -> tuple[str, list[EpisodeAliasIndexRow]]:
    member_keys = set(episode_member_keys(episode))
    desired_id = resolve_alias_episode_id(episode.episode_id, alias_rows)
    existing_ids = sorted(
        {
            resolve_alias_episode_id(row.canonical_episode_id, alias_rows)
            for row in member_rows
            if row.member_key in member_keys
        }
    )
    if _is_v2_component_episode(episode):
        existing_ids = sorted(
            {
                *existing_ids,
                *_stored_path_dependent_v2_episode_ids_for_member_keys(
                    episodes_dir,
                    member_keys,
                    alias_rows,
                ),
            }
        )
    canonical_id = _choose_canonical_episode_id(
        episode,
        desired_id=desired_id,
        existing_ids=existing_ids,
        episodes_dir=episodes_dir,
    )
    aliases = _alias_rows_for_identity_resolution(
        episode,
        canonical_id=canonical_id,
        desired_id=desired_id,
        existing_ids=existing_ids,
        episodes_dir=episodes_dir,
    )
    return canonical_id, aliases


def member_rows_for_episode(episode: EpisodeWire) -> list[EpisodeMemberIndexRow]:
    return [
        EpisodeMemberIndexRow(
            schema_version=EPISODE_IDENTITY_SCHEMA_VERSION,
            project=episode.project,
            member_key=member_key,
            member_kind=member_kind_from_key(member_key),
            canonical_episode_id=episode.episode_id,
        )
        for member_key in episode_member_keys(episode)
    ]


def write_identity_members_if_needed(
    episodes_dir: Path,
    existing_rows: list[EpisodeMemberIndexRow],
    rows_to_add: list[EpisodeMemberIndexRow],
) -> bool:
    if not rows_to_add and not (episodes_dir / "members.jsonl").exists():
        return False
    return write_episode_member_rows_unlocked(
        episodes_dir,
        merge_episode_member_rows(existing_rows, rows_to_add),
    )


def write_identity_aliases_if_needed(
    episodes_dir: Path,
    existing_rows: list[EpisodeAliasIndexRow],
    rows_to_add: list[EpisodeAliasIndexRow],
) -> bool:
    if not rows_to_add and not (episodes_dir / "aliases.jsonl").exists():
        return False
    return write_episode_alias_rows_unlocked(
        episodes_dir,
        merge_episode_alias_rows(existing_rows, rows_to_add),
    )


def episode_writes_lesson(episode: EpisodeWire) -> bool:
    return not _is_v2_component_episode(episode)


def _choose_canonical_episode_id(
    episode: EpisodeWire,
    *,
    desired_id: str,
    existing_ids: list[str],
    episodes_dir: Path,
) -> str:
    if not existing_ids:
        return desired_id
    if desired_id in existing_ids:
        return desired_id
    if _is_v2_component_episode(episode) and all(
        _stored_episode_can_yield_to_logical_v2(episodes_dir, episode_id)
        for episode_id in existing_ids
    ):
        return desired_id
    if len(existing_ids) == 1:
        existing_id = existing_ids[0]
        if _is_v2_component_episode(episode) and _stored_episode_is_legacy(
            episodes_dir,
            existing_id,
        ):
            return desired_id
        return existing_id
    return sorted(
        existing_ids,
        key=lambda episode_id: _canonical_priority(
            episode_id,
            episodes_dir=episodes_dir,
        ),
    )[0]


def _canonical_priority(
    episode_id: str,
    *,
    episodes_dir: Path,
) -> tuple[str, str, str]:
    stored = load_stored_episode_or_none(episodes_dir, episode_id)
    if stored is None:
        return ("", "", episode_id)
    root_time = (
        stored.metadata.get("component_root_timestamp")
        or _first_event_timestamp(stored)
        or ""
    )
    return (root_time, stored.component_key or "", episode_id)


def _alias_rows_for_identity_resolution(
    episode: EpisodeWire,
    *,
    canonical_id: str,
    desired_id: str,
    existing_ids: list[str],
    episodes_dir: Path,
) -> list[EpisodeAliasIndexRow]:
    aliases: dict[str, EpisodeAliasIndexRow] = {}
    if episode.episode_id != canonical_id:
        aliases[episode.episode_id] = EpisodeAliasIndexRow(
            schema_version=EPISODE_IDENTITY_SCHEMA_VERSION,
            project=episode.project,
            alias_episode_id=episode.episode_id,
            canonical_episode_id=canonical_id,
            reason="existing_member",
        )
    if desired_id != canonical_id:
        aliases[desired_id] = EpisodeAliasIndexRow(
            schema_version=EPISODE_IDENTITY_SCHEMA_VERSION,
            project=episode.project,
            alias_episode_id=desired_id,
            canonical_episode_id=canonical_id,
            reason="existing_member",
        )
    for existing_id in existing_ids:
        if existing_id == canonical_id:
            continue
        reason = _alias_reason_for_existing_episode(episodes_dir, existing_id)
        aliases[existing_id] = EpisodeAliasIndexRow(
            schema_version=EPISODE_IDENTITY_SCHEMA_VERSION,
            project=episode.project,
            alias_episode_id=existing_id,
            canonical_episode_id=canonical_id,
            reason=reason,
        )
    return sorted(aliases.values(), key=lambda row: row.alias_episode_id)


def _is_v2_component_episode(episode: EpisodeWire) -> bool:
    return bool(episode.component_key) and not _is_legacy_episode(episode)


def _stored_path_dependent_v2_episode_ids_for_member_keys(
    episodes_dir: Path,
    member_keys: set[str],
    alias_rows: list[EpisodeAliasIndexRow],
) -> list[str]:
    if not member_keys or not episodes_dir.is_dir():
        return []
    episode_ids: set[str] = set()
    for child in sorted(episodes_dir.iterdir(), key=lambda path: path.name):
        if not child.is_dir():
            continue
        stored = load_stored_episode_or_none(episodes_dir, child.name)
        if stored is None or not _is_path_dependent_v2_component_episode(stored):
            continue
        if not (set(episode_member_keys(stored)) & member_keys):
            continue
        episode_ids.add(resolve_alias_episode_id(stored.episode_id, alias_rows))
    return sorted(episode_ids)


def _stored_episode_can_yield_to_logical_v2(
    episodes_dir: Path,
    episode_id: str,
) -> bool:
    return _stored_episode_is_legacy(
        episodes_dir,
        episode_id,
    ) or _stored_episode_is_path_dependent_v2_component(episodes_dir, episode_id)


def _alias_reason_for_existing_episode(episodes_dir: Path, episode_id: str) -> str:
    if _stored_episode_is_legacy(episodes_dir, episode_id):
        return "v1_migration"
    if _stored_episode_is_path_dependent_v2_component(episodes_dir, episode_id):
        return "component_key_migration"
    return "late_bridge"


def _stored_episode_is_path_dependent_v2_component(
    episodes_dir: Path,
    episode_id: str,
) -> bool:
    stored = load_stored_episode_or_none(episodes_dir, episode_id)
    return stored is not None and _is_path_dependent_v2_component_episode(stored)


def _is_path_dependent_v2_component_episode(episode: EpisodeWire) -> bool:
    return _is_v2_component_episode(episode) and _component_key_is_path_dependent_v2(
        episode.component_key
    )


def _component_key_is_path_dependent_v2(component_key: str) -> bool:
    if component_key.startswith("component/chat/"):
        return Path(component_key.removeprefix("component/chat/")).is_absolute()
    if not component_key.startswith("component/artifact/"):
        return False
    parts = component_key.split("/")
    if len(parts) < 5:
        return False
    return Path("/".join(parts[4:])).is_absolute()


def _stored_episode_is_legacy(episodes_dir: Path, episode_id: str) -> bool:
    stored = load_stored_episode_or_none(episodes_dir, episode_id)
    return stored is not None and _is_legacy_episode(stored)


def _is_legacy_episode(episode: EpisodeWire) -> bool:
    return episode.schema_version < EPISODE_WIRE_SCHEMA_VERSION or (
        episode.status == "legacy"
    )


def _first_event_timestamp(episode: EpisodeWire) -> str | None:
    timestamps = sorted(
        {event.timestamp for event in episode.events if event.timestamp}
    )
    return timestamps[0] if timestamps else None
