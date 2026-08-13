"""Hierarchical section numbering for generated agent instruction files."""

from __future__ import annotations

from ._headings import fence_marker, heading_level, iter_headings


def _split_line_ending(line: str) -> tuple[str, str]:
    if line.endswith("\r\n"):
        return line[:-2], "\r\n"
    if line.endswith("\n"):
        return line[:-1], "\n"
    if line.endswith("\r"):
        return line[:-1], "\r"
    return line, ""


def _section_prefix(counters: list[int]) -> str:
    prefix = ".".join(str(counter) for counter in counters)
    if len(counters) == 1:
        return f"{prefix}."
    return prefix


def _numbered_heading(line: str, level: int, counters: list[int]) -> str:
    text = line[level:].strip()
    heading = f"{'#' * level} {_section_prefix(counters)}"
    if text:
        return f"{heading} {text}"
    return heading


def number_agent_document_sections(text: str) -> str:
    """Return *text* with every heading below the title hierarchically numbered."""
    heading_levels = [level for level, _ in iter_headings(text) if level >= 2]
    if not heading_levels:
        return text
    base_level = min(heading_levels)

    result: list[str] = []
    counters: list[int] = []
    in_fence = False
    active_fence_marker = ""
    for raw_line in text.splitlines(keepends=True):
        line, ending = _split_line_ending(raw_line)
        marker = fence_marker(line)
        if in_fence:
            result.append(raw_line)
            if marker == active_fence_marker:
                in_fence = False
            continue
        if marker is not None:
            in_fence = True
            active_fence_marker = marker
            result.append(raw_line)
            continue

        level = heading_level(line)
        if level is None or level < base_level:
            result.append(raw_line)
            continue

        depth = level - base_level + 1
        while len(counters) < depth:
            counters.append(0)
        del counters[depth:]
        counters[depth - 1] += 1
        result.append(_numbered_heading(line, level, counters) + ending)

    return "".join(result)


__all__ = [
    "number_agent_document_sections",
]
