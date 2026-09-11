"""Regression tests for the shared pipe-backed bounded log writer."""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import pytest

from sase.logs.pipe import BoundedLogPipe

# Well under the historical five-second drain-thread join, with room for
# scheduling noise around the configured drain budget plus join allowance.
_PROMPT_CLOSE_SECONDS = 1.0


def test_bounded_log_pipe_reports_chunk_callback_errors_after_disk_append(
    tmp_path: Path,
) -> None:
    path = tmp_path / "stream.log"

    def fail_on_chunk(_chunk: bytes) -> None:
        raise RuntimeError("capture failed")

    pipe = BoundedLogPipe(path, max_bytes=1024, on_chunk=fail_on_chunk)
    pipe.write("hello\n")

    with pytest.raises(RuntimeError, match="capture failed"):
        pipe.close()

    assert path.read_text(encoding="utf-8") == "hello\n"


def test_close_returns_while_a_writer_remains_open(tmp_path: Path) -> None:
    path = tmp_path / "stream.log"
    pipe = BoundedLogPipe(path, max_bytes=1024, close_drain_seconds=0.05)
    leftover_writer = os.dup(pipe.fileno())
    try:
        os.write(leftover_writer, b"kept open\n")
        started = time.monotonic()
        pipe.close()
        elapsed = time.monotonic() - started
        snapshot = pipe.retention_snapshot()
    finally:
        os.close(leftover_writer)
        pipe._thread.join(timeout=1)

    assert elapsed < _PROMPT_CLOSE_SECONDS
    assert path.read_text(encoding="utf-8") == "kept open\n"
    assert snapshot.drain_confirmed is False
    assert snapshot.complete is False


def test_retention_snapshot_tracks_rotation_and_oversized_chunks(
    tmp_path: Path,
) -> None:
    path = tmp_path / "stream.log"
    pipe = BoundedLogPipe(path, max_bytes=10)
    pipe.write("abcde")
    _wait_for_size(path, 5)
    pipe.write("fghijk")
    pipe.close()

    snapshot = pipe.retention_snapshot()
    assert snapshot.total_observed_bytes == 11
    assert [(item.start, item.end) for item in snapshot.retained_ranges] == [
        (0, 5),
        (5, 11),
    ]
    assert snapshot.complete is True
    assert path.with_name("stream.log.1").read_text(encoding="utf-8") == "abcde"
    assert path.read_text(encoding="utf-8") == "fghijk"

    oversized = tmp_path / "oversized.log"
    pipe = BoundedLogPipe(oversized, max_bytes=10)
    pipe.write("0123456789ABCDEFGHIJ")
    pipe.close()

    snapshot = pipe.retention_snapshot()
    assert snapshot.total_observed_bytes == 20
    assert [(item.start, item.end) for item in snapshot.retained_ranges] == [(10, 20)]
    assert snapshot.complete is False
    assert oversized.read_text(encoding="utf-8") == "ABCDEFGHIJ"


def _wait_for_size(path: Path, size: int) -> None:
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        try:
            if path.stat().st_size == size:
                return
        except OSError:
            pass
        time.sleep(0.01)  # sase-test-wait: wait for pipe drain thread
    pytest.fail(f"{path} did not reach {size} bytes")


def test_close_preserves_already_readable_bytes_after_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "stream.log"
    parked = threading.Event()
    release = threading.Event()
    original_drain = BoundedLogPipe._drain

    def hold_drain(self: BoundedLogPipe) -> None:
        parked.set()
        assert release.wait(timeout=2)
        original_drain(self)

    monkeypatch.setattr(BoundedLogPipe, "_drain", hold_drain)
    pipe = BoundedLogPipe(path, max_bytes=1024, close_drain_seconds=0.0)
    releaser: threading.Thread | None = None
    try:
        assert parked.wait(timeout=1)
        os.write(pipe.fileno(), b"already readable\n")

        def release_after_deadline() -> None:
            deadline = time.monotonic() + 2.0
            while pipe._close_deadline is None and time.monotonic() < deadline:
                time.sleep(0.001)  # sase-test-wait: close() publishes drain deadline
            release.set()

        releaser = threading.Thread(target=release_after_deadline, daemon=True)
        releaser.start()
        pipe.close()
    finally:
        release.set()
        if releaser is not None:
            releaser.join(timeout=1)
        if not pipe.closed:
            pipe.close()
        pipe._thread.join(timeout=1)

    assert path.read_text(encoding="utf-8") == "already readable\n"


def test_close_returns_promptly_when_drain_worker_is_delayed(
    tmp_path: Path,
) -> None:
    path = tmp_path / "stream.log"
    entered = threading.Event()
    release = threading.Event()

    def stall_on_chunk(_chunk: bytes) -> None:
        entered.set()
        assert release.wait(timeout=2)

    pipe = BoundedLogPipe(
        path,
        max_bytes=1024,
        on_chunk=stall_on_chunk,
        close_drain_seconds=0.05,
    )
    pipe.write("hello\n")
    assert entered.wait(timeout=1)

    started = time.monotonic()
    try:
        pipe.close()
        elapsed = time.monotonic() - started
    finally:
        release.set()
        pipe._thread.join(timeout=1)

    assert elapsed < _PROMPT_CLOSE_SECONDS
    assert path.read_text(encoding="utf-8") == "hello\n"
