"""Single-line inline-code scanning for xprompt literal zones."""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Iterable

_OPENING_CONTEXT = frozenset("([{\"'")


def inline_code_spans(
    text: str,
    *,
    masked_ranges: Iterable[tuple[int, int]] = (),
) -> list[tuple[int, int]]:
    """Return matched single-line backtick spans in *text*.

    An opener must occur at the start of a line or after the same leading
    context accepted by xprompt markers: whitespace or ``([{"'``. It closes
    at the nearest backtick run of exactly the same length on that line.
    Backtick runs that overlap *masked_ranges* cannot open or close a span.
    """
    if "`" not in text:
        return []

    masked = _merge_ranges(masked_ranges)
    spans: list[tuple[int, int]] = []
    line_start = 0
    while line_start < len(text):
        newline = text.find("\n", line_start)
        line_end = len(text) if newline == -1 else newline
        if line_end > line_start and text[line_end - 1] == "\r":
            line_end -= 1

        cursor = line_start
        while cursor < line_end:
            opener = text.find("`", cursor, line_end)
            if opener == -1:
                break
            opener_end = _backtick_run_end(text, opener, line_end)
            if not _can_open(text, opener, line_start) or _overlaps(
                opener, opener_end, masked
            ):
                cursor = opener_end
                continue

            run_length = opener_end - opener
            closer = _matching_closer(
                text,
                opener_end,
                line_end,
                run_length,
                masked,
            )
            if closer is None:
                cursor = opener_end
                continue

            _closer_start, closer_end = closer
            spans.append((opener, closer_end))
            cursor = closer_end

        if newline == -1:
            break
        line_start = newline + 1

    return spans


def _can_open(text: str, start: int, line_start: int) -> bool:
    if start == line_start:
        return True
    previous = text[start - 1]
    return previous.isspace() or previous in _OPENING_CONTEXT


def _matching_closer(
    text: str,
    start: int,
    line_end: int,
    run_length: int,
    masked: list[tuple[int, int]],
) -> tuple[int, int] | None:
    cursor = start
    while cursor < line_end:
        run_start = text.find("`", cursor, line_end)
        if run_start == -1:
            return None
        run_end = _backtick_run_end(text, run_start, line_end)
        if run_end - run_start == run_length and not _overlaps(
            run_start, run_end, masked
        ):
            return run_start, run_end
        cursor = run_end
    return None


def _backtick_run_end(text: str, start: int, line_end: int) -> int:
    end = start + 1
    while end < line_end and text[end] == "`":
        end += 1
    return end


def _overlaps(
    start: int,
    end: int,
    ranges: list[tuple[int, int]],
) -> bool:
    candidate = bisect_left(ranges, (end,)) - 1
    return candidate >= 0 and ranges[candidate][1] > start


def _merge_ranges(ranges: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted((start, end) for start, end in ranges if end > start):
        if merged and start <= merged[-1][1]:
            previous_start, previous_end = merged[-1]
            merged[-1] = (previous_start, max(previous_end, end))
        else:
            merged.append((start, end))
    return merged


__all__ = ["inline_code_spans"]
