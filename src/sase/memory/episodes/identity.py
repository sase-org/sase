"""Stable episode member and alias identity helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from sase.core.episode_wire import EpisodeWire
from sase.memory.episodes.index import project_episodes_dir, read_episode_index
from sase.memory.episodes.source_refs import normalize_source_path

EPISODE_MEMBERS_FILE_NAME = "members.jsonl"
EPISODE_ALIASES_FILE_NAME = "aliases.jsonl"
EPISODE_IDENTITY_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class EpisodeMemberIndexRow:
    """One stable component member mapped to its canonical episode."""

    schema_version: int
    project: str
    member_key: str
    member_kind: str
    canonical_episode_id: str


@dataclass(frozen=True)
class EpisodeAliasIndexRow:
    """One superseded episode id mapped to its canonical episode."""

    schema_version: int
    project: str
    alias_episode_id: str
    canonical_episode_id: str
    reason: str


@dataclass(frozen=True)
class EpisodeIdResolution:
    """Resolved episode id lookup result for CLI paths."""

    requested_id: str
    matched_id: str
    episode_id: str
    is_alias: bool = False
    alias_reason: str | None = None


def read_episode_member_rows(
    project: str,
    *,
    projects_root: Path | str | None = None,
) -> list[EpisodeMemberIndexRow]:
    """Read member rows for a project episode store."""

    return read_episode_member_rows_unlocked(
        project_episodes_dir(project, projects_root=projects_root)
    )


def read_episode_alias_rows(
    project: str,
    *,
    projects_root: Path | str | None = None,
) -> list[EpisodeAliasIndexRow]:
    """Read alias rows for a project episode store."""

    return read_episode_alias_rows_unlocked(
        project_episodes_dir(project, projects_root=projects_root)
    )


def read_episode_member_rows_unlocked(
    episodes_dir: Path,
) -> list[EpisodeMemberIndexRow]:
    """Read member rows without acquiring a lock."""

    rows: list[EpisodeMemberIndexRow] = []
    for data in _read_jsonl_objects(episodes_dir / EPISODE_MEMBERS_FILE_NAME):
        row = _member_row_from_dict(data)
        if row is not None:
            rows.append(row)
    return sorted(rows, key=_member_row_sort_key)


def read_episode_alias_rows_unlocked(
    episodes_dir: Path,
) -> list[EpisodeAliasIndexRow]:
    """Read alias rows without acquiring a lock."""

    rows: list[EpisodeAliasIndexRow] = []
    for data in _read_jsonl_objects(episodes_dir / EPISODE_ALIASES_FILE_NAME):
        row = _alias_row_from_dict(data)
        if row is not None:
            rows.append(row)
    return sorted(rows, key=_alias_row_sort_key)


def write_episode_member_rows_unlocked(
    episodes_dir: Path,
    rows: list[EpisodeMemberIndexRow],
) -> bool:
    """Rewrite member rows deterministically without acquiring a lock."""

    return _write_jsonl_rows_if_changed(
        episodes_dir / EPISODE_MEMBERS_FILE_NAME,
        [_member_row_to_dict(row) for row in sorted(rows, key=_member_row_sort_key)],
    )


def write_episode_alias_rows_unlocked(
    episodes_dir: Path,
    rows: list[EpisodeAliasIndexRow],
) -> bool:
    """Rewrite alias rows deterministically without acquiring a lock."""

    return _write_jsonl_rows_if_changed(
        episodes_dir / EPISODE_ALIASES_FILE_NAME,
        [_alias_row_to_dict(row) for row in sorted(rows, key=_alias_row_sort_key)],
    )


def episode_member_keys(episode: EpisodeWire) -> list[str]:
    """Return stable member keys represented by an episode."""

    keys: set[str] = set()
    if episode.component_key:
        keys.add(f"component:{episode.component_key}")

    sources_by_id = {source.id: source for source in episode.sources}
    for source in episode.sources:
        if source.kind == "chat":
            keys.add(_chat_member_key(source.path))
            logical_chat_key = _logical_chat_member_key(
                source.path,
                source.sha256,
            )
            if logical_chat_key is not None:
                keys.add(logical_chat_key)
        artifact_dir = _artifact_dir_from_source_path(source.path)
        if artifact_dir is not None:
            keys.add(_artifact_member_key(artifact_dir))
            logical_artifact_key = _logical_artifact_member_key(
                artifact_dir,
                episode.project,
            )
            if logical_artifact_key is not None:
                keys.add(logical_artifact_key)

    for node in episode.nodes:
        if node.kind == "chat":
            node_source = sources_by_id.get(node.source_id or "")
            path = node.metadata.get("path") or (
                node_source.path if node_source is not None else None
            )
            if path:
                keys.add(_chat_member_key(path))
                logical_chat_key = _logical_chat_member_key(
                    path,
                    node_source.sha256 if node_source is not None else None,
                )
                if logical_chat_key is not None:
                    keys.add(logical_chat_key)
        elif node.kind == "agent_run":
            node_source = sources_by_id.get(node.source_id or "")
            path = (
                node.metadata.get("artifact_dir")
                or node.metadata.get("path")
                or (node_source.path if node_source is not None else None)
            )
            if path:
                artifact_dir = _artifact_dir_from_source_path(path) or path
                keys.add(_artifact_member_key(artifact_dir))
                logical_artifact_key = _logical_artifact_member_key(
                    artifact_dir,
                    episode.project,
                )
                if logical_artifact_key is not None:
                    keys.add(logical_artifact_key)

    return sorted(keys)


def member_kind_from_key(member_key: str) -> str:
    """Return the member-kind prefix for a stable member key."""

    if ":" not in member_key:
        return "unknown"
    return member_key.split(":", 1)[0]


def resolve_alias_episode_id(
    episode_id: str,
    alias_rows: list[EpisodeAliasIndexRow],
) -> str:
    """Resolve an episode id through the alias table."""

    alias_map = {
        row.alias_episode_id: row.canonical_episode_id
        for row in alias_rows
        if row.alias_episode_id and row.canonical_episode_id
    }
    current = episode_id
    seen: set[str] = set()
    while current in alias_map and current not in seen:
        seen.add(current)
        next_id = alias_map[current]
        if not next_id or next_id == current:
            break
        current = next_id
    return current


def aliases_by_canonical_episode_id(
    project: str,
    *,
    projects_root: Path | str | None = None,
) -> dict[str, list[EpisodeAliasIndexRow]]:
    """Return alias rows grouped by resolved canonical episode id."""

    rows = read_episode_alias_rows(project, projects_root=projects_root)
    grouped: dict[str, list[EpisodeAliasIndexRow]] = {}
    for row in rows:
        canonical_id = resolve_alias_episode_id(row.canonical_episode_id, rows)
        grouped.setdefault(canonical_id, []).append(row)
    return {
        key: sorted(value, key=_alias_row_sort_key) for key, value in grouped.items()
    }


def canonical_episode_ids(
    project: str,
    *,
    projects_root: Path | str | None = None,
) -> list[str]:
    """Return stored episode ids excluding known aliases."""

    alias_rows = read_episode_alias_rows(project, projects_root=projects_root)
    alias_ids = {row.alias_episode_id for row in alias_rows}
    ids = _stored_episode_ids(project, projects_root=projects_root)
    return sorted(
        episode_id
        for episode_id in ids
        if episode_id not in alias_ids
        and resolve_alias_episode_id(episode_id, alias_rows) == episode_id
    )


def episode_id_reference_map(
    project: str,
    *,
    projects_root: Path | str | None = None,
) -> dict[str, EpisodeIdResolution]:
    """Return canonical and alias id references accepted by CLI lookup."""

    references: dict[str, EpisodeIdResolution] = {}
    for episode_id in _stored_episode_ids(project, projects_root=projects_root):
        references[episode_id] = EpisodeIdResolution(
            requested_id=episode_id,
            matched_id=episode_id,
            episode_id=episode_id,
        )

    alias_rows = read_episode_alias_rows(project, projects_root=projects_root)
    for row in alias_rows:
        canonical_id = resolve_alias_episode_id(row.canonical_episode_id, alias_rows)
        references[row.alias_episode_id] = EpisodeIdResolution(
            requested_id=row.alias_episode_id,
            matched_id=row.alias_episode_id,
            episode_id=canonical_id,
            is_alias=True,
            alias_reason=row.reason,
        )
    return references


def merge_episode_member_rows(
    existing_rows: list[EpisodeMemberIndexRow],
    new_rows: list[EpisodeMemberIndexRow],
) -> list[EpisodeMemberIndexRow]:
    """Merge member rows by member key, with new rows taking precedence."""

    rows_by_key = {row.member_key: row for row in existing_rows}
    rows_by_key.update({row.member_key: row for row in new_rows})
    return sorted(rows_by_key.values(), key=_member_row_sort_key)


def merge_episode_alias_rows(
    existing_rows: list[EpisodeAliasIndexRow],
    new_rows: list[EpisodeAliasIndexRow],
) -> list[EpisodeAliasIndexRow]:
    """Merge alias rows by alias id, dropping self-aliases."""

    rows_by_alias = {
        row.alias_episode_id: row
        for row in existing_rows
        if row.alias_episode_id != row.canonical_episode_id
    }
    for row in new_rows:
        if row.alias_episode_id == row.canonical_episode_id:
            continue
        rows_by_alias[row.alias_episode_id] = row
    return sorted(rows_by_alias.values(), key=_alias_row_sort_key)


def _stored_episode_ids(
    project: str,
    *,
    projects_root: Path | str | None,
) -> set[str]:
    ids = {
        row.episode_id
        for row in read_episode_index(project, projects_root=projects_root)
    }
    episodes_dir = project_episodes_dir(project, projects_root=projects_root)
    if episodes_dir.is_dir():
        for child in episodes_dir.iterdir():
            if child.is_dir() and (child / "episode.json").is_file():
                ids.add(child.name)
    return ids


def _member_row_from_dict(data: dict[str, Any]) -> EpisodeMemberIndexRow | None:
    member_key = _row_str(data, "member_key", "key")
    canonical_episode_id = _row_str(data, "canonical_episode_id", "episode_id")
    if not member_key or not canonical_episode_id:
        return None
    return EpisodeMemberIndexRow(
        schema_version=_row_int(data, "schema_version")
        or EPISODE_IDENTITY_SCHEMA_VERSION,
        project=_row_str(data, "project") or "",
        member_key=member_key,
        member_kind=_row_str(data, "member_kind") or member_kind_from_key(member_key),
        canonical_episode_id=canonical_episode_id,
    )


def _alias_row_from_dict(data: dict[str, Any]) -> EpisodeAliasIndexRow | None:
    alias_episode_id = _row_str(
        data, "alias_episode_id", "old_episode_id", "episode_id"
    )
    canonical_episode_id = _row_str(
        data,
        "canonical_episode_id",
        "target_episode_id",
    )
    if not alias_episode_id or not canonical_episode_id:
        return None
    return EpisodeAliasIndexRow(
        schema_version=_row_int(data, "schema_version")
        or EPISODE_IDENTITY_SCHEMA_VERSION,
        project=_row_str(data, "project") or "",
        alias_episode_id=alias_episode_id,
        canonical_episode_id=canonical_episode_id,
        reason=_row_str(data, "reason") or "superseded",
    )


def _member_row_to_dict(row: EpisodeMemberIndexRow) -> dict[str, Any]:
    return asdict(row)


def _alias_row_to_dict(row: EpisodeAliasIndexRow) -> dict[str, Any]:
    return asdict(row)


def _read_jsonl_objects(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
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
        if isinstance(data, dict):
            rows.append(data)
    return rows


def _write_jsonl_rows_if_changed(path: Path, rows: list[dict[str, Any]]) -> bool:
    content = "".join(
        json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows
    )
    try:
        existing = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        existing = None
    if existing == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except Exception:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    return True


def _chat_member_key(path: str | Path) -> str:
    return f"chat:{normalize_source_path(path)}"


def _artifact_member_key(path: str | Path) -> str:
    return f"artifact:{normalize_source_path(path)}"


def _logical_chat_member_key(path: str | Path, sha256: str | None) -> str | None:
    if not sha256:
        return None
    basename = Path(path).name
    if not basename:
        return None
    return f"chat:{basename}/{sha256[:16]}"


def _logical_artifact_member_key(
    path: str | Path,
    episode_project: str,
) -> str | None:
    normalized = normalize_source_path(path)
    parts = Path(normalized).parts
    for index, part in enumerate(parts):
        if part != "artifacts":
            continue
        if index + 2 >= len(parts):
            return None
        project = parts[index - 1] if index > 0 else episode_project
        workflow = parts[index + 1]
        timestamp = parts[index + 2]
        if not project or not workflow or not timestamp:
            return None
        return f"artifact:{project}/{workflow}/{timestamp}"
    return None


def _artifact_dir_from_source_path(path: str | Path) -> str | None:
    normalized = normalize_source_path(path)
    parts = Path(normalized).parts
    for index, part in enumerate(parts):
        if part != "artifacts":
            continue
        if index + 2 >= len(parts):
            return None
        return str(Path(*parts[: index + 3]))
    return None


def _row_str(data: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _row_int(data: dict[str, Any], key: str) -> int | None:
    try:
        value = data.get(key)
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _member_row_sort_key(row: EpisodeMemberIndexRow) -> tuple[str, str, str, str]:
    return (row.project, row.member_kind, row.member_key, row.canonical_episode_id)


def _alias_row_sort_key(row: EpisodeAliasIndexRow) -> tuple[str, str, str]:
    return (row.project, row.alias_episode_id, row.canonical_episode_id)


__all__ = [
    "EPISODE_ALIASES_FILE_NAME",
    "EPISODE_IDENTITY_SCHEMA_VERSION",
    "EPISODE_MEMBERS_FILE_NAME",
    "EpisodeAliasIndexRow",
    "EpisodeIdResolution",
    "EpisodeMemberIndexRow",
    "aliases_by_canonical_episode_id",
    "canonical_episode_ids",
    "episode_id_reference_map",
    "episode_member_keys",
    "member_kind_from_key",
    "merge_episode_alias_rows",
    "merge_episode_member_rows",
    "read_episode_alias_rows",
    "read_episode_alias_rows_unlocked",
    "read_episode_member_rows",
    "read_episode_member_rows_unlocked",
    "resolve_alias_episode_id",
    "write_episode_alias_rows_unlocked",
    "write_episode_member_rows_unlocked",
]
