"""Terminal presentation helpers for the ToolRun executor."""

from __future__ import annotations

import sys
import time
from typing import Any, TextIO

from sase.tool.logs import BoundedLogSink
from sase.tool.stage_protocol import (
    format_unattributed_line,
    unattributed_from_stages,
)


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
) -> None:
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
            tail = _compact_tail_text(stdout_sink, stderr_sink, tail_lines)
            if tail:
                write_display(sys.stderr, tail.encode("utf-8", "replace"))
                if not tail.endswith("\n"):
                    write_display(sys.stderr, b"\n")
        for line in truncation or ():
            write_display(sys.stderr, f"{line}\n".encode())
        if durable_id:
            write_display(
                sys.stderr,
                f"sase tool show {durable_id} -l\n".encode(),
            )
        return
    extra = f"  dropped={dropped}B" if dropped else ""
    write_display(
        sys.stderr,
        f"{state}  exit={exit_code}  duration={duration_ms}ms{extra}\n".encode(),
    )
    if attribution is not None:
        write_display(sys.stderr, f"{format_unattributed_line(attribution)}\n".encode())


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
    "warn_once",
    "write_display",
    "write_run_footer",
]
