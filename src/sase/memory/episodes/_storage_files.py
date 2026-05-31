"""Filesystem helpers for episode storage."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil

from sase.core.episode_wire import EpisodeWire, episode_wire_from_dict

EPISODE_JSON_FILE_NAME = "episode.json"
EPISODE_LESSON_FILE_NAME = "lesson.md"
EPISODE_SOURCES_FILE_NAME = "sources.jsonl"


def load_stored_episode_or_none(
    episodes_dir: Path,
    episode_id: str,
) -> EpisodeWire | None:
    try:
        data = json.loads(
            (episodes_dir / episode_id / EPISODE_JSON_FILE_NAME).read_text(
                encoding="utf-8"
            )
        )
        return episode_wire_from_dict(data)
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def replace_changed_files(
    target_dir: Path,
    temp_dir: Path,
    payloads: dict[str, str],
) -> bool:
    target_dir.mkdir(parents=True, exist_ok=True)
    changed = False
    for file_name, content in payloads.items():
        target = target_dir / file_name
        if _read_text_or_none(target) == content:
            continue
        os.replace(temp_dir / file_name, target)
        changed = True
    for stale_name in (EPISODE_LESSON_FILE_NAME,):
        if stale_name in payloads:
            continue
        stale_path = target_dir / stale_name
        if stale_path.exists():
            stale_path.unlink()
            changed = True
    return changed


def write_text_and_fsync(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def gc_corrupt_episode_temp_dirs_unlocked(episodes_dir: Path) -> list[Path]:
    if not episodes_dir.exists():
        return []
    removed: list[Path] = []
    for child in sorted(episodes_dir.iterdir(), key=lambda path: path.name):
        if not child.is_dir():
            continue
        if child.name.startswith(".") and ".tmp." in child.name:
            shutil.rmtree(child)
            removed.append(child)
    return removed


def fsync_dir(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _read_text_or_none(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
