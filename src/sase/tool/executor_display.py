"""Terminal presentation helpers for the ToolRun executor."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, TextIO

from sase.tool.logs import BoundedLogSink
from sase.tool.stage_protocol import (
    format_unattributed_line,
    unattributed_from_stages,
)
from sase.tool.triage_display import footer_triage_lines


def write_run_footer(
    *,
    durable_id: str | None,
    state: str,
    exit_code: int,
    duration_ms: int,
    compact: bool,
    tail_lines: int,
    stdout_sink: BoundedLogSink | None,
    stderr_sink: BoundedLogSink | None,
    stages: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    truncation: list[str] | None = None,
    triage: dict[str, Any] | None = None,
    triage_enabled: bool = False,
    tail_text: str | None = None,
) -> None:
    """Render the terminal footer for a settled run.

    Live executors pass their ``BoundedLogSink`` pair for the failure tail;
    a ledger caller with no live sinks passes ``tail_text`` instead (read
    with :func:`ledger_tail_text` from the run's output of record).
    """
    dropped = 0
    if stdout_sink is not None:
        dropped += stdout_sink.dropped
    if stderr_sink is not None:
        dropped += stderr_sink.dropped
    attribution = (
        unattributed_from_stages(list(stages), duration_ms) if stages else None
    )
    if compact:
        line = f"{state}"
        if exit_code:
            line += f"/{exit_code}"
        line += f"  {duration_ms}ms\n"
        write_display(sys.stderr, line.encode())
        if attribution is not None:
            write_display(
                sys.stderr, f"{format_unattributed_line(attribution)}\n".encode()
            )
        if state != "succeeded" and tail_lines > 0:
            if stdout_sink is not None or stderr_sink is not None:
                tail = _compact_tail_text(stdout_sink, stderr_sink, tail_lines)
            else:
                tail = tail_text or ""
            if tail:
                write_display(sys.stderr, tail.encode("utf-8", "replace"))
                if not tail.endswith("\n"):
                    write_display(sys.stderr, b"\n")
        for line in truncation or ():
            write_display(sys.stderr, f"{line}\n".encode())
        triage_lines, verdict = (
            footer_triage_lines(triage, exit_code=exit_code)
            if triage_enabled
            else ([], None)
        )
        for line in triage_lines:
            write_display(sys.stderr, f"{line}\n".encode())
        if durable_id:
            write_display(
                sys.stderr,
                f"sase tool show {durable_id} -l\n".encode(),
            )
        if verdict is not None:
            write_display(sys.stderr, f"{verdict}\n".encode())
        return
    extra = f"  dropped={dropped}B" if dropped else ""
    write_display(
        sys.stderr,
        f"{state}  exit={exit_code}  duration={duration_ms}ms{extra}\n".encode(),
    )
    if attribution is not None:
        write_display(sys.stderr, f"{format_unattributed_line(attribution)}\n".encode())
    if triage_enabled:
        _lines, verdict = footer_triage_lines(triage, exit_code=exit_code)
        for line in _lines:
            write_display(sys.stderr, f"{line}\n".encode())
        if verdict is not None:
            write_display(sys.stderr, f"{verdict}\n".encode())


def _compact_tail_text(
    stdout_sink: BoundedLogSink | None,
    stderr_sink: BoundedLogSink | None,
    tail_lines: int,
) -> str:
    parts: list[str] = []
    if stdout_sink is not None:
        parts.append(stdout_sink.tail_text(tail_lines))
    if stderr_sink is not None:
        parts.append(stderr_sink.tail_text(tail_lines))
    combined = "".join(parts)
    if not combined:
        return ""
    lines = combined.splitlines(keepends=True)
    return "".join(lines[-tail_lines:])


def ledger_tail_text(run: dict[str, Any], tail_lines: int) -> str:
    """Return the last *tail_lines* lines of a run's output of record.

    A ledger follower has no live ``BoundedLogSink`` pair, and must not
    open one on the proc log (its constructor truncates the file), so the
    failure tail is reread from ``output_paths_for_run`` instead.
    """

    if tail_lines <= 0:
        return ""
    from sase.tool.control_outputs import output_paths_for_run

    try:
        paths = output_paths_for_run(run)
    except Exception:  # noqa: BLE001 - a missing tail never blocks the footer.
        return ""
    chunks: list[str] = []
    for path in paths:
        text = _tail_of_record_path(path, tail_lines)
        if text:
            chunks.append(text)
    combined = "".join(chunks)
    if not combined:
        return ""
    return "".join(combined.splitlines(keepends=True)[-tail_lines:])


def _tail_of_record_path(path: Path, lines: int) -> str:
    if lines <= 0:
        return ""
    try:
        if not path.is_file():
            return ""
        # Proc logs rotate to a `.1` sibling; the wait tail reads both
        # segments, so the footer tail does too.
        rotated = path.with_name(f"{path.name}.1")
        prior = _tail_of_file(rotated, lines) if rotated.is_file() else ""
        current = _tail_of_file(path, lines)
        merged = "".join((prior, current)).splitlines(keepends=True)[-lines:]
        return "".join(merged)
    except OSError:
        return ""


def _tail_of_file(path: Path, lines: int) -> str:
    try:
        with open(path, "rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            block = 8192
            data = b""
            while len(data.splitlines()) <= lines and size > 0:
                step = min(block, size)
                size -= step
                handle.seek(size)
                data = handle.read(step) + data
                if size == 0:
                    break
                block *= 2
    except OSError:
        return ""
    return data.decode("utf-8", "replace")


def write_display(stream: TextIO, data: bytes) -> None:
    buffer = getattr(stream, "buffer", None)
    try:
        if buffer is not None:
            buffer.write(data)
            buffer.flush()
        else:
            stream.write(data.decode("utf-8", "replace"))
            stream.flush()
    except OSError:
        pass


def duration_ms_since(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))


def warn_once(message: str) -> None:
    print(message, file=sys.stderr)


__all__ = [
    "duration_ms_since",
    "ledger_tail_text",
    "warn_once",
    "write_display",
    "write_run_footer",
]
