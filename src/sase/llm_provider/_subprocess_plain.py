"""Plain subprocess streaming and interrupt monitoring."""

import json
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

    try:
        if process.stdout:
            os.set_blocking(process.stdout.fileno(), False)
        if process.stderr:
            os.set_blocking(process.stderr.fileno(), False)

        while True:
            readable: list[object] = []
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
                    prev_line_blank = _handle_stdout_line(
                        line,
                        clean_ansi,
                        stdout_lines,
                        live_reply_file,
                        timestamps_file,
                        prev_line_blank,
                        suppress_output,
                    )

            if process.stderr and process.stderr in ready:
                line = process.stderr.readline()
                if line:
                    stderr_lines.append(line)
                    if not suppress_output:
                        print(line, end="", file=sys.stderr, flush=True)

            if process.poll() is not None:
                if process.stdout:
                    os.set_blocking(process.stdout.fileno(), True)
                    try:
                        for line in process.stdout:
                            prev_line_blank = _handle_stdout_line(
                                line,
                                clean_ansi,
                                stdout_lines,
                                live_reply_file,
                                timestamps_file,
                                prev_line_blank,
                                suppress_output,
                            )
                    except OSError:
                        pass
                if process.stderr:
                    os.set_blocking(process.stderr.fileno(), True)
                    for line in process.stderr:
                        stderr_lines.append(line)
                        if not suppress_output:
                            print(line, end="", file=sys.stderr, flush=True)
                break
    finally:
        if live_reply_file:
            live_reply_file.close()
        if timestamps_file:
            timestamps_file.close()

    return_code = process.wait()
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
