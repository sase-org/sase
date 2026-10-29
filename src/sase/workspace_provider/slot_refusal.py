"""Durable nested-preservation refusals that quarantine a workspace slot.

A launch-time ``PreservationError`` that cannot snapshot a dirty nested repo
is recorded against ``(project, workspace_num)``. While the record stands,
new auto-allocations skip the slot (the Rust allocator treats it as busy)
and an explicit pin fails fast with the same actionable message. Exactly
one notification is raised per standing record. The record clears when the
nested repo is clean or gone, when a later preservation succeeds, or when
``sase workspace repair --clear-refusal`` force-clears it.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import logging
import os
import subprocess
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sase.core.atomic_json import write_json_marker_atomic
from sase.core.paths import sase_home

LOGGER = logging.getLogger(__name__)

_SLOT_REFUSAL_STORE_FILENAME = "workspace_slot_refusals.json"
_SLOT_REFUSAL_SCHEMA_VERSION = 1
_DIRTY_PATHS_LIMIT = 20
_SLOT_REFUSAL_SENDER = "workspace-slot-refusal"
_CLEAR_REFUSAL_COMMAND = "sase workspace repair -C {workspace_num} -p {project}"
_GIT_SCRUB_KEYS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_NAMESPACE",
)

__all__ = [
    "SlotRefusalRecord",
    "bounded_dirty_paths",
    "clear_refusal",
    "clear_stale_refusals",
    "format_actionable_message",
    "list_refusals",
    "nested_repo_still_refuses",
    "raise_if_workspace_quarantined",
    "record_slot_refusal",
    "skip_workspace_nums_for_project",
]


@dataclass(frozen=True)
class SlotRefusalRecord:
    """One standing nested-preservation refusal for a numbered workspace."""

    project: str
    workspace_num: int
    nested_repo: str
    dirty_paths: tuple[str, ...]
    reason: str
    recorded_at: str

    def key(self) -> str:
        return _record_key(self.project, self.workspace_num)

    def to_dict(self) -> dict[str, Any]:
        return {
            "project": self.project,
            "workspace_num": self.workspace_num,
            "nested_repo": self.nested_repo,
            "dirty_paths": list(self.dirty_paths),
            "reason": self.reason,
            "recorded_at": self.recorded_at,
        }

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> SlotRefusalRecord | None:
        try:
            project = str(raw["project"]).strip()
            workspace_num = int(raw["workspace_num"])
            nested_repo = str(raw["nested_repo"]).strip()
            reason = str(raw["reason"])
            recorded_at = str(raw["recorded_at"])
        except (KeyError, TypeError, ValueError):
            return None
        if not project or workspace_num < 0 or not nested_repo:
            return None
        dirty_raw = raw.get("dirty_paths") or ()
        dirty_paths: tuple[str, ...]
        if isinstance(dirty_raw, str):
            dirty_paths = (dirty_raw,)
        elif isinstance(dirty_raw, (list, tuple)):
            dirty_paths = tuple(str(path) for path in dirty_raw if str(path))
        else:
            dirty_paths = ()
        return cls(
            project=project,
            workspace_num=workspace_num,
            nested_repo=nested_repo,
            dirty_paths=dirty_paths[:_DIRTY_PATHS_LIMIT],
            reason=reason,
            recorded_at=recorded_at,
        )


def _slot_refusal_store_path(*, root: str | Path | None = None) -> Path:
    """Return the durable slot-refusal store path under SASE home."""
    base = sase_home() if root is None else Path(root)
    return base / _SLOT_REFUSAL_STORE_FILENAME


def record_slot_refusal(
    *,
    project: str,
    workspace_num: int,
    nested_repo: str | Path,
    reason: str,
    dirty_paths: tuple[str, ...] | None = None,
    recorded_at: str | None = None,
    notify: bool = True,
) -> SlotRefusalRecord:
    """Record a refusal for *workspace_num* and notify once if it is new."""
    project_name = project.strip()
    nested = str(Path(nested_repo).expanduser())
    try:
        nested = str(Path(nested).resolve(strict=False))
    except OSError:
        pass
    paths = dirty_paths
    if paths is None:
        listed = bounded_dirty_paths(Path(nested), limit=_DIRTY_PATHS_LIMIT)
        paths = listed if listed is not None else ()
    record = SlotRefusalRecord(
        project=project_name,
        workspace_num=int(workspace_num),
        nested_repo=nested,
        dirty_paths=tuple(paths)[:_DIRTY_PATHS_LIMIT],
        reason=str(reason),
        recorded_at=recorded_at or datetime.now(UTC).isoformat(),
    )
    created = False
    with _store_lock() as payload:
        existing = _records_from_payload(payload)
        key = record.key()
        if key in existing:
            return existing[key]
        existing[key] = record
        _write_payload(payload, existing)
        created = True
    if created and notify:
        _notify_refusal(record)
    return record


def clear_refusal(project: str, workspace_num: int) -> SlotRefusalRecord | None:
    """Force-clear the standing refusal for *workspace_num*, if any."""
    key = _record_key(project, workspace_num)
    with _store_lock() as payload:
        existing = _records_from_payload(payload)
        removed = existing.pop(key, None)
        if removed is None:
            return None
        _write_payload(payload, existing)
        return removed


def clear_stale_refusals(project: str | None = None) -> list[SlotRefusalRecord]:
    """Clear refusals whose nested repo is now clean or gone."""
    cleared: list[SlotRefusalRecord] = []
    with _store_lock() as payload:
        existing = _records_from_payload(payload)
        remaining: dict[str, SlotRefusalRecord] = {}
        for key, record in existing.items():
            if project is not None and record.project != project:
                remaining[key] = record
                continue
            if nested_repo_still_refuses(record.nested_repo):
                remaining[key] = record
                continue
            cleared.append(record)
        if cleared:
            _write_payload(payload, remaining)
    return cleared


def list_refusals(project: str | None = None) -> list[SlotRefusalRecord]:
    """Return standing refusals, optionally filtered by *project*."""
    try:
        payload = _read_payload(_slot_refusal_store_path())
    except Exception as exc:  # noqa: BLE001 - store reads fail open.
        LOGGER.warning("slot-refusal store read failed open: %s", exc)
        return []
    records = list(_records_from_payload(payload).values())
    if project is None:
        return records
    return [record for record in records if record.project == project]


def _active_refusal(project: str, workspace_num: int) -> SlotRefusalRecord | None:
    """Return the standing refusal for *workspace_num*, auto-clearing if stale."""
    key = _record_key(project, workspace_num)
    try:
        payload = _read_payload(_slot_refusal_store_path())
    except Exception as exc:  # noqa: BLE001 - store reads fail open.
        LOGGER.warning("slot-refusal store read failed open: %s", exc)
        return None
    record = _records_from_payload(payload).get(key)
    if record is None:
        return None
    if nested_repo_still_refuses(record.nested_repo):
        return record
    clear_refusal(project, workspace_num)
    return None


def skip_workspace_nums_for_project(project: str) -> frozenset[int]:
    """Return workspace numbers auto-allocation must skip for *project*."""
    clear_stale_refusals(project)
    return frozenset(record.workspace_num for record in list_refusals(project))


def raise_if_workspace_quarantined(project: str, workspace_num: int) -> None:
    """Fail fast when an explicit launch targets a quarantined slot."""
    record = _active_refusal(project, workspace_num)
    if record is None:
        return
    from sase.running_field._model import WorkspaceClaimError

    raise WorkspaceClaimError(
        format_actionable_message(record),
        workspace_num=workspace_num,
    )


def format_actionable_message(record: SlotRefusalRecord) -> str:
    """Render the human-facing refusal diagnostic, including the clear path."""
    dirty = ", ".join(record.dirty_paths) if record.dirty_paths else "(none listed)"
    if len(record.dirty_paths) >= _DIRTY_PATHS_LIMIT:
        dirty += ", ..."
    clear_cmd = _CLEAR_REFUSAL_COMMAND.format(
        workspace_num=record.workspace_num,
        project=record.project,
    )
    return (
        f"workspace #{record.workspace_num} in project {record.project} is "
        f"quarantined: nested preservation refused for {record.nested_repo} "
        f"({record.reason}). Dirty paths: {dirty}. "
        f"New launches skip this slot until the nested repo is clean or gone. "
        f"Force-clear with `{clear_cmd}`."
    )


def nested_repo_still_refuses(nested_repo: str | Path) -> bool:
    """Return True when the nested checkout is still present and dirty."""
    path = Path(nested_repo).expanduser()
    git_marker = path / ".git"
    try:
        if not path.exists() or not os.path.lexists(git_marker):
            return False
    except OSError:
        return True
    dirty = bounded_dirty_paths(path, limit=1)
    if dirty is None:
        return True
    return bool(dirty)


def bounded_dirty_paths(
    repo: Path,
    *,
    limit: int = _DIRTY_PATHS_LIMIT,
) -> tuple[str, ...] | None:
    """Return dirty paths under *repo*, ``()`` if clean, or ``None`` on error."""
    env = dict(os.environ)
    for key in _GIT_SCRUB_KEYS:
        env.pop(key, None)
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain=v1", "-z"],
            cwd=repo,
            check=False,
            capture_output=True,
            env=env,
            stdin=subprocess.DEVNULL,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return _parse_porcelain_z(result.stdout, limit=limit)


def _parse_porcelain_z(payload: bytes, *, limit: int) -> tuple[str, ...]:
    parts = payload.split(b"\0")
    paths: list[str] = []
    index = 0
    while index < len(parts) and len(paths) < limit:
        entry = parts[index]
        index += 1
        if not entry:
            continue
        if len(entry) < 4:
            continue
        status = entry[:2]
        path = entry[3:].decode("utf-8", "surrogateescape")
        if status[:1] in (b"R", b"C") and index < len(parts) and parts[index]:
            path = parts[index].decode("utf-8", "surrogateescape")
            index += 1
        if path:
            paths.append(path)
    return tuple(paths)


def _record_key(project: str, workspace_num: int) -> str:
    return f"{project.strip()}:{int(workspace_num)}"


def _records_from_payload(payload: Mapping[str, Any]) -> dict[str, SlotRefusalRecord]:
    raw = payload.get("refusals")
    items: list[tuple[object, object]]
    if isinstance(raw, Mapping):
        items = list(raw.items())
    elif isinstance(raw, list):
        items = [
            (
                str(item.get("project", "")) + ":" + str(item.get("workspace_num", "")),
                item,
            )
            for item in raw
            if isinstance(item, Mapping)
        ]
    else:
        return {}
    records: dict[str, SlotRefusalRecord] = {}
    for key, item in items:
        if not isinstance(item, Mapping):
            continue
        record = SlotRefusalRecord.from_mapping(item)
        if record is None:
            continue
        records[str(key) if key else record.key()] = record
    return records


def _read_payload(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"schema_version": _SLOT_REFUSAL_SCHEMA_VERSION, "refusals": {}}
    except (OSError, json.JSONDecodeError):
        return {"schema_version": _SLOT_REFUSAL_SCHEMA_VERSION, "refusals": {}}
    return (
        data
        if isinstance(data, dict)
        else {
            "schema_version": _SLOT_REFUSAL_SCHEMA_VERSION,
            "refusals": {},
        }
    )


def _write_payload(
    payload: Mapping[str, Any],
    records: Mapping[str, SlotRefusalRecord],
) -> None:
    del payload
    write_json_marker_atomic(
        _slot_refusal_store_path(),
        {
            "schema_version": _SLOT_REFUSAL_SCHEMA_VERSION,
            "refusals": {
                key: record.to_dict() for key, record in sorted(records.items())
            },
        },
    )


@contextlib.contextmanager
def _store_lock() -> Iterator[dict[str, Any]]:
    path = _slot_refusal_store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(path.name + ".lock")
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield _read_payload(path)
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _notify_refusal(record: SlotRefusalRecord) -> None:
    try:
        from sase.notifications.models import Notification, normalize_notification_tags
        from sase.notifications.store import upsert_notification

        notes = [
            format_actionable_message(record),
            f"Nested repo: {record.nested_repo}",
            f"Recorded at: {record.recorded_at}",
        ]
        upsert_notification(
            Notification(
                id=str(uuid4()),
                timestamp=record.recorded_at,
                sender=_SLOT_REFUSAL_SENDER,
                icon="!",
                notes=notes,
                files=[record.nested_repo],
                tags=normalize_notification_tags(
                    ["workspace", "preservation", "quarantine"]
                ),
                action_data={
                    "project": record.project,
                    "workspace_num": str(record.workspace_num),
                    "nested_repo": record.nested_repo,
                    "clear_command": _CLEAR_REFUSAL_COMMAND.format(
                        workspace_num=record.workspace_num,
                        project=record.project,
                    ),
                },
                dedup_key=_dedup_key(record),
            ),
            plus_one_note="refusal still standing",
            plus_one_timestamp=record.recorded_at,
        )
    except Exception:  # noqa: BLE001 - notification must not hide the refusal.
        LOGGER.warning(
            "failed to notify nested-preservation refusal for %s #%s",
            record.project,
            record.workspace_num,
            exc_info=True,
        )


def _dedup_key(record: SlotRefusalRecord) -> str:
    return (
        f"workspace-slot-refusal:{record.project}:"
        f"{record.workspace_num}:{record.nested_repo}"
    )
