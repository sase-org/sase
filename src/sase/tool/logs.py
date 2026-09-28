"""Bounded ToolRun stdout/stderr sinks and retained-log replay."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping
import json
import os
from dataclasses import dataclass
from pathlib import Path
import stat
import threading
from typing import Any

from sase.config.tools import (
    DEFAULT_TOOL_RUNS_EVENT_MAX_BYTES,
    DEFAULT_TOOL_RUNS_RUN_LOG_MAX_BYTES,
    ToolRunsConfigError,
    get_tool_runs_config,
)
from sase.core.tool_run import tools_dir


_TRUNCATION_PREFIX = "retained output truncated"
# The events file already carries per-run metadata that shares the retained
# logs' lifetime; a settlement-time ``output`` record keeps the dropped-byte fact
# durable without a new core field or a second per-run file.
OUTPUT_RECORD_KIND = "output"
_OUTPUT_RECORD_READ_BYTES = 16 * 1024 * 1024
_TAIL_LINE_CAP = 4000
_IN_MEMORY_TAIL_BYTES = 1024 * 1024


class LogSinkError(OSError):
    """A retained-output sink could not be created or written."""


class RunLogBudget:
    """Shared per-run retained-byte budget across stdout and stderr."""

    def __init__(self, max_bytes: int) -> None:
        self.max_bytes = max(0, max_bytes)
        self.written = 0
        self.dropped = 0
        self._lock = threading.Lock()

    def consume(self, size: int) -> int:
        """Return how many of *size* bytes may still be written to disk."""

        if size <= 0:
            return 0
        with self._lock:
            room = max(0, self.max_bytes - self.written)
            take = min(room, size)
            self.written += take
            self.dropped += size - take
            return take


class BoundedLogSink:
    """Write a child stream to a private log while keeping an in-memory tail."""

    def __init__(
        self,
        path: Path,
        budget: RunLogBudget,
        *,
        tail_lines: int,
    ) -> None:
        self.path = path
        self.budget = budget
        self.failed = False
        self.received = 0
        self.dropped = 0
        self._tail_bytes = bytearray()
        self._tail_lines: deque[bytes] = deque(maxlen=max(1, tail_lines))
        self._line_buf = bytearray()
        self._lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = path.open("wb")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    def write(self, chunk: bytes) -> None:
        if not chunk:
            return
        with self._lock:
            self.received += len(chunk)
            self._extend_tail(chunk)
            if self.failed:
                self.dropped += len(chunk)
                return
            take = self.budget.consume(len(chunk))
            dropped = len(chunk) - take
            self.dropped += dropped
            if take <= 0:
                return
            try:
                self._fh.write(chunk[:take])
                self._fh.flush()
            except OSError:
                self.failed = True
                self.dropped += take

    def close(self) -> None:
        with self._lock:
            try:
                self._fh.close()
            except OSError:
                self.failed = True

    def tail_text(self, lines: int) -> str:
        with self._lock:
            selected = list(self._tail_lines)[-max(0, lines) :]
        return b"".join(selected).decode("utf-8", "replace")

    def _extend_tail(self, chunk: bytes) -> None:
        self._tail_bytes.extend(chunk)
        overflow = len(self._tail_bytes) - _IN_MEMORY_TAIL_BYTES
        if overflow > 0:
            del self._tail_bytes[:overflow]
        self._line_buf.extend(chunk)
        while True:
            idx = self._line_buf.find(b"\n")
            if idx < 0:
                break
            self._tail_lines.append(bytes(self._line_buf[: idx + 1]))
            del self._line_buf[: idx + 1]
            if len(self._tail_lines) > _TAIL_LINE_CAP:
                self._tail_lines.popleft()
        if len(self._line_buf) > _IN_MEMORY_TAIL_BYTES:
            self._tail_lines.append(bytes(self._line_buf))
            self._line_buf.clear()


def log_write_diagnostics(
    stdout_sink: BoundedLogSink | None,
    stderr_sink: BoundedLogSink | None,
) -> list[str]:
    """Return one explicit fact per retained log sink whose write failed."""

    facts = []
    for label, sink in (("stdout", stdout_sink), ("stderr", stderr_sink)):
        if sink is not None and sink.failed:
            facts.append(f"retained {label} log write failed: {sink.path}")
    return facts


def truncation_diagnostics(
    stdout_sink: BoundedLogSink | None,
    stderr_sink: BoundedLogSink | None,
    budget: RunLogBudget,
) -> list[str]:
    """Return one explicit dropped-byte fact when a retained log lost output."""

    sinks = (("stdout", stdout_sink), ("stderr", stderr_sink))
    dropped = [
        f"{label} dropped {sink.dropped} bytes"
        for label, sink in sinks
        if sink is not None and sink.dropped > 0
    ]
    if not dropped:
        return []
    write_failed = any(sink is not None and sink.failed for _, sink in sinks)
    reason = (
        "after a log write failure"
        if write_failed
        else f"run_log_max_bytes={budget.max_bytes}"
    )
    return [f"{_TRUNCATION_PREFIX}: {', '.join(dropped)} ({reason})"]


def record_truncation(
    events_path: Path | None, run_id: str, messages: list[str]
) -> bool:
    """Append one durable dropped-byte record to the run's events file."""

    if events_path is None or not messages:
        return False
    record = {
        "schema_version": 1,
        "kind": OUTPUT_RECORD_KIND,
        "run_id": run_id,
        "event_id": f"{run_id}:output",
        "messages": messages,
    }
    try:
        with events_path.open("ab") as handle:
            handle.write(json.dumps(record, sort_keys=True).encode("utf-8") + b"\n")
    except OSError:
        return False
    return True


