"""Output extraction helpers for frozen monitor follow-up prompts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .diagnostics import read_retained_log_range
from .result_projection import selected_raw_limits


def frozen_output_text(
    artifacts_dir: str,
    *,
    result: Mapping[str, Any],
    selection: Mapping[str, Any],
    fallback: str,
) -> str:
    raw_limits = selected_raw_limits(selection, requested_tail_lines=10_000)
    if raw_limits is None:
        return ""
    _tail_lines, max_chars = raw_limits
    retained_log = result.get("retained_log")
    if not isinstance(retained_log, Mapping):
        return fallback
    ranges = retained_log.get("retained_ranges")
    if not isinstance(ranges, list) or not ranges:
        return fallback
    chunks: list[str] = []
    remaining = max_chars
    for item in ranges:
        if remaining <= 0:
            break
        if not isinstance(item, Mapping):
            continue
        start = _int_value(item.get("start"))
        end = _int_value(item.get("end"))
        if start is None or end is None or end <= start:
            continue
        read = read_retained_log_range(
            artifacts_dir,
            start=start,
            end=end,
            max_bytes=remaining,
        )
        chunks.append(read.text)
        remaining = max(0, max_chars - len("".join(chunks).encode("utf-8")))
    text = "".join(chunks)
    return text if text else fallback


def _int_value(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


__all__ = ["frozen_output_text"]
