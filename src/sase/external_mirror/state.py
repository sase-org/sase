"""State files for external mirror chops.

``ChopScriptContext.state_dir`` is the lumberjack directory shared by every
chop in a lane, not a per-instance directory. Files here are therefore keyed
as ``<kind>__<project_key>.json`` under the caller-supplied state directory.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import tempfile
from typing import Any


@dataclass(frozen=True)
class MirrorCursor:
    last_updated_at: datetime | None = None
    last_provider_id: str = ""
    backfill_complete: bool = False
    last_full_scan_at: datetime | None = None


@dataclass(frozen=True)
class BackoffEntry:
    failures: int
    next_attempt_at: datetime
    last_error: str = ""


def mirror_state_path(state_dir: Path, kind: str, project_key: str) -> Path:
    """Return the cursor path for one mirror kind/project pair."""
    return state_dir / f"{kind}__{project_key}.json"


def _backoff_state_path(state_dir: Path, kind: str) -> Path:
    """Return the shared backoff-state path for one mirror kind."""
    return state_dir / f"{kind}__backoff.json"


def read_mirror_cursor(state_dir: Path, kind: str, project_key: str) -> MirrorCursor:
    """Read a cursor, degrading malformed or absent state to an empty cursor."""
    path = mirror_state_path(state_dir, kind, project_key)
    try:
        with path.open(encoding="utf-8") as stream:
            payload = json.load(stream)
    except (OSError, json.JSONDecodeError):
        return MirrorCursor()
    if not isinstance(payload, dict):
        return MirrorCursor()
    return MirrorCursor(
        last_updated_at=_parse_datetime(payload.get("last_updated_at")),
        last_provider_id=str(payload.get("last_provider_id") or ""),
        backfill_complete=bool(payload.get("backfill_complete", False)),
        last_full_scan_at=_parse_datetime(payload.get("last_full_scan_at")),
    )


def write_mirror_cursor(
    state_dir: Path,
    kind: str,
    project_key: str,
    cursor: MirrorCursor,
) -> None:
    """Atomically write one mirror cursor."""
    path = mirror_state_path(state_dir, kind, project_key)
    _atomic_json_write(
        path,
        {
            "last_updated_at": _format_datetime(cursor.last_updated_at),
            "last_provider_id": cursor.last_provider_id,
            "backfill_complete": cursor.backfill_complete,
            "last_full_scan_at": _format_datetime(cursor.last_full_scan_at),
        },
    )


def read_backoff_state(state_dir: Path, kind: str) -> dict[str, BackoffEntry]:
    """Read shared mirror backoff state keyed by project."""
    path = _backoff_state_path(state_dir, kind)
    try:
        with path.open(encoding="utf-8") as stream:
            payload = json.load(stream)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    state: dict[str, BackoffEntry] = {}
    for project_key, raw_entry in payload.items():
        if not isinstance(project_key, str) or not isinstance(raw_entry, dict):
            continue
        failures = raw_entry.get("failures")
        next_attempt_at = _parse_datetime(raw_entry.get("next_attempt_at"))
        if (
            not isinstance(failures, int)
            or isinstance(failures, bool)
            or failures < 1
            or next_attempt_at is None
        ):
            continue
        state[project_key] = BackoffEntry(
            failures=failures,
            next_attempt_at=next_attempt_at,
            last_error=str(raw_entry.get("last_error") or ""),
        )
    return state


def write_backoff_state(
    state_dir: Path,
    kind: str,
    state: dict[str, BackoffEntry],
) -> None:
    """Atomically write shared mirror backoff state."""
    path = _backoff_state_path(state_dir, kind)
    payload = {
        project_key: {
            "failures": entry.failures,
            "next_attempt_at": entry.next_attempt_at.isoformat(),
            "last_error": entry.last_error,
        }
        for project_key, entry in sorted(state.items())
    }
    _atomic_json_write(path, payload)


def next_backoff_entry(
    previous: BackoffEntry | None,
    *,
    now: datetime,
    run_every_seconds: int = 600,
    max_backoff_seconds: int = 3600,
    last_error: str = "",
) -> BackoffEntry:
    """Return the next exponential backoff entry."""
    failures = (previous.failures if previous is not None else 0) + 1
    exponent = min(failures, 5)
    delay_seconds = min(run_every_seconds * (2**exponent), max_backoff_seconds)
    return BackoffEntry(
        failures=failures,
        next_attempt_at=now + timedelta(seconds=delay_seconds),
        last_error=last_error,
    )


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _format_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _atomic_json_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_path = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2)
            stream.write("\n")
        os.replace(temporary_path, path)
    except BaseException:
        try:
            os.unlink(temporary_path)
        except OSError:
            pass
        raise


__all__ = [
    "BackoffEntry",
    "MirrorCursor",
    "mirror_state_path",
    "next_backoff_entry",
    "read_backoff_state",
    "read_mirror_cursor",
    "write_backoff_state",
    "write_mirror_cursor",
]