def read_truncation_messages(events_path: object, run_id: str) -> list[str]:
    """Return the recorded dropped-byte messages for *run_id*, if any."""

    if not events_path:
        return []
    try:
        with Path(str(events_path)).open("rb") as handle:
            data = handle.read(_OUTPUT_RECORD_READ_BYTES)
    except OSError:
        return []
    messages: list[str] = []
    for raw in data.splitlines():
        if OUTPUT_RECORD_KIND.encode() not in raw:
            continue
        try:
            record = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if (
            isinstance(record, dict)
            and record.get("kind") == OUTPUT_RECORD_KIND
            and record.get("run_id") == run_id
        ):
            messages = [str(item) for item in record.get("messages") or ()]
    return messages


def log_policy() -> dict[str, int]:
    """Return ToolRun log caps, falling back to defaults if policy is invalid."""

    try:
        return get_tool_runs_config()
    except ToolRunsConfigError:
        return {
            "run_log_max_bytes": DEFAULT_TOOL_RUNS_RUN_LOG_MAX_BYTES,
            "event_max_bytes": DEFAULT_TOOL_RUNS_EVENT_MAX_BYTES,
        }


def _ensure_tools_layout() -> Path:
    """Create ``sase_home()/tools`` and ``logs/`` with private modes."""

    root = tools_dir()
    _mkdir_private(root, 0o700)
    _mkdir_private(root / "logs", 0o700)
    return root


def prepare_run_paths(
    run_id: str, *, owns_output: bool
) -> tuple[Path, Path | None, Path | None]:
    """Create per-run log directory and return events/stdout/stderr paths."""

    _ensure_tools_layout()
    directory = tools_dir() / "logs" / run_id
    _mkdir_private(directory, 0o700)
    events = directory / "events.jsonl"
    events.touch(exist_ok=True)
    try:
        os.chmod(events, 0o600)
    except OSError:
        pass
    if not owns_output:
        return events, None, None
    return events, directory / "stdout.log", directory / "stderr.log"


def replay_retained_bytes(path: Path, write: Callable[[bytes], None]) -> int:
    """Replay one retained log file as raw bytes. Returns bytes written."""

    written = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(64 * 1024)
            if not chunk:
                break
            write(chunk)
            written += len(chunk)
    return written


