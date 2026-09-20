"""Plain subprocess streaming, interrupt monitoring, and teardown watchdog."""

import json
import math
import os
import select
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import IO

from ._subprocess_artifacts import (
    open_live_reply_file,
    open_live_reply_timestamps_file,
    strip_ansi,
)
from ._subprocess_reap import (
    DEFAULT_TERMINATE_TIMEOUT_SECONDS,
    TeardownStall,
    register_teardown_stall,
    teardown_stall_for,
    terminate_process_tree,
)
from ._subprocess_stream import (
    drain_reaped_streams,
    prepare_nonblocking_text_stream,
    settle_teardown_stall,
)

TEARDOWN_GRACE_ENV = "SASE_PROVIDER_TEARDOWN_GRACE_SECONDS"
DEFAULT_TEARDOWN_GRACE_SECONDS = 120.0
TEARDOWN_STALL_FILENAME = "provider_teardown_stall.json"
_WATCHDOG_POLL_SECONDS = 1.0


def start_interrupt_monitor(
    process: subprocess.Popen[str],
    on_interrupt: Callable[[str | None], None],
) -> None:
    """Spin a daemon thread that watches for interrupt_request.json.

    When the file appears, invoke ``on_interrupt(message)`` with the
    ``"message"`` field from the JSON, unlink the file, and call
    ``process.terminate()``. Reads ``SASE_ARTIFACTS_DIR`` from the
    environment; no-op if unset.
    """
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not artifacts_dir:
        return

    interrupt_path = Path(artifacts_dir) / "interrupt_request.json"

    def _monitor_interrupt() -> None:
        while process.poll() is None:
            if interrupt_path.exists():
                try:
                    data = json.loads(interrupt_path.read_text(encoding="utf-8"))
                    on_interrupt(data.get("message"))
                    interrupt_path.unlink(missing_ok=True)
                    process.terminate()
                except (OSError, json.JSONDecodeError):
                    pass
                return
            time.sleep(1.0)

    threading.Thread(target=_monitor_interrupt, daemon=True).start()


def _teardown_grace_seconds() -> float:
    """Return the post-declaration grace period; ``0`` disables the watchdog.

    An unset, unparseable, negative, or non-finite value keeps the default so
    a typo in the override cannot silently switch the guard off.
    """
    raw = os.environ.get(TEARDOWN_GRACE_ENV, "").strip()
    if not raw:
        return DEFAULT_TEARDOWN_GRACE_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_TEARDOWN_GRACE_SECONDS
    if not math.isfinite(value) or value < 0:
        return DEFAULT_TEARDOWN_GRACE_SECONDS
    return value


def _file_signature(path: Path) -> tuple[int, int] | None:
    """Identify one write of *path*; ``None`` when it does not exist.

    Declarations replace ``final_submission.json`` atomically, so a new
    acceptance always changes the inode or the mtime.
    """
    try:
        stat = path.stat()
    except OSError:
        return None
    return stat.st_ino, stat.st_mtime_ns


def start_completion_watchdog(
    process: subprocess.Popen[str],
    *,
    runtime: str = "provider",
    on_stall: Callable[[TeardownStall], None] | None = None,
    grace_seconds: float | None = None,
    poll_seconds: float = _WATCHDOG_POLL_SECONDS,
    terminate_timeout: float = DEFAULT_TERMINATE_TIMEOUT_SECONDS,
) -> threading.Thread | None:
    """Spin a daemon thread that reaps a provider stuck after its declaration.

    Once the host accepts the agent's final declaration
    (``final_submission.json`` appears) the turn is over. If *process* is
    still alive *grace_seconds* later (default 120s, override with
    ``SASE_PROVIDER_TEARDOWN_GRACE_SECONDS``, ``0`` disables), it is
    terminated, its leaked descendants are reaped, the stall is written to
    ``provider_teardown_stall.json`` and stderr, and ``on_stall`` is called
    with the record. The stream loops then report the turn as a clean exit.

    A ``final_submission.json`` already present when the watchdog starts is
    ignored: it belongs to an earlier provider run in the same artifacts
    directory. Reads ``SASE_ARTIFACTS_DIR`` from the environment; no-op
    (returning ``None``) if unset or disabled.
    """
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not artifacts_dir:
        return None
    grace = _teardown_grace_seconds() if grace_seconds is None else grace_seconds
    if grace <= 0:
        return None

    from sase.finalizers.declaration_manifest import FINAL_SUBMISSION_FILENAME

    submission_path = Path(artifacts_dir) / FINAL_SUBMISSION_FILENAME
    last_seen = _file_signature(submission_path)

    def _watch() -> None:
        nonlocal last_seen
        declared_at: float | None = None
        declared_wall: datetime | None = None
        while process.poll() is None:
            signature = _file_signature(submission_path)
            now = time.monotonic()
            if signature is not None and signature != last_seen:
                # A new acceptance (re)starts the grace period.
                last_seen = signature
                declared_at = now
                declared_wall = datetime.now(tz=UTC)
            elif declared_at is not None and now - declared_at >= grace:
                assert declared_wall is not None
                _tear_down_stalled_provider(
                    process,
                    artifacts_dir,
                    runtime=runtime,
                    declared_wall=declared_wall,
                    grace=grace,
                    waited=now - declared_at,
                    terminate_timeout=terminate_timeout,
                    on_stall=on_stall,
                )
                return
            time.sleep(poll_seconds)

    thread = threading.Thread(target=_watch, daemon=True)
    thread.start()
    return thread


