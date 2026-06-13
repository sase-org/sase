"""Read normalized tool-call artifacts for TUI display.

Tool-call data is read from SASE-owned per-run artifacts. New provider runs
write normalized stream-backed rows to ``tool_calls.jsonl`` as the cross-runtime
contract. Claude schema-v3 hook rows from older runs remain readable for
backward compatibility. If a historical mixed file contains both stream and
hook rows for the same ``tool_use_id``, the hook rows are kept as a legacy
de-duplication rule so old timelines do not double-count one tool call.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ._constants import (
    KNOWN_STATUSES,
    LINEAGE_METADATA_KEYS,
    MAX_RELATED_ARTIFACT_DIRS,
    MAX_RELATED_FALLBACK_SIBLINGS,
    SUPPORTED_SCHEMA_VERSIONS,
    TOOL_CALLS_FILENAME,
)
from ._entry import ToolCallEntry
from ._parser import (
    collapse_tool_use_pairs,
    derive_tool_call_status,
    prefer_hook_records,
    read_tool_call_file,
)

if TYPE_CHECKING:
    from sase.ace.tui.models.agent import Agent

_MAX_RELATED_ARTIFACT_DIRS = MAX_RELATED_ARTIFACT_DIRS
_MAX_RELATED_FALLBACK_SIBLINGS = MAX_RELATED_FALLBACK_SIBLINGS

__all__ = [
    "KNOWN_STATUSES",
    "SUPPORTED_SCHEMA_VERSIONS",
    "TOOL_CALLS_FILENAME",
    "ToolCallEntry",
    "derive_tool_call_status",
    "discover_related_tool_artifact_dirs",
    "discover_related_tool_artifact_dirs_cached",
    "read_tool_calls_for_agent",
]


def read_tool_calls_for_agent(
    agent: Agent,
    *,
    artifact_dirs: Sequence[Path | str] | None = None,
) -> list[ToolCallEntry] | None:
    """Return tool calls for *agent*.

    Returns ``None`` when no relevant ``tool_calls.jsonl`` exists, and ``[]``
    when one or more artifacts exist but contain no usable records.
    """
    get_artifacts_dir = getattr(agent, "get_artifacts_dir", None)
    if not callable(get_artifacts_dir):
        return None

    artifacts_dir = get_artifacts_dir()
    if not artifacts_dir:
        return None

    current = Path(artifacts_dir).expanduser()
    related_dirs = (
        discover_related_tool_artifact_dirs(agent, current)
        if artifact_dirs is None
        else _dedupe_artifact_dirs(artifact_dirs, current=current)
    )
    paths = [path / TOOL_CALLS_FILENAME for path in related_dirs]
    existing_paths = [path for path in paths if path.is_file()]
    if not existing_paths:
        return None

    entries: list[ToolCallEntry] = []
    file_order = 0
    for artifact_dir in related_dirs:
        path = artifact_dir / TOOL_CALLS_FILENAME
        if not path.is_file():
            continue
        entries.extend(read_tool_call_file(path, artifact_dir, file_order))
        file_order += 1

    entries.sort(
        key=lambda entry: (
            entry._recorded_at_sort,
            entry._file_order,
            entry.line_number,
            entry.tool_use_id or "",
        )
    )
    entries = prefer_hook_records(entries)
    return collapse_tool_use_pairs(entries)


def discover_related_tool_artifact_dirs(
    agent: Agent,
    artifacts_dir: str | Path,
) -> list[Path]:
    """Discover artifact directories for one logical agent lineage.

    The current directory is always first. Index-backed discovery follows
    explicit lineage pointers in ``sase-core``. If the index is missing or
    stale, the filesystem fallback follows direct pointers and scans only a
    small bounded prefix of legacy siblings.
    """
    current = Path(artifacts_dir).expanduser()
    current_meta = _combined_artifact_metadata(current)
    root_ids = _agent_root_ids(agent, current, current_meta)

    indexed_dirs = _discover_related_tool_artifact_dirs_from_index(current, root_ids)
    if indexed_dirs:
        return _dedupe_artifact_dirs(indexed_dirs, current=current)

    direct_dirs = _discover_related_tool_artifact_dirs_direct(
        agent,
        current,
        current_meta,
    )
    scanned_dirs = _discover_related_tool_artifact_dirs_bounded_scan(
        current,
        root_ids,
    )
    return _dedupe_artifact_dirs(
        [*direct_dirs, *scanned_dirs],
        current=current,
    )


def _discover_related_tool_artifact_dirs_from_index(
    current: Path,
    root_ids: set[str],
) -> list[Path]:
    try:
        from sase.core.agent_scan_facade import (
            default_agent_artifact_index_path,
            query_related_agent_artifact_dirs,
        )
    except ImportError:
        return []

    index_path = default_agent_artifact_index_path()
    if not index_path.is_file():
        return []
    try:
        return query_related_agent_artifact_dirs(
            index_path,
            current,
            sorted(root_ids),
        )
    except (AttributeError, ImportError, OSError, RuntimeError, ValueError):
        return []


def _discover_related_tool_artifact_dirs_direct(
    agent: Agent,
    current: Path,
    current_meta: Mapping[str, Any],
) -> list[Path]:
    related: list[Path] = []
    queue: list[Path] = [current]
    queue.extend(_related_agent_artifact_dirs(agent))
    queue.extend(
        current.parent / timestamp
        for timestamp in _lineage_timestamps_for_agent(agent, current, current_meta)
    )
    seen: set[Path] = set()

    while queue and len(related) < MAX_RELATED_ARTIFACT_DIRS:
        path = queue.pop(0).expanduser()
        if path.parent != current.parent:
            continue
        key = _path_identity(path)
        if key in seen:
            continue
        seen.add(key)
        if not path.is_dir():
            continue
        related.append(path)

        metadata = (
            current_meta
            if key == _path_identity(current)
            else (_combined_artifact_metadata(path))
        )
        queue.extend(
            path.parent / timestamp
            for timestamp in _metadata_lineage_timestamps(metadata)
        )

    return related


def _discover_related_tool_artifact_dirs_bounded_scan(
    current: Path,
    root_ids: set[str],
) -> list[Path]:
    if not root_ids:
        return []

    related: list[Path] = []
    scanned_dirs = 0
    try:
        siblings = current.parent.iterdir()
    except OSError:
        return []

    for sibling in siblings:
        if scanned_dirs >= MAX_RELATED_FALLBACK_SIBLINGS:
            break
        if sibling == current:
            continue
        try:
            is_dir = sibling.is_dir()
        except OSError:
            continue
        if not is_dir:
            continue
        scanned_dirs += 1
        if _artifact_dir_matches_roots(sibling, root_ids):
            related.append(sibling)
    return related


def discover_related_tool_artifact_dirs_cached(
    agent: Agent,
    artifacts_dir: str | Path,
    *,
    cached_dirs: list[Path] | None = None,
    cached_parent_mtime_ns: int = 0,
) -> tuple[list[Path], int]:
    """Discover artifact directories, reusing a prior result when possible.

    Returns ``(dirs, parent_mtime_ns)``. When the parent directory's mtime
    matches ``cached_parent_mtime_ns`` and ``cached_dirs`` is non-empty, returns
    ``cached_dirs`` without re-walking the parent or re-reading sibling
    metadata. Otherwise re-runs :func:`discover_related_tool_artifact_dirs`.
    """
    current = Path(artifacts_dir).expanduser()
    parent = current.parent
    try:
        parent_mtime_ns = parent.stat().st_mtime_ns
    except OSError:
        return [current], 0

    if (
        cached_dirs
        and cached_parent_mtime_ns
        and parent_mtime_ns == cached_parent_mtime_ns
    ):
        return cached_dirs, parent_mtime_ns

    return discover_related_tool_artifact_dirs(agent, artifacts_dir), parent_mtime_ns


def _dedupe_artifact_dirs(
    artifact_dirs: Iterable[Path | str],
    *,
    current: Path,
) -> list[Path]:
    seen: set[Path] = set()
    result: list[Path] = []
    for raw_path in (current, *artifact_dirs):
        path = Path(raw_path).expanduser()
        key = _path_identity(path)
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    if not result:
        return [current]
    head = result[0]
    tail = sorted(result[1:], key=lambda path: path.name)
    return [head, *tail]


def _path_identity(path: Path) -> Path:
    try:
        return path.resolve(strict=False)
    except OSError:
        return path.absolute()


def _related_agent_artifact_dirs(agent: Agent) -> list[Path]:
    related: list[Path] = []
    queue: list[Any] = [
        *list(getattr(agent, "followup_agents", []) or []),
        *list(getattr(agent, "retry_chain_siblings", []) or []),
    ]
    seen: set[int] = set()
    while queue and len(related) < MAX_RELATED_ARTIFACT_DIRS:
        candidate = queue.pop(0)
        identity = id(candidate)
        if identity in seen:
            continue
        seen.add(identity)
        get_artifacts_dir = getattr(candidate, "get_artifacts_dir", None)
        if callable(get_artifacts_dir):
            artifacts_dir = get_artifacts_dir()
            if isinstance(artifacts_dir, (str, Path)) and artifacts_dir:
                related.append(Path(artifacts_dir).expanduser())
        queue.extend(getattr(candidate, "followup_agents", []) or [])
        queue.extend(getattr(candidate, "retry_chain_siblings", []) or [])
    return related


def _lineage_timestamps_for_agent(
    agent: Agent,
    current: Path,
    current_meta: Mapping[str, Any],
) -> set[str]:
    timestamps = {
        current.name,
        *_metadata_lineage_timestamps(current_meta),
    }
    for field_name in LINEAGE_METADATA_KEYS:
        value = getattr(agent, field_name, None)
        if isinstance(value, str) and value:
            timestamps.add(value)
    return timestamps


def _metadata_lineage_timestamps(metadata: Mapping[str, Any]) -> set[str]:
    timestamps: set[str] = set()
    for key in LINEAGE_METADATA_KEYS:
        value = metadata.get(key)
        if isinstance(value, str) and value:
            timestamps.add(value)
    return timestamps


def _agent_root_ids(
    agent: Agent,
    current: Path,
    current_meta: Mapping[str, Any] | None = None,
) -> set[str]:
    root_ids: set[str] = set()
    for value in (
        getattr(agent, "retry_chain_root_timestamp", None),
        getattr(agent, "retry_of_timestamp", None),
        getattr(agent, "retried_as_timestamp", None),
        getattr(agent, "parent_timestamp", None),
        current.name,
    ):
        if isinstance(value, str) and value:
            root_ids.add(value)

    if current_meta is None:
        current_meta = _combined_artifact_metadata(current)
    for key in LINEAGE_METADATA_KEYS:
        value = current_meta.get(key)
        if isinstance(value, str) and value:
            root_ids.add(value)
    return root_ids


def _artifact_dir_matches_roots(path: Path, root_ids: set[str]) -> bool:
    if path.name in root_ids:
        return True
    metadata = _combined_artifact_metadata(path)
    for key in LINEAGE_METADATA_KEYS:
        value = metadata.get(key)
        if isinstance(value, str) and value in root_ids:
            return True
    return False


def _combined_artifact_metadata(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for filename in ("agent_meta.json", "done.json"):
        loaded = _read_json_object(path / filename)
        if loaded:
            data.update(loaded)
    return data


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return dict(data) if isinstance(data, Mapping) else {}