def _mkdir_private(path: Path, mode: int) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        st = os.lstat(path)
    except OSError as exc:
        raise LogSinkError(f"cannot inspect {path}: {exc}") from exc
    if stat.S_ISLNK(st.st_mode):
        raise LogSinkError(f"refusing to follow symlink {path}")
    if not stat.S_ISDIR(st.st_mode):
        raise LogSinkError(f"{path} is not a directory")
    try:
        os.chmod(path, mode)
    except OSError:
        pass


def retained_log_rotated(path: Path | str) -> bool:
    """Return True when a retained log has a rotated ``.1`` sibling.

    Shared with the ``sase tool show --log`` replay path, which reports the
    same rotation as truncation.
    """

    sibling = Path(str(path)).with_name(f"{Path(str(path)).name}.1")
    try:
        return sibling.is_file()
    except OSError:
        return False


#: Availability words for :class:`_ToolRunLogTail`, matching the honest-absence
#: copy the Runs card renders.
TOOL_RUN_LOG_AVAILABILITY: tuple[str, ...] = (
    "available",
    "truncated",
    "pruned",
    "owner-missing",
    "not-recorded",
)

#: Tail sources: the run's own retained streams, its owner's log, or neither.
TOOL_RUN_LOG_SOURCES: tuple[str, ...] = ("run", "owner", "none")


@dataclass(frozen=True)
class _ToolRunLogTail:
    """A bounded tail of a run's output of record.

    ``availability`` is one of ``available``, ``truncated``, ``pruned``,
    ``owner-missing``, or ``not-recorded``; ``source`` is ``run``, ``owner``,
    or ``none``. ``lines`` holds the decoded tail lines without endings,
    ``total_bytes`` the retained bytes on disk, and ``truncated`` whether the
    tail omits retained output.
    """

    availability: str = "not-recorded"
    source: str = "none"
    lines: tuple[str, ...] = ()
    total_bytes: int = 0
    truncated: bool = False


def _tail_of_file(
    path: Path, lines: int, max_bytes: int
) -> tuple[list[str], int, bool]:
    """Return the last *lines* lines within the last *max_bytes* of *path*.

    Also returns the file size and whether retained output was left out.
    """

    try:
        size = path.stat().st_size
    except OSError:
        return [], 0, False
    if lines <= 0 or max_bytes <= 0:
        return [], size, size > 0
    window = min(size, max_bytes)
    try:
        with path.open("rb") as handle:
            handle.seek(size - window)
            data = handle.read(window)
    except OSError:
        return [], size, False
    text = data.decode("utf-8", "replace")
    if not text:
        return [], size, size > window
    text_lines = text.splitlines()
    kept = text_lines[-lines:]
    return kept, size, size > window or len(text_lines) > lines


def _rotated_tail(
    path: Path, lines: int, max_bytes: int
) -> tuple[list[str], int, bool]:
    """Return the merged tail of a retained log plus its rotated sibling."""

    sibling = path.with_name(f"{path.name}.1")
    rotated = retained_log_rotated(path)
    prior: list[str] = []
    if rotated:
        prior, _, _ = _tail_of_file(sibling, lines, max_bytes)
    kept, size, cut = _tail_of_file(path, lines, max_bytes)
    try:
        size += sibling.stat().st_size
    except OSError:
        pass
    merged = (prior + kept)[-lines:] if lines > 0 else []
    # A rotation marker means retained output lives outside this tail, the
    # same truncation the show replay path reports.
    dropped = len(prior) + len(kept) > len(merged)
    return merged, size, rotated or cut or dropped


