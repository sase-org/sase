"""Atomic project episode storage."""

from __future__ import annotations

from dataclasses import dataclass, replace
import fcntl
from pathlib import Path
import shutil
import tempfile

from sase.core.episode_wire import EpisodeStorageIndexRowWire, EpisodeWire
from sase.memory.episodes._storage_files import (
    EPISODE_JSON_FILE_NAME,
    EPISODE_LESSON_FILE_NAME,
    EPISODE_SOURCES_FILE_NAME,
    fsync_dir,
    gc_corrupt_episode_temp_dirs_unlocked,
    replace_changed_files,
    write_text_and_fsync,
)
from sase.memory.episodes._storage_identity import (
    episode_writes_lesson,
    member_rows_for_episode,
    resolve_episode_write_identity,
    write_identity_aliases_if_needed,
    write_identity_members_if_needed,
)
from sase.memory.episodes._storage_index_row import build_episode_index_row
from sase.memory.episodes._storage_projection import (
    episode_content_sha256,
    episode_file_payloads,
)
from sase.memory.episodes.identity import (
    read_episode_alias_rows_unlocked,
    read_episode_member_rows_unlocked,
)
from sase.memory.episodes.index import (
    episode_index_lock_path,
    episode_index_path,
    project_episodes_dir,
    upsert_episode_index_row_unlocked,
)
from sase.memory.locks import locked_file


@dataclass(frozen=True)
class EpisodeWriteResult:
    """Result from a project episode write."""

    episode_id: str
    project: str
    episode_dir: Path
    episode_json_path: Path
    lesson_path: Path
    sources_path: Path
    index_path: Path
    index_row: EpisodeStorageIndexRowWire
    changed: bool


def write_project_episode(
    episode: EpisodeWire,
    *,
    lesson_markdown: str | None = None,
    projects_root: Path | str | None = None,
) -> EpisodeWriteResult:
    """Persist an episode and update its project index.

    ``episode.json`` remains canonical. ``lesson.md``, ``sources.jsonl``, and
    ``index.jsonl`` are deterministic projections that can be rebuilt.
    """

    index_path = episode_index_path(episode.project, projects_root=projects_root)
    with locked_file(episode_index_lock_path(index_path), fcntl.LOCK_EX):
        return write_project_episode_unlocked(
            episode,
            lesson_markdown=lesson_markdown,
            projects_root=projects_root,
        )


def write_project_episode_unlocked(
    episode: EpisodeWire,
    *,
    lesson_markdown: str | None = None,
    projects_root: Path | str | None = None,
) -> EpisodeWriteResult:
    """Persist an episode while the caller holds the project episode lock."""

    if not episode.project.strip():
        raise ValueError("episode project must not be empty")
    if not episode.episode_id.strip():
        raise ValueError("episode id must not be empty")

    episodes_dir = project_episodes_dir(episode.project, projects_root=projects_root)
    index_path = episode_index_path(episode.project, projects_root=projects_root)
    episodes_dir.mkdir(parents=True, exist_ok=True)
    gc_corrupt_episode_temp_dirs_unlocked(episodes_dir)
    existing_member_rows = read_episode_member_rows_unlocked(episodes_dir)
    existing_alias_rows = read_episode_alias_rows_unlocked(episodes_dir)
    canonical_episode_id, alias_rows_to_add = resolve_episode_write_identity(
        episode,
        episodes_dir=episodes_dir,
        member_rows=existing_member_rows,
        alias_rows=existing_alias_rows,
    )
    stored_episode = (
        episode
        if canonical_episode_id == episode.episode_id
        else replace(episode, episode_id=canonical_episode_id)
    )
    target_dir = episodes_dir / stored_episode.episode_id
    payloads = episode_file_payloads(
        stored_episode,
        lesson_markdown=lesson_markdown,
    )
    content_sha256 = episode_content_sha256(payloads)
    index_row = build_episode_index_row(
        stored_episode,
        lesson_path=(
            target_dir / EPISODE_LESSON_FILE_NAME
            if episode_writes_lesson(stored_episode)
            else None
        ),
        content_sha256=content_sha256,
    )
    temp_dir = Path(
        tempfile.mkdtemp(
            prefix=f".{stored_episode.episode_id}.tmp.",
            dir=episodes_dir,
        )
    )
    try:
        for file_name, content in payloads.items():
            write_text_and_fsync(temp_dir / file_name, content)
        files_changed = replace_changed_files(target_dir, temp_dir, payloads)
        index_changed = upsert_episode_index_row_unlocked(index_path, index_row)
        member_rows_to_add = member_rows_for_episode(stored_episode)
        members_changed = write_identity_members_if_needed(
            episodes_dir,
            existing_member_rows,
            member_rows_to_add,
        )
        aliases_changed = write_identity_aliases_if_needed(
            episodes_dir,
            existing_alias_rows,
            alias_rows_to_add,
        )
        fsync_dir(target_dir)
        fsync_dir(episodes_dir)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    return EpisodeWriteResult(
        episode_id=stored_episode.episode_id,
        project=stored_episode.project,
        episode_dir=target_dir,
        episode_json_path=target_dir / EPISODE_JSON_FILE_NAME,
        lesson_path=target_dir / EPISODE_LESSON_FILE_NAME,
        sources_path=target_dir / EPISODE_SOURCES_FILE_NAME,
        index_path=index_path,
        index_row=index_row,
        changed=files_changed or index_changed or members_changed or aliases_changed,
    )


def gc_corrupt_episode_temp_dirs(
    project: str,
    *,
    projects_root: Path | str | None = None,
) -> list[Path]:
    """Remove only storage temp directories from a project episode store."""

    episodes_dir = project_episodes_dir(project, projects_root=projects_root)
    index_path = episode_index_path(project, projects_root=projects_root)
    with locked_file(episode_index_lock_path(index_path), fcntl.LOCK_EX):
        return gc_corrupt_episode_temp_dirs_unlocked(episodes_dir)


__all__ = [
    "EPISODE_JSON_FILE_NAME",
    "EPISODE_LESSON_FILE_NAME",
    "EPISODE_SOURCES_FILE_NAME",
    "EpisodeWriteResult",
    "gc_corrupt_episode_temp_dirs",
    "write_project_episode",
    "write_project_episode_unlocked",
]
