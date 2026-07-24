"""Saved dismissed-agent group archive facade."""

from __future__ import annotations

import json
import tempfile
from dataclasses import replace
from functools import lru_cache
from pathlib import Path
from typing import Any

from sase.core.agent_group_archive_wire import (
    AGENT_GROUP_ARCHIVE_WIRE_SCHEMA_VERSION,
    SavedAgentGroupPageWire,
    SavedAgentGroupRefWire,
    SavedAgentGroupSummaryWire,
    SavedAgentGroupWire,
    saved_agent_group_from_dict,
    saved_agent_group_page_from_dict,
    saved_agent_group_summary_from_group,
    saved_agent_group_wire_to_json_dict,
)
from sase.core.paths import sase_subdir
from sase.core.rust import require_rust_binding

from .dismissed_agents_bundles import write_json_file_atomic

_DEFAULT_DISMISSED_AGENT_GROUPS_DIR: Path | None = None
_DEFAULT_RECENT_DISMISSED_AGENT_GROUPS_DIR: Path | None = None
_WIRE_EXPORT_TYPES = (SavedAgentGroupRefWire, SavedAgentGroupSummaryWire)
_WIRE_CAPABILITY_PROBE = {
    "schema_version": AGENT_GROUP_ARCHIVE_WIRE_SCHEMA_VERSION,
    "group_id": "wire-probe",
    "created_at": "2026-05-27T12:00:00Z",
    "source": "marked_agents",
    "title": "1 agent in cl",
    "name": "Probe group",
    "canonical_global_family": "alice.athena.probe",
    "source_snapshot_digest": "a" * 64,
    "agent_count": 1,
    "top_level_agent_count": 1,
    "status_counts": {"DONE": 1},
    "project_names": ["proj"],
    "cl_names": ["cl"],
    "agent_refs": [
        {
            "agent_type": "run",
            "cl_name": "cl",
            "raw_suffix": "ts-1",
            "tribe": "backend",
            "prompt_preview": "Restore this backend worker.",
            "reasoning_effort": "high",
            "source_run_id": "run-probe-1",
        }
    ],
}


def _default_dismissed_agent_groups_dir() -> Path:
    return _DEFAULT_DISMISSED_AGENT_GROUPS_DIR or sase_subdir("dismissed_agent_groups")


def _default_recent_dismissed_agent_groups_dir() -> Path:
    return _DEFAULT_RECENT_DISMISSED_AGENT_GROUPS_DIR or sase_subdir(
        "recent_dismissed_agent_groups"
    )


def _rust_group_archive_binding(name: str) -> Any:
    if not _rust_group_archive_supports_current_wire():
        raise AttributeError("sase_core_rs saved-group archive wire is stale")
    return require_rust_binding(name)


@lru_cache(maxsize=1)
def _rust_group_archive_supports_current_wire() -> bool:
    try:
        binding = require_rust_binding("save_dismissed_agent_group")
    except (ImportError, AttributeError):
        return False

    with tempfile.TemporaryDirectory(prefix="sase-group-wire-probe-") as tmpdir:
        try:
            result = binding(tmpdir, _WIRE_CAPABILITY_PROBE)
        except Exception:
            return False

    if not isinstance(result, dict):
        return False
    refs = result.get("agent_refs")
    first_ref = refs[0] if isinstance(refs, list) and refs else None
    if not isinstance(first_ref, dict):
        return False
    return (
        result.get("name") == "Probe group"
        and first_ref.get("tribe") == "backend"
        and first_ref.get("prompt_preview") == "Restore this backend worker."
        and first_ref.get("reasoning_effort") == "high"
        and first_ref.get("source_run_id") == "run-probe-1"
        and result.get("canonical_global_family") == "alice.athena.probe"
        and result.get("source_snapshot_digest") == "a" * 64
    )


def save_dismissed_agent_group(
    group: SavedAgentGroupWire | dict[str, Any],
    *,
    groups_dir: Path | None = None,
) -> SavedAgentGroupWire:
    """Persist one saved group record and return the normalized record."""

    root = groups_dir or _default_dismissed_agent_groups_dir()
    payload = _normalize_group_dict(group)
    try:
        binding = _rust_group_archive_binding("save_dismissed_agent_group")
    except (ImportError, AttributeError):
        return _save_dismissed_agent_group_python(root, payload)

    result = binding(str(root), payload)
    return saved_agent_group_from_dict(dict(result))


def list_dismissed_agent_groups(
    *,
    limit: int = 20,
    cursor: int | None = None,
    groups_dir: Path | None = None,
) -> SavedAgentGroupPageWire:
    """List saved groups in newest-first deterministic pages."""

    root = groups_dir or _default_dismissed_agent_groups_dir()
    try:
        binding = _rust_group_archive_binding("list_dismissed_agent_groups")
    except (ImportError, AttributeError):
        return _list_dismissed_agent_groups_python(root, limit=limit, cursor=cursor)

    result = binding(str(root), limit, cursor)
    return saved_agent_group_page_from_dict(dict(result))