def _owner_log_tail(
    kind: str, owner_id: str, metadata: Mapping[str, Any], lines: int, max_bytes: int
) -> _ToolRunLogTail:
    """Tail the owner's log of record, or report that it is missing."""

    recorded = metadata.get("owner_log_path")
    if recorded:
        path = Path(str(recorded))
        if path.is_file():
            kept, size, cut = _rotated_tail(path, lines, max_bytes)
            return _ToolRunLogTail(
                availability="truncated" if cut else "available",
                source="owner",
                lines=tuple(kept),
                total_bytes=size,
                truncated=cut,
            )
        return _ToolRunLogTail(availability="owner-missing", source="none")
    resolved: Path | None = None
    if kind == "proc" and owner_id:
        try:
            from sase.procs.store import get_proc

            proc = get_proc(owner_id)
        except Exception:  # noqa: BLE001 - expired owners have no log.
            proc = None
        if proc is not None and proc.log_path and Path(proc.log_path).is_file():
            resolved = Path(proc.log_path)
    elif kind == "monitor" and owner_id:
        try:
            from sase.tool.control import monitor_output_path

            found = monitor_output_path(
                {"project": metadata.get("project") or ""}, owner_id
            )
        except Exception:  # noqa: BLE001 - expired owners have no log.
            found = None
        if found is not None and found.is_file():
            resolved = found
    if resolved is None:
        return _ToolRunLogTail(availability="owner-missing", source="none")
    kept, size, cut = _rotated_tail(resolved, lines, max_bytes)
    return _ToolRunLogTail(
        availability="truncated" if cut else "available",
        source="owner",
        lines=tuple(kept),
        total_bytes=size,
        truncated=cut,
    )


def tool_run_log_tail(
    run_id: str,
    logs_metadata: Mapping[str, Any] | None,
    owner_kind: str | None,
    owner_id: str | None,
    lines: int,
    max_bytes: int,
) -> _ToolRunLogTail:
    """Return the bounded tail of a run's output of record.

    The selection mirrors the ``sase tool show --log`` path: the run's own
    retained stdout/stderr streams first, then the owner's log, then the
    honest-absence cases. ``logs_metadata`` is the run's ``logs`` map
    (``stdout_path``, ``stderr_path``, ``events_path``, ``owner_log_path``,
    plus ``detail_pruned``/``log_pruned`` retention signals). The result is
    pure apart from the file reads it exists to bound.
    """

    metadata = dict(logs_metadata or {})
    retained = [
        Path(str(raw))
        for key in ("stdout_path", "stderr_path")
        if (raw := metadata.get(key))
    ]
    if retained:
        existing = [path for path in retained if path.is_file()]
        if not existing:
            if metadata.get("detail_pruned") or metadata.get("log_pruned"):
                return _ToolRunLogTail(availability="pruned", source="none")
            return _ToolRunLogTail(availability="not-recorded", source="none")
        merged: list[str] = []
        total = 0
        cut = False
        for path in existing:
            kept, size, truncated = _rotated_tail(path, lines, max_bytes)
            total += size
            cut = cut or truncated
            merged.extend(kept)
        kept_lines = merged[-lines:] if lines > 0 else []
        if len(merged) > len(kept_lines):
            cut = True
        truncation_record = read_truncation_messages(
            metadata.get("events_path"), run_id
        )
        if truncation_record:
            cut = True
        return _ToolRunLogTail(
            availability="truncated" if cut else "available",
            source="run",
            lines=tuple(kept_lines),
            total_bytes=total,
            truncated=cut,
        )
    kind = str(owner_kind or "")
    resolved_owner = str(owner_id or "")
    if kind and resolved_owner:
        return _owner_log_tail(kind, resolved_owner, metadata, lines, max_bytes)
    if metadata.get("detail_pruned") or metadata.get("log_pruned"):
        return _ToolRunLogTail(availability="pruned", source="none")
    return _ToolRunLogTail(availability="not-recorded", source="none")


__all__ = [
    "OUTPUT_RECORD_KIND",
    "TOOL_RUN_LOG_AVAILABILITY",
    "TOOL_RUN_LOG_SOURCES",
    "BoundedLogSink",
    "LogSinkError",
    "RunLogBudget",
    "_ToolRunLogTail",
    "log_policy",
    "log_write_diagnostics",
    "prepare_run_paths",
    "read_truncation_messages",
    "record_truncation",
    "replay_retained_bytes",
    "retained_log_rotated",
    "tool_run_log_tail",
    "truncation_diagnostics",
]
