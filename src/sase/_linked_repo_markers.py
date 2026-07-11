"""Opened-workspace marker persistence for linked repositories."""

from __future__ import annotations

from collections.abc import Mapping
import json
import os
from pathlib import Path

from sase._linked_repo_config import normalize_path

OPENED_LINKED_FILENAME = "opened_linked_workspaces.json"
OPENED_SIBLINGS_FILENAME = "opened_siblings.json"

_OPENED_SCHEMA_VERSION = 2


def record_opened_linked_repo(
    name: str,
    workspace_dir: str,
    *,
    reason: str = "",
    opened_at: str | None = None,
) -> None:
    """Record that the current agent run opened a configured linked repo.

    During the migration both the canonical ``opened_linked_workspaces.json``
    and the legacy ``opened_siblings.json`` markers are written.
    """

    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not artifacts_dir:
        return

    normalized_name = name.strip()
    if not normalized_name:
        return
    normalized_reason = reason.strip()
    normalized_opened_at = (opened_at or "").strip()

    root = Path(artifacts_dir).expanduser().resolve(strict=False)
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError:
        return

    for filename, records_key in (
        (OPENED_LINKED_FILENAME, "linked_repos"),
        (OPENED_SIBLINGS_FILENAME, "siblings"),
    ):
        marker = root / filename
        records = _opened_records(marker)
        records[normalized_name] = {
            "name": normalized_name,
            "workspace_dir": normalize_path(workspace_dir),
            "reason": normalized_reason,
            "opened_at": normalized_opened_at,
        }
        _write_opened_marker(marker, records, records_key)


def opened_linked_repo_names(artifact_root: Path | None) -> set[str]:
    """Return linked repo names opened during the agent run."""

    if artifact_root is None:
        return set()
    names: set[str] = set()
    names.update(_opened_records(artifact_root / OPENED_LINKED_FILENAME))
    names.update(_opened_records(artifact_root / OPENED_SIBLINGS_FILENAME))
    return names


def opened_linked_repo_workspace_dirs(artifact_root: Path | None) -> dict[str, str]:
    """Return opened linked repo names mapped to their recorded workspace dirs."""

    if artifact_root is None:
        return {}
    workspace_dirs: dict[str, str] = {}
    for filename in (OPENED_LINKED_FILENAME, OPENED_SIBLINGS_FILENAME):
        for name, record in _opened_records(artifact_root / filename).items():
            workspace_dirs.setdefault(name, record.get("workspace_dir", ""))
    return workspace_dirs


def opened_linked_repo_records(artifact_root: Path | None) -> dict[str, dict[str, str]]:
    """Return full opened linked-repo records keyed by linked repo name."""

    if artifact_root is None:
        return {}
    records: dict[str, dict[str, str]] = {}
    for filename in (OPENED_LINKED_FILENAME, OPENED_SIBLINGS_FILENAME):
        for name, record in _opened_records(artifact_root / filename).items():
            records.setdefault(name, record)
    return records


def _write_opened_marker(
    marker: Path, records: dict[str, dict[str, str]], records_key: str
) -> None:
    payload = {
        "schema_version": _OPENED_SCHEMA_VERSION,
        records_key: [records[key] for key in sorted(records)],
    }
    try:
        tmp = marker.with_name(f".{marker.name}.{os.getpid()}.tmp")
        tmp.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp, marker)
    except OSError:
        pass


def _opened_records(marker: Path) -> dict[str, dict[str, str]]:
    try:
        loaded = json.loads(marker.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    if not isinstance(loaded, Mapping):
        return {}
    entries = loaded.get("linked_repos")
    if not isinstance(entries, list):
        entries = loaded.get("siblings")
    if not isinstance(entries, list):
        return {}

    records: dict[str, dict[str, str]] = {}
    for item in entries:
        if not isinstance(item, Mapping):
            continue
        name = item.get("name")
        workspace_dir = item.get("workspace_dir")
        if not isinstance(name, str) or not name.strip():
            continue
        if not isinstance(workspace_dir, str):
            workspace_dir = ""
        reason = item.get("reason")
        if not isinstance(reason, str):
            reason = ""
        opened_at = item.get("opened_at")
        if not isinstance(opened_at, str):
            opened_at = ""
        normalized_name = name.strip()
        records[normalized_name] = {
            "name": normalized_name,
            "workspace_dir": workspace_dir,
            "reason": reason.strip(),
            "opened_at": opened_at.strip(),
        }
    return records