def load_dismissed_agent_group(
    group_id: str,
    *,
    groups_dir: Path | None = None,
) -> SavedAgentGroupWire | None:
    """Load one saved group, returning ``None`` for absent/corrupt files."""

    root = groups_dir or _default_dismissed_agent_groups_dir()
    try:
        binding = _rust_group_archive_binding("load_dismissed_agent_group")
    except (ImportError, AttributeError):
        return _load_dismissed_agent_group_python(root, group_id)

    result = binding(str(root), group_id)
    if result is None:
        return None
    return saved_agent_group_from_dict(dict(result))


def mark_dismissed_agent_group_revived(
    group_id: str,
    *,
    revived_at: str,
    groups_dir: Path | None = None,
) -> SavedAgentGroupWire | None:
    """Mark one saved group revived without deleting the group metadata."""

    root = groups_dir or _default_dismissed_agent_groups_dir()
    try:
        binding = _rust_group_archive_binding("mark_dismissed_agent_group_revived")
    except (ImportError, AttributeError):
        return _mark_dismissed_agent_group_revived_python(
            root, group_id, revived_at=revived_at
        )

    result = binding(str(root), group_id, revived_at)
    if result is None:
        return None
    return saved_agent_group_from_dict(dict(result))


def delete_dismissed_agent_group(
    group_id: str,
    *,
    groups_dir: Path | None = None,
) -> bool:
    """Delete one saved group metadata record.

    Returns ``True`` when a record was removed and ``False`` when it was
    already absent.
    """

    root = groups_dir or _default_dismissed_agent_groups_dir()
    try:
        binding = _rust_group_archive_binding("delete_dismissed_agent_group")
    except (ImportError, AttributeError):
        return _delete_dismissed_agent_group_python(root, group_id)

    return bool(binding(str(root), group_id))


def record_recent_dismissed_agent_group(
    group: SavedAgentGroupWire | dict[str, Any],
    *,
    groups_dir: Path | None = None,
    limit: int = 10,
) -> SavedAgentGroupWire:
    """Persist one recent dismissal record and prune the capped store."""

    root = groups_dir or _default_recent_dismissed_agent_groups_dir()
    payload = _normalize_group_dict(group)
    try:
        binding = _rust_group_archive_binding("record_recent_dismissed_agent_group")
    except (ImportError, AttributeError):
        return _record_recent_dismissed_agent_group_python(
            root,
            payload,
            limit=limit,
        )

    result = binding(str(root), payload, limit)
    return saved_agent_group_from_dict(dict(result))


def list_recent_dismissed_agent_groups(
    *,
    limit: int = 10,
    groups_dir: Path | None = None,
) -> SavedAgentGroupPageWire:
    """List recent dismissal records in newest-first order."""

    root = groups_dir or _default_recent_dismissed_agent_groups_dir()
    try:
        binding = _rust_group_archive_binding("list_recent_dismissed_agent_groups")
    except (ImportError, AttributeError):
        page = _list_dismissed_agent_groups_python(root, limit=limit, cursor=None)
        return SavedAgentGroupPageWire(groups=page.groups, next_cursor=None)

    result = binding(str(root), limit)
    return saved_agent_group_page_from_dict(dict(result))


def load_recent_dismissed_agent_group(
    group_id: str,
    *,
    groups_dir: Path | None = None,
) -> SavedAgentGroupWire | None:
    """Load one recent dismissal record, returning ``None`` when absent/corrupt."""

    root = groups_dir or _default_recent_dismissed_agent_groups_dir()
    try:
        binding = _rust_group_archive_binding("load_recent_dismissed_agent_group")
    except (ImportError, AttributeError):
        return _load_dismissed_agent_group_python(root, group_id)

    result = binding(str(root), group_id)
    if result is None:
        return None
    return saved_agent_group_from_dict(dict(result))


def mark_recent_dismissed_agent_group_revived(
    group_id: str,
    *,
    revived_at: str,
    groups_dir: Path | None = None,
) -> SavedAgentGroupWire | None:
    """Mark one recent dismissal record revived without deleting it."""

    root = groups_dir or _default_recent_dismissed_agent_groups_dir()
    try:
        binding = _rust_group_archive_binding(
            "mark_recent_dismissed_agent_group_revived"
        )
    except (ImportError, AttributeError):
        return _mark_dismissed_agent_group_revived_python(
            root,
            group_id,
            revived_at=revived_at,
        )

    result = binding(str(root), group_id, revived_at)
    if result is None:
        return None
    return saved_agent_group_from_dict(dict(result))


def _save_dismissed_agent_group_python(
    root: Path,
    payload: dict[str, Any],
) -> SavedAgentGroupWire:
    group = saved_agent_group_from_dict(payload)
    _validate_group(group)
    write_json_file_atomic(_group_path(root, group.group_id), payload)
    return group