def _tear_down_stalled_provider(
    process: subprocess.Popen[str],
    artifacts_dir: str,
    *,
    runtime: str,
    declared_wall: datetime,
    grace: float,
    waited: float,
    terminate_timeout: float,
    on_stall: Callable[[TeardownStall], None] | None,
) -> None:
    """Terminate *process*, record the stall, and publish it via ``settled``."""
    if process.poll() is not None:
        return
    stall = TeardownStall(
        runtime=runtime,
        provider_pid=process.pid,
        declared_at=declared_wall.isoformat(),
        grace_seconds=grace,
        waited_seconds=round(waited, 3),
    )
    # Registered before the signal so a stream loop that sees the provider
    # exit already knows why, and can wait for ``settled``.
    register_teardown_stall(process, stall)
    try:
        terminate_process_tree(process, stall, timeout=terminate_timeout)
        _write_stall_artifact(artifacts_dir, stall)
        print(stall.note, file=sys.stderr, flush=True)
        if on_stall is not None:
            on_stall(stall)
    except Exception as exc:
        print(f"[sase] provider teardown watchdog failed: {exc}", file=sys.stderr)
    finally:
        stall.settled.set()


def _write_stall_artifact(artifacts_dir: str, stall: TeardownStall) -> None:
    path = os.path.join(artifacts_dir, TEARDOWN_STALL_FILENAME)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(stall.to_json(), f, indent=2, sort_keys=True)
            f.write("\n")
    except OSError:
        pass


def stream_process_output(
    process: subprocess.Popen[str],
    suppress_output: bool = False,
    clean_ansi: bool = False,
) -> tuple[str, str, int]:
    """Stream stdout and stderr from a process in real-time.

    Args:
        process: The subprocess.Popen process to stream from.
        suppress_output: If True, don't print output to console.
        clean_ansi: If True, strip ANSI escape sequences from stdout
            lines before accumulating and writing to ``live_reply.md``.
            Useful when stdout is backed by a PTY that may inject
            terminal control codes.

    Returns:
        Tuple of (stdout_content, stderr_content, return_code).
    """
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    live_reply_file = open_live_reply_file()
    timestamps_file = open_live_reply_timestamps_file()
    prev_line_blank = True

    def record_stdout(line: str) -> None:
        nonlocal prev_line_blank
        prev_line_blank = _handle_stdout_line(
            line,
            clean_ansi,
            stdout_lines,
            live_reply_file,
            timestamps_file,
            prev_line_blank,
            suppress_output,
        )

    def record_stderr(line: str) -> None:
        stderr_lines.append(line)
        if not suppress_output:
            print(line, end="", file=sys.stderr, flush=True)

    try:
        prepare_nonblocking_text_stream(process.stdout)
        prepare_nonblocking_text_stream(process.stderr)

        while True:
            readable: list[IO[str]] = []
            if process.stdout:
                readable.append(process.stdout)
            if process.stderr:
                readable.append(process.stderr)

            if not readable:
                break

            ready, _, _ = select.select(readable, [], [], 0.1)

            if process.stdout and process.stdout in ready:
                try:
                    line = process.stdout.readline()
                except OSError:
                    # PTY master raises EIO when the slave side closes.
                    line = ""
                if line:
                    record_stdout(line)

            if process.stderr and process.stderr in ready:
                line = process.stderr.readline()
                if line:
                    record_stderr(line)

            if process.poll() is not None:
                stall = teardown_stall_for(process)
                if stall is not None:
                    drain_reaped_streams(
                        process, record_stdout, record_stderr, stall.settled
                    )
                    break
                if process.stdout:
                    os.set_blocking(process.stdout.fileno(), True)
                    try:
                        for line in process.stdout:
                            record_stdout(line)
                    except OSError:
                        pass
                if process.stderr:
                    os.set_blocking(process.stderr.fileno(), True)
                    for line in process.stderr:
                        record_stderr(line)
                break
    finally:
        if live_reply_file:
            live_reply_file.close()
        if timestamps_file:
            timestamps_file.close()

    return_code = process.wait()
    return_code = settle_teardown_stall(process, stderr_lines, return_code)
    stdout_content = "".join(stdout_lines)
    stderr_content = "".join(stderr_lines)

    return stdout_content, stderr_content, return_code


def _handle_stdout_line(
    line: str,
    clean_ansi: bool,
    stdout_lines: list[str],
    live_reply_file: IO[str] | None,
    timestamps_file: IO[str] | None,
    prev_line_blank: bool,
    suppress_output: bool,
) -> bool:
    """Record one stdout line and return the next paragraph-boundary state."""
    if clean_ansi:
        line = strip_ansi(line)
    stdout_lines.append(line)
    if live_reply_file:
        if timestamps_file and prev_line_blank and line.strip():
            entry = {
                "byte_offset": live_reply_file.tell(),
                "timestamp": datetime.now(tz=UTC).isoformat(),
            }
            timestamps_file.write(json.dumps(entry) + "\n")
            timestamps_file.flush()
        prev_line_blank = not line.strip()
        live_reply_file.write(line)
        live_reply_file.flush()
    if not suppress_output:
        print(line, end="", flush=True)
    return prev_line_blank
