"""Bounded presentation log retained for observed proc rows.

The durable combined log stays supervisor-owned; this buffer only backs the
ACE-local rows the Procs pane renders, so it is bounded by both line count and
character count and is safe to append to from the observer thread.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from sase.core.time import local_now

ProcLogStream = Literal["stdout", "stderr", "progress", "header", "result"]

_MAX_PROC_LOG_LINES = 5_000
_MAX_PROC_LOG_CHARS = 512 * 1024


@dataclass(frozen=True)
class ProcLogLine:
    """One append-only presentation log line."""

    text: str
    stream: ProcLogStream
    ts: datetime


@dataclass(frozen=True)
class _ProcLogSnapshot:
    """Immutable view of a presentation log."""

    lines: tuple[ProcLogLine, ...]
    version: int
    trimmed_count: int


@dataclass
class ObservedProcLog:
    """Thread-safe, bounded log used only for ACE-local presentation rows."""

    max_lines: int = _MAX_PROC_LOG_LINES
    max_chars: int = _MAX_PROC_LOG_CHARS
    _lines: list[ProcLogLine] = field(default_factory=list, init=False, repr=False)
    _chars: int = field(default=0, init=False, repr=False)
    _trimmed_count: int = field(default=0, init=False, repr=False)
    _version: int = field(default=0, init=False, repr=False)
    _lock: threading.Lock = field(
        default_factory=threading.Lock, init=False, repr=False
    )

    @property
    def version(self) -> int:
        with self._lock:
            return self._version

    def append(self, text: str, *, stream: ProcLogStream = "stdout") -> None:
        """Append text to the log, splitting multi-line chunks into log lines."""
        if text == "":
            return
        entries = text.splitlines() or [text]
        with self._lock:
            for entry in entries:
                self._lines.append(
                    ProcLogLine(text=entry.rstrip("\r"), stream=stream, ts=local_now())
                )
                self._chars += len(entry)
            while self._lines and (
                len(self._lines) > self.max_lines or self._chars > self.max_chars
            ):
                removed = self._lines.pop(0)
                self._chars -= len(removed.text)
                self._trimmed_count += 1
            self._version += 1

    def snapshot(self) -> _ProcLogSnapshot:
        with self._lock:
            return _ProcLogSnapshot(
                lines=tuple(self._lines),
                version=self._version,
                trimmed_count=self._trimmed_count,
            )

    def text(self) -> str:
        snapshot = self.snapshot()
        lines: list[str] = []
        if snapshot.trimmed_count:
            lines.append(f"... {snapshot.trimmed_count} earlier lines trimmed")
        lines.extend(line.text for line in snapshot.lines)
        if not lines:
            return ""
        return "\n".join(lines) + "\n"


__all__ = [
    "ObservedProcLog",
    "ProcLogLine",
    "ProcLogStream",
]
