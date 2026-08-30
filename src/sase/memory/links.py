"""Scanner for authored ``[[...]]`` memory links."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
import re

from sase.xprompt._literal_zones import code_literal_ranges

_MEMORY_LINK_RE = re.compile(r"!?\[\[([^\]\n]+)\]\]")


@dataclass(frozen=True, slots=True)
class MemoryLink:
    """One authored memory link found in a memory body."""

    raw: str
    target: str
    inline: bool
    span: tuple[int, int]


def scan_memory_links(body: str) -> tuple[MemoryLink, ...]:
    """Return authored memory links in *body*, skipping Markdown code zones."""

    if "[[" not in body:
        return ()

    links: list[MemoryLink] = []
    seen: set[tuple[str, bool]] = set()
    protected_ranges = _merge_ranges(code_literal_ranges(body))
    for match in _matches_outside_ranges(_MEMORY_LINK_RE, body, protected_ranges):
        target = match.group(1).strip()
        if not target:
            continue
        inline = match.group(0).startswith("!")
        key = (target, inline)
        if key in seen:
            continue
        seen.add(key)
        links.append(
            MemoryLink(
                raw=match.group(0),
                target=target,
                inline=inline,
                span=(match.start(), match.end()),
            )
        )
    return tuple(links)


def _merge_ranges(ranges: Sequence[tuple[int, int]]) -> tuple[tuple[int, int], ...]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1]:
            previous_start, previous_end = merged[-1]
            merged[-1] = (previous_start, max(previous_end, end))
            continue
        merged.append((start, end))
    return tuple(merged)


def _matches_outside_ranges(
    pattern: re.Pattern[str],
    text: str,
    ranges: Sequence[tuple[int, int]],
) -> Iterator[re.Match[str]]:
    cursor = 0
    for start, end in ranges:
        if cursor < start:
            yield from pattern.finditer(text, cursor, start)
        cursor = max(cursor, end)
    if cursor < len(text):
        yield from pattern.finditer(text, cursor)


__all__ = [
    "MemoryLink",
    "scan_memory_links",
]