def _list_dismissed_agent_groups_python(
    root: Path,
    *,
    limit: int,
    cursor: int | None,
) -> SavedAgentGroupPageWire:
    if limit <= 0:
        return SavedAgentGroupPageWire(groups=(), next_cursor=None)

    offset = max(0, int(cursor or 0))
    groups = [
        group
        for path in _iter_group_paths(root)
        if (group := _read_group_file(path)) is not None
    ]
    groups.sort(key=lambda group: group.group_id)
    groups.sort(key=lambda group: group.created_at, reverse=True)

    page_groups = groups[offset : offset + limit + 1]
    next_cursor = offset + limit if len(page_groups) > limit else None
    page_groups = page_groups[:limit]
    return SavedAgentGroupPageWire(
        groups=tuple(
            saved_agent_group_summary_from_group(group) for group in page_groups
        ),
        next_cursor=next_cursor,
    )


def _load_dismissed_agent_group_python(
    root: Path,
    group_id: str,
) -> SavedAgentGroupWire | None:
    return _read_group_file(_group_path(root, group_id))


def _mark_dismissed_agent_group_revived_python(
    root: Path,
    group_id: str,
    *,
    revived_at: str,
) -> SavedAgentGroupWire | None:
    group = _load_dismissed_agent_group_python(root, group_id)
    if group is None:
        return None
    updated = replace(
        group,
        revived_at=revived_at,
        times_revived=max(0, group.times_revived) + 1,
    )
    payload = saved_agent_group_wire_to_json_dict(updated)
    write_json_file_atomic(_group_path(root, group_id), payload)
    return updated


def _delete_dismissed_agent_group_python(root: Path, group_id: str) -> bool:
    path = _group_path(root, group_id)
    existed = path.exists()
    path.unlink(missing_ok=True)
    return existed


def _record_recent_dismissed_agent_group_python(
    root: Path,
    payload: dict[str, Any],
    *,
    limit: int,
) -> SavedAgentGroupWire:
    group = _save_dismissed_agent_group_python(root, payload)
    _prune_recent_dismissed_agent_groups_python(root, limit=limit)
    return group


def _prune_recent_dismissed_agent_groups_python(root: Path, *, limit: int) -> None:
    keep = max(1, int(limit))
    groups = [
        group
        for path in _iter_group_paths(root)
        if (group := _read_group_file(path)) is not None
    ]
    groups.sort(key=lambda group: group.group_id)
    groups.sort(key=lambda group: group.created_at, reverse=True)
    for group in groups[keep:]:
        try:
            _group_path(root, group.group_id).unlink()
        except FileNotFoundError:
            pass


def _normalize_group_dict(
    group: SavedAgentGroupWire | dict[str, Any],
) -> dict[str, Any]:
    payload = saved_agent_group_wire_to_json_dict(group)
    if not isinstance(payload, dict):
        raise TypeError("saved agent group must be a wire record or dict")
    normalized = saved_agent_group_from_dict(payload)
    _validate_group(normalized)
    return saved_agent_group_wire_to_json_dict(normalized)


def _read_group_file(path: Path) -> SavedAgentGroupWire | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        group = saved_agent_group_from_dict(data)
        _validate_group(group)
    except (KeyError, TypeError, ValueError):
        return None
    return group


def _iter_group_paths(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    paths = [path for path in root.glob("*.json") if path.is_file()]
    for entry in root.iterdir():
        if entry.is_dir() and len(entry.name) == 6 and entry.name.isdigit():
            paths.extend(path for path in entry.glob("*.json") if path.is_file())
    return paths


def _group_path(root: Path, group_id: str) -> Path:
    _validate_group_id(group_id)
    return root / f"{group_id}.json"


def _validate_group(group: SavedAgentGroupWire) -> None:
    _validate_group_id(group.group_id)
    if group.schema_version != AGENT_GROUP_ARCHIVE_WIRE_SCHEMA_VERSION:
        raise ValueError("saved agent group schema mismatch")
    if not group.created_at.strip():
        raise ValueError("saved agent group created_at must not be empty")
    if not group.source.strip():
        raise ValueError("saved agent group source must not be empty")
    if not group.title.strip():
        raise ValueError("saved agent group title must not be empty")
    if group.agent_count < 0 or group.top_level_agent_count < 0:
        raise ValueError("saved agent group counts must be non-negative")


def _validate_group_id(group_id: str) -> None:
    if not group_id:
        raise ValueError("saved agent group id must not be empty")
    allowed = set("._-")
    if any(
        not (char.isascii() and (char.isalnum() or char in allowed))
        for char in group_id
    ):
        raise ValueError(
            "saved agent group id may only contain ASCII letters, digits, '.', '-', and '_'"
        )


__all__ = [
    "save_dismissed_agent_group",
    "list_dismissed_agent_groups",
    "load_dismissed_agent_group",
    "mark_dismissed_agent_group_revived",
    "delete_dismissed_agent_group",
    "record_recent_dismissed_agent_group",
    "list_recent_dismissed_agent_groups",
    "load_recent_dismissed_agent_group",
    "mark_recent_dismissed_agent_group_revived",
]
