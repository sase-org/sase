"""Incremental, deadlock-safe subprocess draining for finalizer execution."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import BinaryIO
import os
import signal
import subprocess
import threading
import time


STDOUT_CAP_BYTES = 1_048_576
STDERR_CAP_BYTES = 1_048_576
HARD_MAX_SUBPROCESS_TIMEOUT_SECONDS = 600.0
_READ_CHUNK_BYTES = 65_536
_REAP_GRACE_SECONDS = 1.0


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


def run_bounded_subprocess(
    argv: Sequence[str],
    *,
    cwd: str,
    env: Mapping[str, str],
    input_bytes: bytes | None,
    timeout: float,
    stdout_cap: int = STDOUT_CAP_BYTES,
    stderr_cap: int = STDERR_CAP_BYTES,
) -> BoundedCompletedProcess:
    """Run *argv* and drain pipes incrementally until exit, timeout, or cap."""

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
    try:
        while True:
            if cap_exceeded.is_set():
                _kill_process_group(process)
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                _kill_process_group(process)
                break
            try:
                process.wait(timeout=min(remaining, 0.05))
                break
            except subprocess.TimeoutExpired:
                continue
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


def _kill_process_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    except OSError:
        try:
            process.kill()
        except ProcessLookupError:
            return


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
    "STDOUT_CAP_BYTES",
    "clamp_timeout_seconds",
    "run_bounded_subprocess",
]
