"""Bounded ToolRun stdout/stderr sinks and retained-log replay."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
import os
from pathlib import Path
import stat
import threading

from sase.config.tools import (
    DEFAULT_TOOL_RUNS_EVENT_MAX_BYTES,
    DEFAULT_TOOL_RUNS_RUN_LOG_MAX_BYTES,
    ToolRunsConfigError,
    get_tool_runs_config,
)
from sase.core.tool_run import tools_dir


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


__all__ = [
    "BoundedLogSink",
    "LogSinkError",
    "RunLogBudget",
    "log_policy",
    "prepare_run_paths",
    "replay_retained_bytes",
]
