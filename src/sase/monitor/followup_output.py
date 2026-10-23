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
    selected_ranges: list[tuple[int, int]] = []
    remaining = max_chars
    for item in reversed(ranges):
        if remaining <= 0:
            break
        if not isinstance(item, Mapping):
            continue
        start = _int_value(item.get("start"))
        end = _int_value(item.get("end"))
        if start is None or end is None or end <= start:
            continue
        selected_start = max(start, end - remaining)
        if selected_start >= end:
            continue
        selected_ranges.append((selected_start, end))
        remaining -= end - selected_start
    chunks: list[str] = []
    previous_end: int | None = None
    for start, end in reversed(selected_ranges):
        if previous_end is not None and previous_end < start:
            chunks.append(
                f"\n[retained output gap: bytes {previous_end}:{start} are unavailable]\n"
            )
        read = read_retained_log_range(
            artifacts_dir,
            start=start,
            end=end,
            max_bytes=end - start,
        )
        chunks.append(read.text)
        previous_end = end
    text = "".join(chunks)
    return text if text else fallback


def _int_value(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


__all__ = ["frozen_output_text"]
