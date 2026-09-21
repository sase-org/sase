"""Bounded, best-effort journal for axe lifecycle activity."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from sase.core.time import get_timezone

from . import state as axe_state
from .maintenance import clear_stale_maintenance, read_maintenance


LifecycleEvent = Literal["start", "stop", "restart"]

LIFECYCLE_JOURNAL_FILENAME = "lifecycle.jsonl"
DEFAULT_LIFECYCLE_JOURNAL_MAX_BYTES = 256 * 1024
_LIFECYCLE_JOURNAL_LOCK_FILENAME = "lifecycle_journal.lock"


def _lifecycle_journal_path() -> Path:
    """Return the axe lifecycle JSONL journal path."""
    return axe_state.axe_state_dir() / LIFECYCLE_JOURNAL_FILENAME


def append_lifecycle_event(
    event: LifecycleEvent,
    outcome: str,
    *,
    source: str,
    reason: str | None = None,
    orchestrator_pid: int | None = None,
    succeeded: bool,
    timestamp_epoch: float | None = None,
    max_bytes: int = DEFAULT_LIFECYCLE_JOURNAL_MAX_BYTES,
) -> bool:
    """Append one lifecycle record without surfacing persistence failures."""
    try:
        record = _lifecycle_record(
            event,
            outcome,
            source=source,
            reason=reason,
            orchestrator_pid=orchestrator_pid,
            succeeded=succeeded,
            timestamp_epoch=timestamp_epoch,
        )
        line = _serialize_record(record)
        cap = max(1, int(max_bytes))
        if len(line) > cap:
            return False

        target = _lifecycle_journal_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        lock_path = target.parent / _LIFECYCLE_JOURNAL_LOCK_FILENAME
        with lock_path.open("a+b") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                lines = _recent_valid_lines(target, max_bytes=cap)
                lines.append(line)
                lines = _fit_complete_lines(lines, max_bytes=cap)
                _atomic_replace_lines(target, lines)
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    except Exception:  # noqa: BLE001 - lifecycle success must not depend on audit I/O.
        return False
    return True


def read_recent_lifecycle_events(*, limit: int = 100) -> list[dict[str, Any]]:
    """Return recent valid records, skipping malformed or truncated rows."""
    try:
        data = _lifecycle_journal_path().read_bytes()
    except OSError:
        return []

    records: list[dict[str, Any]] = []
    for raw_line in data.splitlines():
        record = _parse_record(raw_line)
        if record is not None:
            records.append(record)
    if limit <= 0:
        return records
    return records[-limit:]


def _lifecycle_record(
    event: LifecycleEvent,
    outcome: str,
    *,
    source: str,
    reason: str | None,
    orchestrator_pid: int | None,
    succeeded: bool,
    timestamp_epoch: float | None,
) -> dict[str, Any]:
    now = time.time() if timestamp_epoch is None else float(timestamp_epoch)
    try:
        clear_stale_maintenance()
    except Exception:  # noqa: BLE001 - snapshots are best-effort.
        pass
    try:
        maintenance = read_maintenance()
    except Exception:  # noqa: BLE001 - snapshots are best-effort.
        maintenance = None
    return {
        "schema_version": 1,
        "timestamp": datetime.fromtimestamp(now, get_timezone()).isoformat(),
        "timestamp_epoch": now,
        "event": event,
        "outcome": outcome,
        "succeeded": succeeded,
        "source": source.strip() or "unknown",
        "reason": reason,
        "orchestrator_pid": orchestrator_pid,
        # The retired desired-state marker is no longer stamped here. Readers
        # must tolerate old entries that still carry the field.
        "desired_state": None,
        "maintenance": maintenance,
    }


def _serialize_record(record: dict[str, Any]) -> bytes:
    return (json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _parse_record(raw_line: bytes) -> dict[str, Any] | None:
    try:
        record = json.loads(raw_line)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(record, dict):
        return None
    if record.get("schema_version") != 1:
        return None
    if record.get("event") not in {"start", "stop", "restart"}:
        return None
    if not isinstance(record.get("outcome"), str) or not record["outcome"]:
        return None
    if not isinstance(record.get("succeeded"), bool):
        return None
    if not isinstance(record.get("source"), str) or not record["source"]:
        return None
    if not isinstance(record.get("timestamp"), str) or not record["timestamp"]:
        return None
    timestamp_epoch = record.get("timestamp_epoch")
    if not isinstance(timestamp_epoch, (int, float)):
        return None
    orchestrator_pid = record.get("orchestrator_pid")
    if orchestrator_pid is not None and not isinstance(orchestrator_pid, int):
        return None
    if record.get("desired_state") is not None and not isinstance(
        record["desired_state"], dict
    ):
        return None
    if record.get("maintenance") is not None and not isinstance(
        record["maintenance"], dict
    ):
        return None
    reason = record.get("reason")
    if reason is not None and not isinstance(reason, str):
        return None
    return record


def _recent_valid_lines(path: Path, *, max_bytes: int) -> list[bytes]:
    try:
        with path.open("rb") as journal:
            journal.seek(0, os.SEEK_END)
            size = journal.tell()
            offset = max(0, size - max_bytes)
            journal.seek(offset)
            data = journal.read(max_bytes)
    except OSError:
        return []

    lines = data.splitlines(keepends=True)
    if offset > 0 and lines:
        lines = lines[1:]
    valid: list[bytes] = []
    for line in lines:
        record = _parse_record(line)
        if record is not None:
            valid.append(_serialize_record(record))
    return valid


def _fit_complete_lines(lines: list[bytes], *, max_bytes: int) -> list[bytes]:
    kept: list[bytes] = []
    size = 0
    for line in reversed(lines):
        if size + len(line) > max_bytes:
            break
        kept.append(line)
        size += len(line)
    kept.reverse()
    return kept


def _atomic_replace_lines(path: Path, lines: list[bytes]) -> None:
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            temp_file.writelines(lines)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        os.replace(temp_path, path)
        temp_path = None
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except OSError:
                pass


__all__ = [
    "DEFAULT_LIFECYCLE_JOURNAL_MAX_BYTES",
    "LIFECYCLE_JOURNAL_FILENAME",
    "append_lifecycle_event",
    "read_recent_lifecycle_events",
]
