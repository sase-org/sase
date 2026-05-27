"""Project-scoped episode index helpers."""

from __future__ import annotations

from dataclasses import asdict
import fcntl
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from sase.core.episode_wire import (
    EPISODE_WIRE_SCHEMA_VERSION,
    EpisodeStorageIndexRowWire,
)
from sase.memory.locks import locked_file

EPISODE_INDEX_FILE_NAME = "index.jsonl"
EPISODE_INDEX_LOCK_FILE_NAME = "index.lock"


def project_episodes_dir(
    project: str,
    *,
    projects_root: Path | str | None = None,
) -> Path:
    """Return ``~/.sase/projects/<project>/episodes`` or a test override."""

    normalized = project.strip()
    if not normalized:
        raise ValueError("episode project must not be empty")
    root = (
        Path(projects_root).expanduser()
        if projects_root is not None
        else Path.home() / ".sase" / "projects"
    )
    return root / normalized / "episodes"


def episode_index_path(
    project: str,
    *,
    projects_root: Path | str | None = None,
) -> Path:
    """Return the JSONL index path for a project episode store."""

    return project_episodes_dir(project, projects_root=projects_root) / (
        EPISODE_INDEX_FILE_NAME
    )


def episode_index_lock_path(index_path: Path) -> Path:
    """Return the lock path that protects one project episode index."""

    return index_path.parent / EPISODE_INDEX_LOCK_FILE_NAME


def read_episode_index(
    project: str,
    *,
    projects_root: Path | str | None = None,
) -> list[EpisodeStorageIndexRowWire]:
    """Read a project episode index under a shared lock."""

    path = episode_index_path(project, projects_root=projects_root)
    with locked_file(episode_index_lock_path(path), fcntl.LOCK_SH):
        return _read_episode_index_unlocked(path)


def _read_episode_index_unlocked(index_path: Path) -> list[EpisodeStorageIndexRowWire]:
    """Read an episode index without acquiring a lock."""

    if not index_path.exists():
        return []
    rows: list[EpisodeStorageIndexRowWire] = []
    try:
        lines = index_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        row = _episode_index_row_from_dict(data)
        if row is not None:
            rows.append(row)
    return rows


def upsert_episode_index_row_unlocked(
    index_path: Path,
    row: EpisodeStorageIndexRowWire,
) -> bool:
    """Upsert one index row without acquiring a lock."""

    existing_rows = _read_episode_index_unlocked(index_path)
    rows_by_id = {existing.episode_id: existing for existing in existing_rows}
    rows_by_id[row.episode_id] = row
    new_rows = _sort_rows(rows_by_id.values())
    existing_content = _read_text_or_none(index_path)
    new_content = _render_episode_index_rows(new_rows)
    if existing_content == new_content:
        return False
    _write_episode_index_unlocked(index_path, new_rows)
    return True


def _write_episode_index_unlocked(
    index_path: Path,
    rows: list[EpisodeStorageIndexRowWire],
) -> None:
    """Rewrite an episode index atomically without acquiring a lock."""

    index_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{index_path.name}.",
        suffix=".tmp",
        dir=index_path.parent,
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(_render_episode_index_rows(_sort_rows(rows)))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, index_path)
    except Exception:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def _render_episode_index_rows(rows: list[EpisodeStorageIndexRowWire]) -> str:
    """Return the deterministic JSONL representation for index rows."""

    output: list[str] = []
    for row in _sort_rows(rows):
        output.append(
            json.dumps(
                _episode_index_row_to_dict(row),
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    return "".join(f"{line}\n" for line in output)


def _episode_index_row_to_dict(row: EpisodeStorageIndexRowWire) -> dict[str, Any]:
    """Return a JSON-safe mapping for an index row."""

    return asdict(row)


def _episode_index_row_from_dict(
    data: dict[str, Any],
) -> EpisodeStorageIndexRowWire | None:
    """Parse an index row, skipping unknown or stale schema versions."""

    try:
        schema_version = int(data.get("schema_version", 0))
    except (TypeError, ValueError):
        return None
    if schema_version != EPISODE_WIRE_SCHEMA_VERSION:
        return None
    try:
        return EpisodeStorageIndexRowWire(
            schema_version=schema_version,
            episode_id=str(data["episode_id"]),
            project=str(data["project"]),
            title=str(data["title"]),
            source_count=int(data["source_count"]),
            lesson_path=str(data["lesson_path"]),
            content_sha256=str(data["content_sha256"]),
            root_agent_names=_strings(data.get("root_agent_names")),
            changespec_name=_optional_str(data.get("changespec_name")),
            bead_ids=_strings(data.get("bead_ids")),
            outcome=_optional_str(data.get("outcome")),
            first_event_at=_optional_str(data.get("first_event_at")),
            last_event_at=_optional_str(data.get("last_event_at")),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _sort_rows(
    rows: list[EpisodeStorageIndexRowWire] | Any,
) -> list[EpisodeStorageIndexRowWire]:
    return sorted(rows, key=lambda row: (row.project, row.episode_id))


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted({str(item) for item in value if str(item)})


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _read_text_or_none(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


__all__ = [
    "EPISODE_INDEX_FILE_NAME",
    "EPISODE_INDEX_LOCK_FILE_NAME",
    "episode_index_lock_path",
    "episode_index_path",
    "project_episodes_dir",
    "read_episode_index",
    "upsert_episode_index_row_unlocked",
]
