"""Durable history for TUI toast notifications.

Toast capture runs on the Textual event loop, so ``record_toast`` only builds a
small record and enqueues it. A daemon writer thread owns the blocking file I/O.
Errors are diagnostic-only and must never escape back into the TUI.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sase.axe.state import read_tail_seek
from sase.core.paths import sase_subdir
from sase.logs._bounded import (
    DEFAULT_MAX_BYTES,
    append_encoded_line_locked,
    encode_jsonl_record,
    log_file_lock,
    max_bytes_from_env,
)

log = logging.getLogger(__name__)

TUI_TOASTS_JSONL: str | None = None

ENV_TOASTS_PATH = "SASE_TUI_TOASTS_PATH"
ENV_MAX_BYTES = "SASE_TUI_TOASTS_MAX_BYTES"
TOAST_HISTORY_LIMIT = 100
_COMPACT_SLACK = 50


@dataclass(frozen=True)
class ToastSession:
    """Identity of one running TUI process for toast history grouping."""

    session_id: str
    session_started_at: str
    pid: int


@dataclass(frozen=True)
class ToastRecord:
    """One toast notification record from ``tui_toasts.jsonl``."""

    timestamp: str
    session_id: str
    session_started_at: str
    pid: int
    severity: str
    title: str
    message: str


_session_lock = threading.RLock()
_current_session: ToastSession | None = None
_writer_lock = threading.Lock()
_writer_thread: threading.Thread | None = None
_writer_queue: queue.Queue[dict[str, Any]] = queue.Queue()


def tui_toasts_jsonl_path() -> Path:
    """Canonical path of the persisted TUI toast history JSONL log."""
    return Path(
        TUI_TOASTS_JSONL
        or os.environ.get(ENV_TOASTS_PATH)
        or os.path.join(str(sase_subdir("logs")), "tui_toasts.jsonl")
    )


def current_toast_session() -> ToastSession:
    """Return this process's memoized toast session identity."""
    with _session_lock:
        if _current_session is None:
            session = _reset_current_toast_session(
                session_started_at=datetime.now(UTC),
                pid=os.getpid(),
            )
            assert session is not None
            return session
        return _current_session


def record_toast(
    message: object,
    *,
    title: object = "",
    severity: object = "information",
) -> None:
    """Enqueue one toast notification for durable history.

    This function is called from ``AceApp.notify`` and must stay non-blocking
    and non-raising.
    """
    try:
        session = current_toast_session()
        record = {
            "timestamp": _format_utc(datetime.now(UTC)),
            "session_id": session.session_id,
            "session_started_at": session.session_started_at,
            "pid": session.pid,
            "severity": str(severity or "information"),
            "title": str(title or ""),
            "message": str(message),
        }
        _ensure_writer_thread()
        _writer_queue.put(record)
    except Exception:
        log.debug("TUI toast enqueue failed", exc_info=True)


def flush_toasts(timeout: float | None = None) -> bool:
    """Wait for queued toast writes to drain.

    Returns ``False`` if *timeout* elapses before all currently queued records
    are written.
    """
    deadline = None if timeout is None else time.monotonic() + timeout
    condition = _writer_queue.all_tasks_done
    with condition:
        while _writer_queue.unfinished_tasks:
            if deadline is None:
                condition.wait()
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            condition.wait(remaining)
    return True


def read_recent_toasts(limit: int = TOAST_HISTORY_LIMIT) -> list[ToastRecord]:
    """Read up to *limit* recent valid toast records from disk."""
    if limit <= 0:
        return []
    path = tui_toasts_jsonl_path()
    if not path.exists():
        return []
    raw = read_tail_seek(path, limit)
    records: list[ToastRecord] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        record = _toast_record_from_json(data)
        if record is not None:
            records.append(record)
    return records


def _reset_current_toast_session(
    *,
    session_started_at: datetime | str | None = None,
    pid: int | None = None,
) -> ToastSession | None:
    """Reset or pin the memoized session for deterministic tests."""
    global _current_session
    with _session_lock:
        if session_started_at is None and pid is None:
            _current_session = None
            return None
        started_at = _coerce_datetime(session_started_at or datetime.now(UTC))
        _current_session = _build_session(started_at, pid or os.getpid())
        return _current_session


def _ensure_writer_thread() -> None:
    global _writer_thread
    if _writer_thread is not None and _writer_thread.is_alive():
        return
    with _writer_lock:
        if _writer_thread is not None and _writer_thread.is_alive():
            return
        _writer_thread = threading.Thread(
            target=_writer_main,
            name="sase-tui-toast-log-writer",
            daemon=True,
        )
        _writer_thread.start()


def _writer_main() -> None:
    while True:
        record = _writer_queue.get()
        try:
            _append_record(tui_toasts_jsonl_path(), record)
        except Exception:
            log.debug("TUI toast write failed", exc_info=True)
        finally:
            _writer_queue.task_done()


def _append_record(path: Path, record: dict[str, Any]) -> None:
    encoded = encode_jsonl_record(record, ensure_ascii=False)
    with log_file_lock(path):
        append_encoded_line_locked(
            path,
            encoded,
            max_bytes=max_bytes_from_env(ENV_MAX_BYTES, DEFAULT_MAX_BYTES),
        )
        _compact_locked(path)


def _compact_locked(path: Path) -> None:
    with path.open("r+", encoding="utf-8") as file_obj:
        lines = file_obj.readlines()
        if len(lines) <= TOAST_HISTORY_LIMIT + _COMPACT_SLACK:
            return
        kept = lines[-TOAST_HISTORY_LIMIT:]
        file_obj.seek(0)
        file_obj.truncate(0)
        file_obj.writelines(kept)
        file_obj.flush()


def _toast_record_from_json(data: Any) -> ToastRecord | None:
    if not isinstance(data, dict):
        return None
    required = (
        "timestamp",
        "session_id",
        "session_started_at",
        "pid",
        "severity",
        "title",
        "message",
    )
    if any(key not in data for key in required):
        return None
    try:
        return ToastRecord(
            timestamp=str(data["timestamp"]),
            session_id=str(data["session_id"]),
            session_started_at=str(data["session_started_at"]),
            pid=int(data["pid"]),
            severity=str(data["severity"]),
            title=str(data["title"]),
            message=str(data["message"]),
        )
    except (TypeError, ValueError):
        return None


def _build_session(started_at: datetime, pid: int) -> ToastSession:
    timestamp = _format_utc(started_at)
    compact = timestamp.replace("-", "").replace(":", "").removesuffix("Z")
    return ToastSession(
        session_id=f"{compact}Z-{pid}",
        session_started_at=timestamp,
        pid=pid,
    )


def _coerce_datetime(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _format_utc(value: datetime) -> str:
    return (
        value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )


__all__ = [
    "ENV_TOASTS_PATH",
    "TOAST_HISTORY_LIMIT",
    "ToastRecord",
    "ToastSession",
    "current_toast_session",
    "flush_toasts",
    "read_recent_toasts",
    "record_toast",
    "tui_toasts_jsonl_path",
]
