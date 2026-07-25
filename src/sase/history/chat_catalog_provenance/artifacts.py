"""Transcript-to-agent artifact indexing for the provenance catalog."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import sqlite3
from typing import Any

from sase.config import get_agent_owner_identity
from sase.core.agent_identity_facade import (
    AgentIdentitySnapshot,
    globalize_owned_agent_name,
)
from sase.core.agent_scan_wire import AGENT_ARTIFACT_INDEX_SCHEMA_VERSION
from sase.core.agent_scan_facade import default_agent_artifact_index_path
from sase.core.paths import sase_projects_dir

from .cache import load_cached_json, store_cached_json
from .models import AgentChatLink

_CACHE_NAMESPACE = "agent-links"
_CACHE_KEY = "all"


@dataclass(frozen=True, slots=True)
class _ArtifactLinkCandidate:
    chat_path: str
    project_key: str
    artifact_dir: str
    local_name: str | None
    global_name: str | None
    source_machine: str | None
    source_username: str | None
    imported: bool
    order: tuple[float, str, str]


def load_agent_links(
    cache: sqlite3.Connection,
    *,
    force: bool,
) -> dict[str, AgentChatLink]:
    """Load transcript links, cached against the artifact-index generation."""

    index_path = default_agent_artifact_index_path()
    token = _artifact_generation_token(index_path)
    if not force:
        payload = load_cached_json(cache, _CACHE_NAMESPACE, _CACHE_KEY, token)
        decoded = _decode_links(payload)
        if decoded is not None:
            return decoded

    records = _indexed_records(index_path)
    if records is None:
        records = list(_filesystem_records())
    links = _build_links(records)
    store_cached_json(
        cache,
        _CACHE_NAMESPACE,
        _CACHE_KEY,
        token,
        {path: asdict(link) for path, link in links.items()},
    )
    return links


def _artifact_generation_token(index_path: Path) -> str:
    try:
        stat = index_path.stat()
    except OSError:
        root = sase_projects_dir()
        try:
            root_stat = root.stat()
        except OSError:
            return "filesystem:missing"
        return f"filesystem:{root_stat.st_mtime_ns}:{root_stat.st_size}"
    wal_path = Path(f"{index_path}-wal")
    try:
        wal_stat = wal_path.stat()
        wal_token = f":{wal_stat.st_mtime_ns}:{wal_stat.st_size}"
    except OSError:
        wal_token = ":no-wal"
    return f"sqlite:{stat.st_mtime_ns}:{stat.st_size}{wal_token}"


def _indexed_records(index_path: Path) -> list[dict[str, object]] | None:
    if not index_path.is_file():
        return None
    try:
        connection = sqlite3.connect(
            f"file:{index_path}?mode=ro",
            uri=True,
            timeout=0.25,
        )
        connection.execute("PRAGMA busy_timeout=250")
        schema_row = connection.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()
        if (
            schema_row is None
            or int(schema_row[0]) != AGENT_ARTIFACT_INDEX_SCHEMA_VERSION
        ):
            return None
        rows = connection.execute(
            """
            SELECT artifact_dir, project_name, workflow_dir_name, timestamp,
                   record_json
            FROM agent_artifacts
            """
        ).fetchall()
    except (OSError, sqlite3.DatabaseError, TypeError, ValueError):
        return None
    finally:
        if "connection" in locals():
            connection.close()

    records: list[dict[str, object]] = []
    try:
        for artifact_dir, project, workflow, timestamp, payload in rows:
            decoded = json.loads(str(payload))
            if not isinstance(decoded, dict):
                continue
            decoded["artifact_dir"] = str(artifact_dir)
            decoded["project_name"] = str(project)
            decoded["workflow_dir_name"] = str(workflow)
            decoded["timestamp"] = str(timestamp)
            records.append(decoded)
    except (json.JSONDecodeError, TypeError):
        return None
    return records


def _filesystem_records() -> Iterator[dict[str, object]]:
    for artifact_dir, project, workflow in _iter_artifact_dirs():
        meta = _read_json_object(artifact_dir / "agent_meta.json")
        done = _read_json_object(artifact_dir / "done.json")
        if meta is None and done is None:
            continue
        yield {
            "artifact_dir": str(artifact_dir),
            "project_name": project,
            "workflow_dir_name": workflow,
            "timestamp": artifact_dir.name,
            "agent_meta": meta,
            "done": done,
        }


def _iter_artifact_dirs() -> Iterator[tuple[Path, str, str]]:
    root = sase_projects_dir()
    try:
        projects = sorted(root.iterdir(), key=lambda path: path.name)
    except OSError:
        return
    for project_dir in projects:
        artifacts_root = project_dir / "artifacts"
        try:
            workflows = sorted(artifacts_root.iterdir(), key=lambda path: path.name)
        except OSError:
            continue
        for workflow_dir in workflows:
            try:
                children = sorted(workflow_dir.iterdir(), key=lambda path: path.name)
            except OSError:
                continue
            for child in children:
                if _has_agent_markers(child):
                    yield child, project_dir.name, workflow_dir.name
                    continue
                try:
                    nested = sorted(child.iterdir(), key=lambda path: path.name)
                except OSError:
                    continue
                for artifact_dir in nested:
                    if _has_agent_markers(artifact_dir):
                        yield artifact_dir, project_dir.name, workflow_dir.name


def _has_agent_markers(path: Path) -> bool:
    try:
        return path.is_dir() and (
            (path / "agent_meta.json").is_file() or (path / "done.json").is_file()
        )
    except OSError:
        return False


def _build_links(
    records: Iterable[Mapping[str, object]],
) -> dict[str, AgentChatLink]:
    candidates: defaultdict[str, list[_ArtifactLinkCandidate]] = defaultdict(list)
    for record in records:
        for candidate in _record_candidates(record):
            candidates[candidate.chat_path].append(candidate)

    result: dict[str, AgentChatLink] = {}
    for chat_path, path_candidates in candidates.items():
        ordered = sorted(path_candidates, key=lambda row: row.order, reverse=True)
        primary = ordered[0]
        result[chat_path] = AgentChatLink(
            project_key=primary.project_key,
            artifact_dir=primary.artifact_dir,
            artifact_dirs=tuple(dict.fromkeys(row.artifact_dir for row in ordered)),
            local_name=primary.local_name,
            global_name=primary.global_name,
            source_machine=primary.source_machine,
            source_username=primary.source_username,
            imported=primary.imported,
        )
    return result


def _record_candidates(
    record: Mapping[str, object],
) -> Iterator[_ArtifactLinkCandidate]:
    artifact_dir_value = str(record.get("artifact_dir") or "")
    if not artifact_dir_value:
        return
    artifact_dir = Path(artifact_dir_value).expanduser()
    projected_meta = _mapping(record.get("agent_meta"))
    projected_done = _mapping(record.get("done"))
    chat_paths = _chat_paths(projected_meta, projected_done)
    needs_raw_done = (
        not chat_paths
        or _is_projected_import(projected_done)
        or any(_looks_imported(path) for path in chat_paths)
    )
    # The current artifact-index wire intentionally projects only fields used
    # by existing TUI loaders. ``chat_path`` and ``imported_source_owner`` are
    # not among them, so one bounded marker read is required on a cold link
    # index build. The resulting link map is persisted by index generation.
    raw_meta = _read_json_object(artifact_dir / "agent_meta.json")
    raw_done = _read_json_object(artifact_dir / "done.json") if needs_raw_done else None
    meta = {**projected_meta, **(raw_meta or {})}
    done = {**projected_done, **(raw_done or {})}
    chat_paths = _chat_paths(meta, done)
    if not chat_paths:
        return

    local_name = _text(meta.get("name")) or _text(done.get("name"))
    source_username, source_machine = _imported_owner(meta, done)
    imported = bool(
        source_machine
        or _text(meta.get("imported_transaction_key"))
        or _text(done.get("imported_transaction_key"))
    )
    global_name = _text(meta.get("canonical_global_name"))
    if global_name is None and local_name is not None:
        global_name = _global_name(local_name, imported=imported)
    finished_at = _number(done.get("finished_at"))
    timestamp = str(record.get("timestamp") or artifact_dir.name)
    order = (finished_at, timestamp, str(artifact_dir))
    project_key = str(record.get("project_name") or "")
    for chat_path in chat_paths:
        yield _ArtifactLinkCandidate(
            chat_path=chat_path,
            project_key=project_key,
            artifact_dir=str(artifact_dir),
            local_name=local_name,
            global_name=global_name,
            source_machine=source_machine,
            source_username=source_username,
            imported=imported,
            order=order,
        )


def _chat_paths(
    meta: Mapping[str, object],
    done: Mapping[str, object],
) -> tuple[str, ...]:
    paths: list[str] = []
    for value in (done.get("response_path"), meta.get("chat_path")):
        text = _text(value)
        if text is None:
            continue
        paths.append(_normalize_path(text))
    return tuple(dict.fromkeys(paths))


def _normalize_path(value: str) -> str:
    return str(Path(os.path.expanduser(value)).resolve(strict=False))


def _imported_owner(
    meta: Mapping[str, object],
    done: Mapping[str, object],
) -> tuple[str | None, str | None]:
    owner = meta.get("imported_source_owner") or done.get("imported_source_owner")
    if isinstance(owner, Mapping):
        return _text(owner.get("username")), _text(owner.get("machine_name"))
    machine = _text(meta.get("imported_from_machine")) or _text(
        done.get("imported_from_machine")
    )
    return None, machine


def _is_projected_import(done: Mapping[str, object]) -> bool:
    return _text(done.get("imported_transaction_key")) is not None


def _looks_imported(path: str) -> bool:
    return Path(path).name.startswith("imported-")


def _global_name(local_name: str, *, imported: bool) -> str:
    if imported:
        return local_name
    try:
        owner = get_agent_owner_identity()
        if owner is None:
            return local_name
        return globalize_owned_agent_name(
            local_name,
            AgentIdentitySnapshot(owner),
        )
    except (ImportError, OSError, RuntimeError, ValueError):
        return local_name


def _read_json_object(path: Path) -> dict[str, object] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    return value


def _mapping(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: object) -> str | None:
    return str(value) if isinstance(value, str) and value else None


def _number(value: object) -> float:
    if isinstance(value, (float, int)) and not isinstance(value, bool):
        return float(value)
    return 0.0


def _decode_links(payload: object) -> dict[str, AgentChatLink] | None:
    if not isinstance(payload, dict):
        return None
    result: dict[str, AgentChatLink] = {}
    try:
        for path, raw_link in payload.items():
            if not isinstance(path, str) or not isinstance(raw_link, dict):
                return None
            raw_link["artifact_dirs"] = tuple(raw_link.get("artifact_dirs") or ())
            result[path] = AgentChatLink(**raw_link)
    except (TypeError, ValueError):
        return None
    return result


__all__ = ["load_agent_links"]
