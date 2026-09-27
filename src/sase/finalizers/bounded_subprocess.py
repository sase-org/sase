"""Incremental, deadlock-safe subprocess draining for finalizer execution."""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO
import logging
import os
import signal
import subprocess
import threading
import time


logger = logging.getLogger(__name__)

STDOUT_CAP_BYTES = 1_048_576
STDERR_CAP_BYTES = 1_048_576
HARD_MAX_SUBPROCESS_TIMEOUT_SECONDS = 1800.0
LIVE_SINK_ROTATE_BYTES = 512 * 1024
PROGRESS_TICK_INTERVAL_SECONDS = 2.0
_READ_CHUNK_BYTES = 65_536
_REAP_GRACE_SECONDS = 1.0
_TERM_GRACE_SECONDS = 5.0


@dataclass(frozen=True)
class BoundedCompletedProcess:
    """Captured subprocess outcome with bounded stdout/stderr."""

    returncode: int
    stdout: bytes
    stderr: bytes
    duration_seconds: float
    timed_out: bool = False
    stdout_truncated: bool = False
    stderr_truncated: bool = False


def clamp_timeout_seconds(timeout: float) -> float:
    """Keep a caller timeout inside the hard global maximum."""

    if timeout <= 0:
        return 0.001
    return min(float(timeout), HARD_MAX_SUBPROCESS_TIMEOUT_SECONDS)


