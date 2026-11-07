"""Sweep checkpoint and project cursor for the ``artifact_link_backfill`` chop.

Persists two small JSON files in the chop's state directory across ticks:

- the per-project set of already-swept refs, so the resumable derivation
  sweep never redoes processed documents;
- the project the next tick starts with, so the enabled projects rotate
  fairly and a project whose work was deferred for budget goes first.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from sase.core.project_lifecycle_wire import ProjectRecordWire

STATE_FILENAME = "artifact_link_backfill.json"
_STATE_SCHEMA_VERSION = 1
CURSOR_FILENAME = "artifact_link_backfill_cursor.json"
_CURSOR_SCHEMA_VERSION = 1


def read_sweep_state(path: Path) -> dict[str, list[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != _STATE_SCHEMA_VERSION
    ):
        return {}
    swept = payload.get("swept")
    if not isinstance(swept, dict):
        return {}
    result: dict[str, list[str]] = {}
    for project_key, refs in swept.items():
        if isinstance(project_key, str) and isinstance(refs, list):
            result[project_key] = [ref for ref in refs if isinstance(ref, str)]
    return result


def write_sweep_state(path: Path, swept: dict[str, list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": _STATE_SCHEMA_VERSION, "swept": swept}
    fd, temporary_path = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream)
        os.replace(temporary_path, path)
    except BaseException:
        try:
            os.unlink(temporary_path)
        except OSError:
            pass
        raise


def read_project_cursor(path: Path) -> str | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != _CURSOR_SCHEMA_VERSION
    ):
        return None
    value = payload.get("next_project")
    return value if isinstance(value, str) and value else None


def write_project_cursor(path: Path, next_project: str | None) -> None:
    if not next_project:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": _CURSOR_SCHEMA_VERSION,
        "next_project": next_project,
    }
    fd, temporary_path = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream)
            stream.write("\n")
        os.replace(temporary_path, path)
    except BaseException:
        try:
            os.unlink(temporary_path)
        except OSError:
            pass
        raise


def rotate_records(
    records: list[ProjectRecordWire], next_project: str | None
) -> list[ProjectRecordWire]:
    if not records or not next_project:
        return records
    for index, record in enumerate(records):
        if record.project_name == next_project:
            return [*records[index:], *records[:index]]
    return records


def next_cursor_after(
    records: list[ProjectRecordWire], last_started: str | None
) -> str | None:
    if not records:
        return None
    if last_started is None:
        return records[0].project_name
    for index, record in enumerate(records):
        if record.project_name == last_started:
            return records[(index + 1) % len(records)].project_name
    return records[0].project_name
