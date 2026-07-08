"""Shared nonblocking stream loop for JSON-line LLM subprocesses."""

import io
import os
import select
import subprocess
import sys
from collections.abc import Callable
from typing import IO


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
                stderr_lines.append(line)
                if not suppress_output:
                    print(line, end="", file=sys.stderr, flush=True)

        if process.poll() is not None:
            if process.stdout:
                os.set_blocking(process.stdout.fileno(), True)
                for line in process.stdout:
                    dispatch_stdout_chunk(line)
                flush_stdout_buffer()
            if process.stderr:
                os.set_blocking(process.stderr.fileno(), True)
                for line in process.stderr:
                    stderr_lines.append(line)
                    if not suppress_output:
                        print(line, end="", file=sys.stderr, flush=True)
            break

    return_code = process.wait()
    return "".join(stderr_lines), return_code


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
