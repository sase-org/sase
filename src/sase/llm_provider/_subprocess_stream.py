"""Shared nonblocking stream loop for JSON-line LLM subprocesses."""

import os
import select
import subprocess
import sys
from collections.abc import Callable


def stream_json_lines(
    process: subprocess.Popen[str],
    handle_stdout_line: Callable[[str], None],
    suppress_output: bool,
) -> tuple[str, int]:
    """Stream stdout JSON lines through *handle_stdout_line* and collect stderr."""
    stderr_lines: list[str] = []

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
            line = process.stdout.readline()
            if line:
                handle_stdout_line(line)

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
                    handle_stdout_line(line)
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
