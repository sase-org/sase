"""Shared nonblocking stream loop for JSON-line LLM subprocesses."""

import io
import os
import select
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from typing import IO

from ._subprocess_reap import teardown_stall_for

# After the watchdog has torn a provider down, how long the stream loop keeps
# reading pipes that a surviving (shielded) process still holds open, and how
# long it waits for the watchdog to finish recording the stall.
_REAPED_PIPE_SETTLE_SECONDS = 2.0
_STALL_SETTLE_TIMEOUT_SECONDS = 30.0


def prepare_nonblocking_text_stream(stream: IO[str] | None) -> None:
    """Set *stream* to non-blocking mode with lenient UTF-8 error handling.

    Reconfigures the underlying ``TextIOWrapper`` to use ``errors='replace'``
    so a multi-byte UTF-8 sequence that straddles a non-blocking read boundary
    yields ``U+FFFD`` instead of raising ``UnicodeDecodeError`` and killing
    the agent.
    """
    if stream is None:
        return
    if isinstance(stream, io.TextIOWrapper):
        stream.reconfigure(errors="replace")
    os.set_blocking(stream.fileno(), False)


def drain_reaped_streams(
    process: subprocess.Popen[str],
    on_stdout_chunk: Callable[[str], None],
    on_stderr_line: Callable[[str], None],
    settled: threading.Event,
) -> None:
    """Read what a watchdog-killed provider left in its pipes, boundedly.

    A leaked descendant can inherit the provider's stdout or stderr and hold
    the write end open after the provider itself is dead, which would make a
    blocking read-to-EOF hang forever. This keeps reading until both streams
    hit EOF, or until the watchdog has finished its sweep and the pipes have
    then stayed open for a short settle period.
    """
    streams: dict[str, IO[str]] = {}
    if process.stdout:
        streams["stdout"] = process.stdout
    if process.stderr:
        streams["stderr"] = process.stderr

    settle_deadline: float | None = None
    while streams:
        if settled.is_set():
            now = time.monotonic()
            if settle_deadline is None:
                settle_deadline = now + _REAPED_PIPE_SETTLE_SECONDS
            elif now >= settle_deadline:
                return
        ready, _, _ = select.select(list(streams.values()), [], [], 0.1)
        for name, stream in list(streams.items()):
            # ``select`` cannot see lines the text wrapper already buffered,
            # so read until the wrapper reports nothing more. An empty read
            # from a stream ``select`` flagged ready (with no data before it)
            # is EOF; otherwise it only means "nothing available yet".
            got_data = False
            at_eof = False
            while True:
                try:
                    chunk = stream.readline()
                except OSError:
                    # PTY master raises EIO when the slave side closes.
                    at_eof = True
                    break
                if not chunk:
                    break
                got_data = True
                if name == "stdout":
                    on_stdout_chunk(chunk)
                else:
                    on_stderr_line(chunk)
            if at_eof or (not got_data and stream in ready):
                del streams[name]


def stream_json_lines(
    process: subprocess.Popen[str],
    handle_stdout_line: Callable[[str], None],
    suppress_output: bool,
) -> tuple[str, int]:
    """Stream stdout JSON lines through *handle_stdout_line* and collect stderr."""
    stderr_lines: list[str] = []
    stdout_buffer = ""

    prepare_nonblocking_text_stream(process.stdout)
    prepare_nonblocking_text_stream(process.stderr)

    def dispatch_stdout_chunk(chunk: str) -> None:
        nonlocal stdout_buffer
        stdout_buffer += chunk
        while True:
            newline_index = stdout_buffer.find("\n")
            if newline_index == -1:
                break
            line = stdout_buffer[: newline_index + 1]
            stdout_buffer = stdout_buffer[newline_index + 1 :]
            handle_stdout_line(line)

    def record_stderr_line(line: str) -> None:
        stderr_lines.append(line)
        if not suppress_output:
            print(line, end="", file=sys.stderr, flush=True)

    def flush_stdout_buffer() -> None:
        nonlocal stdout_buffer
        if stdout_buffer:
            handle_stdout_line(stdout_buffer)
            stdout_buffer = ""

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
            line = process.stdout.readline()
            if line:
                dispatch_stdout_chunk(line)

        if process.stderr and process.stderr in ready:
            line = process.stderr.readline()
            if line:
                record_stderr_line(line)

        if process.poll() is not None:
            stall = teardown_stall_for(process)
            if stall is not None:
                drain_reaped_streams(
                    process, dispatch_stdout_chunk, record_stderr_line, stall.settled
                )
                flush_stdout_buffer()
                break
            if process.stdout:
                os.set_blocking(process.stdout.fileno(), True)
                for line in process.stdout:
                    dispatch_stdout_chunk(line)
                flush_stdout_buffer()
            if process.stderr:
                os.set_blocking(process.stderr.fileno(), True)
                for line in process.stderr:
                    record_stderr_line(line)
            break

    return_code = process.wait()
    return_code = settle_teardown_stall(process, stderr_lines, return_code)
    return "".join(stderr_lines), return_code


def settle_teardown_stall(
    process: subprocess.Popen[str],
    stderr_lines: list[str],
    return_code: int,
) -> int:
    """Report a watchdog-terminated provider as the clean exit it stands for.

    The watchdog only fires once the host has accepted the final declaration,
    so the streamed reply is complete and the signal that ended the provider
    (a negative return code) says nothing about the turn. Waits for the
    watchdog to finish recording the stall, adds its note to *stderr_lines*,
    and returns ``0``. A provider the watchdog never touched keeps its own
    return code.
    """
    stall = teardown_stall_for(process)
    if stall is None:
        return return_code
    stall.settled.wait(timeout=_STALL_SETTLE_TIMEOUT_SECONDS)
    stderr_lines.append(stall.note + "\n")
    return 0


def append_error_events(
    stderr_content: str,
    return_code: int,
    error_events: list[str],
) -> str:
    """Append captured JSON diagnostics to stderr when a process failed."""
    if return_code == 0 or not error_events:
        return stderr_content

    error_info = "\n".join(error_events)
    if stderr_content:
        return stderr_content + "\n" + error_info
    return error_info


_append_error_events = append_error_events
_stream_json_lines = stream_json_lines
