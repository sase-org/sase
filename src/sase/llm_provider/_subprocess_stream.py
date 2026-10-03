"""Shared nonblocking stream loop for JSON-line LLM subprocesses."""

import codecs
import io
import os
import select
import subprocess
import sys
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import IO

from ._subprocess_reap import teardown_stall_for

# After the watchdog has torn a provider down, how long the stream loop keeps
# reading pipes that a surviving (shielded) process still holds open, and how
# long it waits for the watchdog to finish recording the stall.
_REAPED_PIPE_SETTLE_SECONDS = 2.0
_STALL_SETTLE_TIMEOUT_SECONDS = 30.0
_JSONL_READ_SIZE = 64 * 1024
_JSONL_READ_BUDGET = 256 * 1024
_JSONL_RECORD_BUDGET = 256


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


@dataclass
class _JsonlPipe:
    """Incremental byte-reader state for one JSONL subprocess pipe."""

    name: str
    fd: int
    decoder: codecs.IncrementalDecoder = field(
        default_factory=lambda: codecs.getincrementaldecoder("utf-8")("replace")
    )
    tail: str = ""
    records: deque[str] = field(default_factory=deque)
    eof: bool = False
    finalized: bool = False

    @property
    def is_stdout(self) -> bool:
        return self.name == "stdout"

    def feed(self, data: bytes) -> str:
        """Decode bytes, queue complete stdout records, and return stderr text."""
        text = self.decoder.decode(data, final=False)
        if not self.is_stdout or not text:
            return text

        pieces = (self.tail + text).split("\n")
        self.records.extend(piece + "\n" for piece in pieces[:-1])
        self.tail = pieces[-1]
        return ""

    def finish(self) -> str:
        """Flush decoder and the final unterminated stdout record exactly once."""
        if self.finalized:
            return ""
        self.finalized = True
        text = self.decoder.decode(b"", final=True)
        if self.is_stdout:
            pieces = (self.tail + text).split("\n")
            self.records.extend(piece + "\n" for piece in pieces[:-1])
            self.tail = pieces[-1]
            if self.tail:
                self.records.append(self.tail)
                self.tail = ""
            return ""
        return text


def _make_jsonl_pipe(name: str, stream: IO[str] | None) -> _JsonlPipe | None:
    if stream is None:
        return None
    fd = stream.fileno()
    os.set_blocking(fd, False)
    return _JsonlPipe(name=name, fd=fd)


def stream_json_lines(
    process: subprocess.Popen[str],
    handle_stdout_line: Callable[[str], None],
    suppress_output: bool,
) -> tuple[str, int]:
    """Stream decoded JSONL records and stderr from a subprocess without blocking.

    JSONL providers can write bursts containing many records in one pipe write.
    Descriptor reads avoid hidden ``TextIOWrapper`` buffers, while incremental
    decoders preserve valid UTF-8 characters split across reads. Bounded reads
    and record dispatch keep a continuously-writing stdout from starving stderr
    or process/watchdog checks.
    """
    stderr_lines: list[str] = []
    stdout = _make_jsonl_pipe("stdout", process.stdout)
    stderr = _make_jsonl_pipe("stderr", process.stderr)
    pipes = [pipe for pipe in (stdout, stderr) if pipe is not None]

    def record_stderr_chunk(chunk: str) -> None:
        if not chunk:
            return
        stderr_lines.append(chunk)
        if not suppress_output:
            print(chunk, end="", file=sys.stderr, flush=True)

    settle_deadline: float | None = None
    forced_settle = False
    rotate_first = False

    def dispatch_stdout_records(limit: int) -> int:
        if stdout is None:
            return 0
        count = 0
        while stdout.records and count < limit:
            handle_stdout_line(stdout.records.popleft())
            count += 1
        return count

    def finish_pipe(pipe: _JsonlPipe) -> None:
        if pipe.eof:
            return
        pipe.eof = True
        record_stderr_chunk(pipe.finish())

    def read_ready_pipe(pipe: _JsonlPipe, byte_budget: int, record_budget: int) -> int:
        """Drain one ready descriptor within this turn's byte/record limits."""
        bytes_read = 0
        records_dispatched = 0
        while not pipe.eof and bytes_read < byte_budget:
            if pipe.is_stdout and records_dispatched >= record_budget:
                break
            read_size = min(_JSONL_READ_SIZE, byte_budget - bytes_read)
            try:
                data = os.read(pipe.fd, read_size)
            except InterruptedError:
                continue
            except BlockingIOError:
                break
            if not data:
                finish_pipe(pipe)
                break

            bytes_read += len(data)
            record_stderr_chunk(pipe.feed(data))
            if pipe.is_stdout:
                records_dispatched += dispatch_stdout_records(
                    record_budget - records_dispatched
                )
            # Check completion and watchdog state between bounded read batches.
            process.poll()
        return records_dispatched

    while True:
        if process.poll() is not None:
            stall = teardown_stall_for(process)
            if stall is not None and stall.settled.is_set():
                now = time.monotonic()
                if settle_deadline is None:
                    settle_deadline = now + _REAPED_PIPE_SETTLE_SECONDS
                elif now >= settle_deadline:
                    forced_settle = True

        # Records already decoded from one bounded read batch are serviced
        # immediately on the next pass, even when select has no new readiness.
        records_this_iteration = dispatch_stdout_records(_JSONL_RECORD_BUDGET)
        if forced_settle:
            for pipe in pipes:
                finish_pipe(pipe)

        pending_records = stdout is not None and bool(stdout.records)
        if (
            process.poll() is not None
            and all(pipe.eof for pipe in pipes)
            and not pending_records
        ):
            break
        if forced_settle and not pending_records:
            break

        active = [pipe for pipe in pipes if not pipe.eof]
        readable_fds = [pipe.fd for pipe in active]
        # A decoded record backlog must never wait for another producer write.
        timeout = 0.0 if pending_records else 0.1
        ready_fds, _, _ = select.select(readable_fds, [], [], timeout)

        ordered = active[::-1] if rotate_first else active
        rotate_first = not rotate_first
        for pipe in ordered:
            if pipe.fd not in ready_fds:
                continue
            if pipe.is_stdout:
                remaining_records = _JSONL_RECORD_BUDGET - records_this_iteration
                if pending_records or remaining_records <= 0:
                    continue
                records_this_iteration += read_ready_pipe(
                    pipe, _JSONL_READ_BUDGET, remaining_records
                )
            else:
                read_ready_pipe(pipe, _JSONL_READ_BUDGET, _JSONL_RECORD_BUDGET)

        # Observe a watchdog transition after every bounded pair of stream
        # batches; on normal exit the same readers continue through EOF.
        process.poll()

    # Keep this wait and settlement contract in step with the plain reader.
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
