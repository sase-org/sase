"""Pipe-backed bounded stream writer for subprocess output."""

from __future__ import annotations

import io
import os
import select
import threading
import time
from collections.abc import Callable
from pathlib import Path

from sase.logs._bounded import append_bytes_locked, log_file_lock

READ_CHUNK_BYTES = 64 * 1024
_DRAIN_POLL_SECONDS = 0.05
# Join slop after the configured drain budget so a scheduled drain thread can
# finish one last non-blocking poll. This is not a second drain window.
_CLOSE_JOIN_ALLOWANCE_SECONDS = 0.1


class BoundedLogPipe(io.TextIOBase):
    """A file-like subprocess sink backed by a bounded durable log file.

    The returned object exposes a real ``fileno()`` for ``subprocess``. A
    daemon thread drains bytes from the read end and appends them through the
    shared bounded-log rotation primitive.

    ``close()`` waits at most ``close_drain_seconds`` plus a short scheduling
    allowance. Bytes already readable at that deadline are consumed; a
    descendant that keeps a writer open does not block ``close()`` for EOF.
    If the daemon is still running after the join, it closes the read end
    itself and stores a later callback error without raising into the caller.
    """

    def __init__(
        self,
        path: Path,
        max_bytes: int,
        *,
        on_chunk: Callable[[bytes], None] | None = None,
        close_drain_seconds: float = 5.0,
    ) -> None:
        super().__init__()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        self._max_bytes = max_bytes
        self._on_chunk = on_chunk
        self._close_drain_seconds = max(0.0, close_drain_seconds)
        self._close_deadline: float | None = None
        with log_file_lock(path):
            fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600)
            os.close(fd)
        self._read_fd, self._write_fd = os.pipe()
        self._write_error: BaseException | None = None
        self._closing = threading.Event()
        self._thread = threading.Thread(
            target=self._drain,
            name=f"sase-log-pipe-{path.stem}",
            daemon=True,
        )
        self._thread.start()

    def writable(self) -> bool:
        return True

    def fileno(self) -> int:
        self._check_closed()
        return self._write_fd

    def write(self, value: str) -> int:
        self._check_closed()
        encoded = value.encode("utf-8")
        remaining = memoryview(encoded)
        while remaining:
            written = os.write(self._write_fd, remaining)
            remaining = remaining[written:]
        return len(value)

    def flush(self) -> None:
        self._check_closed()

    def close(self) -> None:
        if self.closed:
            return
        self._close_deadline = time.monotonic() + self._close_drain_seconds
        self._closing.set()
        try:
            os.close(self._write_fd)
        except OSError:
            pass
        remaining = self._close_deadline - time.monotonic()
        self._thread.join(timeout=max(0.0, remaining) + _CLOSE_JOIN_ALLOWANCE_SECONDS)
        super().close()
        if self._write_error is not None:
            raise self._write_error

    def _drain(self) -> None:
        try:
            while True:
                if self._close_deadline_reached():
                    self._ingest_ready_chunk()
                    break
                ready, _, _ = select.select(
                    [self._read_fd], [], [], _DRAIN_POLL_SECONDS
                )
                if not ready:
                    if self._closing.is_set():
                        self._ingest_ready_chunk()
                        break
                    continue
                if not self._ingest_chunk():
                    break
        except OSError as exc:
            self._write_error = exc
        finally:
            try:
                os.close(self._read_fd)
            except OSError:
                pass

    def _ingest_ready_chunk(self) -> None:
        ready, _, _ = select.select([self._read_fd], [], [], 0)
        if ready:
            self._ingest_chunk()

    def _ingest_chunk(self) -> bool:
        chunk = os.read(self._read_fd, READ_CHUNK_BYTES)
        if not chunk:
            return False
        with log_file_lock(self._path):
            append_bytes_locked(
                self._path,
                chunk,
                max_bytes=self._max_bytes,
                truncate_oversized=True,
            )
        self._notify_chunk(chunk)
        return True

    def _notify_chunk(self, chunk: bytes) -> None:
        if self._on_chunk is None:
            return
        try:
            self._on_chunk(chunk)
        except BaseException as exc:
            if self._write_error is None:
                self._write_error = exc

    def _close_deadline_reached(self) -> bool:
        return (
            self._closing.is_set()
            and self._close_deadline is not None
            and time.monotonic() >= self._close_deadline
        )

    def _check_closed(self) -> None:
        if self.closed:
            raise ValueError("I/O operation on closed bounded log pipe")


__all__ = ["BoundedLogPipe", "READ_CHUNK_BYTES"]
