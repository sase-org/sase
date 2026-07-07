"""Bounded diagnostics for provider subprocess stream parsing."""

from __future__ import annotations

import os
from json import JSONDecodeError

from ._tool_call_io import append_tool_call_collector_diagnostic

_MAX_STDOUT_JSON_DECODE_DIAGNOSTICS = 5
_stdout_json_decode_counts: dict[tuple[str, str], int] = {}


def record_stdout_json_decode_diagnostic(
    runtime: str,
    line: str,
    exc: JSONDecodeError,
) -> None:
    """Record a bounded diagnostic for a stdout line that is not valid JSON."""
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not artifacts_dir:
        return

    key = (artifacts_dir, runtime)
    count = _stdout_json_decode_counts.get(key, 0)
    if count >= _MAX_STDOUT_JSON_DECODE_DIAGNOSTICS:
        return
    _stdout_json_decode_counts[key] = count + 1

    append_tool_call_collector_diagnostic(
        artifacts_dir,
        reason=f"{runtime}_stdout_json_decode_error",
        raw_preview=line,
        extra={
            "error": exc.msg,
            "line_length": len(line),
        },
    )


__all__ = ["record_stdout_json_decode_diagnostic"]