class _LiveSink:
    """Best-effort interleaved output tee with bounded rotation (contract C4).

    Output chunks are appended exactly as received. At 512 KiB the file is
    moved to ``<path>.1`` (replacing it) and a new file starts. Any sink
    error disables the sink for the rest of the op and is swallowed.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._disabled = False
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "ab"):
                pass
        except OSError:
            logger.debug("live sink open failed", exc_info=True)
            self._disabled = True

    @property
    def disabled(self) -> bool:
        """Return whether the sink stopped recording."""
        return self._disabled

    def append(self, chunk: bytes) -> None:
        """Append *chunk*; disable the sink on any error."""
        if self._disabled or not chunk:
            return
        try:
            with open(self._path, "ab") as handle:
                handle.write(chunk)
                handle.flush()
            if self._path.stat().st_size >= LIVE_SINK_ROTATE_BYTES:
                rotated = self._path.with_name(self._path.name + ".1")
                try:
                    if rotated.is_file():
                        rotated.unlink()
                except OSError:
                    pass
                try:
                    os.replace(self._path, rotated)
                except OSError:
                    self._disabled = True
                    logger.debug("live sink rotation failed", exc_info=True)
        except OSError:
            self._disabled = True
            logger.debug("live sink append failed", exc_info=True)


def cleanup_live_sink(live_path: str | Path | None) -> None:
    """Remove a live sink and its rotation after terminal artifacts land.

    Both ``<path>`` and ``<path>.1`` are removed. Retained (never call this)
    on timeout, kill, or a terminal-write failure so the tail survives for
    diagnosis. Never raises.
    """
    if live_path is None:
        return
    try:
        path = Path(live_path)
        for candidate in (path, path.with_name(path.name + ".1")):
            try:
                candidate.unlink()
            except FileNotFoundError:
                pass
    except OSError:
        logger.debug("live sink cleanup failed", exc_info=True)


def run_bounded_subprocess(
    argv: Sequence[str],
    *,
    cwd: str,
    env: Mapping[str, str],
    input_bytes: bytes | None,
    timeout: float,
    stdout_cap: int = STDOUT_CAP_BYTES,
    stderr_cap: int = STDERR_CAP_BYTES,
    live_path: str | Path | None = None,
    live_streams: Collection[str] | None = None,
    progress_tick: Callable[[], None] | None = None,
    progress_tick_interval: float = PROGRESS_TICK_INTERVAL_SECONDS,
) -> BoundedCompletedProcess:
    """Run *argv* and drain pipes incrementally until exit, timeout, or cap.

    When *live_path* is set, chunks from *live_streams* (default both
    ``stdout`` and ``stderr``; pass ``{"stderr"}`` for plugin workers) are
    teed to a bounded rotating sink. When *progress_tick* is set it is
    invoked about every *progress_tick_interval* seconds from the waiting
    thread while the process runs; tick errors are swallowed.
    """

    timeout = clamp_timeout_seconds(timeout)
    started = time.monotonic()
    process = subprocess.Popen(
        list(argv),
        cwd=cwd,
        env=dict(env),
        stdin=subprocess.PIPE if input_bytes is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
        bufsize=0,
    )
    stdout_buf = bytearray()
    stderr_buf = bytearray()
    truncated = {"stdout": False, "stderr": False}
    lock = threading.Lock()
    cap_exceeded = threading.Event()
    sink = _LiveSink(live_path) if live_path is not None else None
    teed = set(live_streams) if live_streams is not None else {"stdout", "stderr"}

    def _reader(
        stream: BinaryIO | None,
        name: str,
        cap: int,
        buf: bytearray,
    ) -> None:
        if stream is None:
            return
        try:
            while True:
                chunk = stream.read(_READ_CHUNK_BYTES)
                if not chunk:
                    break
                with lock:
                    if sink is not None and name in teed:
                        sink.append(chunk)
                    if truncated[name]:
                        continue
                    room = cap - len(buf)
                    if len(chunk) > room:
                        buf.extend(chunk[: max(0, room)])
                        truncated[name] = True
                        cap_exceeded.set()
                    else:
                        buf.extend(chunk)
        except OSError:
            return
        finally:
            try:
                stream.close()
            except OSError:
                pass

    threads = [
        threading.Thread(
            target=_reader,
            args=(process.stdout, "stdout", stdout_cap, stdout_buf),
            daemon=True,
        ),
        threading.Thread(
            target=_reader,
            args=(process.stderr, "stderr", stderr_cap, stderr_buf),
            daemon=True,
        ),
    ]
    for thread in threads:
        thread.start()

    if input_bytes is not None and process.stdin is not None:

        def _write_stdin() -> None:
            assert process.stdin is not None
            try:
                process.stdin.write(input_bytes)
                process.stdin.flush()
            except OSError:
                return
            finally:
                try:
                    process.stdin.close()
                except OSError:
                    pass

        threading.Thread(target=_write_stdin, daemon=True).start()

    timed_out = False
    deadline = started + timeout
    last_tick = started
    try:
        while True:
            if cap_exceeded.is_set():
                _escalate_stop(process)
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                _escalate_stop(process)
                break
            try:
                process.wait(timeout=min(remaining, 0.05))
                break
            except subprocess.TimeoutExpired:
                pass
            if progress_tick is not None and progress_tick_interval > 0:
                now = time.monotonic()
                if now - last_tick >= progress_tick_interval:
                    last_tick = now
                    try:
                        progress_tick()
                    except Exception:  # noqa: BLE001 - ticks are best-effort
                        logger.debug("progress tick failed", exc_info=True)
        _reap_process(process)
    finally:
        for thread in threads:
            thread.join(timeout=_REAP_GRACE_SECONDS)

    with lock:
        stdout_truncated = truncated["stdout"]
        stderr_truncated = truncated["stderr"]
        stdout = bytes(stdout_buf)
        stderr = bytes(stderr_buf)

    return BoundedCompletedProcess(
        returncode=process.returncode if process.returncode is not None else -9,
        stdout=stdout,
        stderr=stderr,
        duration_seconds=time.monotonic() - started,
        timed_out=timed_out,
        stdout_truncated=stdout_truncated,
        stderr_truncated=stderr_truncated,
    )


def _escalate_stop(process: subprocess.Popen[bytes]) -> None:
    """Send SIGTERM, wait a short grace period, then SIGKILL leftovers."""

    _signal_process_group(process, signal.SIGTERM)
    grace_deadline = time.monotonic() + _TERM_GRACE_SECONDS
    while True:
        remaining = grace_deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            process.wait(timeout=min(remaining, 0.05))
            return
        except subprocess.TimeoutExpired:
            continue
    _kill_process_group(process)


def _signal_process_group(process: subprocess.Popen[bytes], sig: int) -> None:
    try:
        os.killpg(process.pid, sig)
    except ProcessLookupError:
        return
    except OSError:
        try:
            if sig == signal.SIGKILL:
                process.kill()
            else:
                process.terminate()
        except ProcessLookupError:
            return


def _kill_process_group(process: subprocess.Popen[bytes]) -> None:
    _signal_process_group(process, signal.SIGKILL)


def _reap_process(process: subprocess.Popen[bytes]) -> None:
    try:
        process.wait(timeout=_REAP_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        _kill_process_group(process)
        try:
            process.wait(timeout=_REAP_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            return


__all__ = [
    "BoundedCompletedProcess",
    "HARD_MAX_SUBPROCESS_TIMEOUT_SECONDS",
    "LIVE_SINK_ROTATE_BYTES",
    "PROGRESS_TICK_INTERVAL_SECONDS",
    "STDOUT_CAP_BYTES",
    "STDERR_CAP_BYTES",
    "cleanup_live_sink",
    "clamp_timeout_seconds",
    "run_bounded_subprocess",
]
