"""Shared matched-run rendering for completion surfaces."""

from __future__ import annotations

from collections.abc import Sequence
from itertools import pairwise

from rich.text import Text


MATCH_STYLE = "bold #FFD700"
DIR_STYLE = "bold #87D7FF"
FILE_BASENAME_STYLE = "bold"
DIR_PORTION_STYLE = "dim"


def append_highlighted(
    content: Text,
    text: str,
    runs: Sequence[tuple[int, int]],
    *,
    base_style: str,
    match_style: str = MATCH_STYLE,
    segment_split: int = 0,
    dim_style: str = DIR_PORTION_STYLE,
    cellwise: bool = False,
) -> None:
    """Append *text* with bounded match spans and an optional dim prefix.

    ``runs`` are half-open character ranges. Invalid and overlapping ranges are
    normalized so this presentation helper stays safe at the wire boundary.
    ``cellwise`` preserves the legacy finder raster by emitting one span per
    character while still using the shared run/style normalization.
    """
    text_length = len(text)
    normalized: list[tuple[int, int]] = []
    for raw_start, raw_end in sorted(runs):
        start = max(0, min(text_length, raw_start))
        end = max(start, min(text_length, raw_end))
        if start == end:
            continue
        if normalized and start <= normalized[-1][1]:
            previous_start, previous_end = normalized[-1]
            normalized[-1] = (previous_start, max(previous_end, end))
        else:
            normalized.append((start, end))

    split = max(0, min(text_length, segment_split))
    boundaries = {0, text_length}
    if split:
        boundaries.add(split)
    for start, end in normalized:
        boundaries.add(start)
        boundaries.add(end)

    ordered = sorted(boundaries)
    run_index = 0
    for start, end in pairwise(ordered):
        if start == end:
            continue
        while run_index < len(normalized) and normalized[run_index][1] <= start:
            run_index += 1
        matched = (
            run_index < len(normalized)
            and normalized[run_index][0] <= start
            and end <= normalized[run_index][1]
        )
        style = (
            match_style
            if matched
            else dim_style
            if split and start < split
            else base_style
        )
        segment = text[start:end]
        if cellwise:
            for char in segment:
                content.append(char, style=style)
        else:
            content.append(segment, style=style)
