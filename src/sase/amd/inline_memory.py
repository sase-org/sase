"""Pure helpers for inlining short-term memory notes into ``AGENTS.md``.

These functions are dependency-free building blocks consumed by ``sase memory
init`` (wired up in a later phase). They translate a memory note's Markdown body
into the inlined ``### Title (file)`` section shape, or the numbered
``### N. Title (file)`` section shape, used inside the ``## Tier 1
(short-term) Memory`` block. When a note number is supplied, H2 and H3 body
headings are also numbered as ``N.S`` and ``N.S.T`` after they are shifted down
two levels. These helpers also validate that a short note's heading structure can
be inlined safely.

Heading detection is *fence-aware*: ``#`` characters at the start of lines inside
fenced code blocks (for example ``# comment`` lines in a ``bash`` block) are
content, never headings. The fence handling mirrors
``sase.main.init_memory.formatting.format_generated_memory_markdown`` rather than
the non-fence-aware ``sase.history.chat._increment_markdown_headings``.
"""

from __future__ import annotations

import re
from pathlib import Path

_FENCE_MARKERS = ("```", "~~~")
_HEADING_RE = re.compile(r"^(#+)(?:[ \t]|$)")


def _fence_marker(line: str) -> str | None:
    """Return the fence marker (``` ``` ``` or ``~~~``) opening/closing *line*."""
    stripped = line.lstrip()
    for marker in _FENCE_MARKERS:
        if stripped.startswith(marker):
            return marker
    return None


def _heading_level(line: str) -> int | None:
    """Return the ATX heading level of *line*, or ``None`` if it is not one.

    Headings are recognized only at column zero (matching how canonical memory
    notes are authored) and must be followed by whitespace or end-of-line.
    """
    match = _HEADING_RE.match(line)
    if match is None:
        return None
    return len(match.group(1))


def _iter_headings(body: str) -> list[tuple[int, str]]:
    """Return ``(level, line)`` for every heading outside fenced code blocks."""
    headings: list[tuple[int, str]] = []
    in_fence = False
    fence_marker = ""
    for line in body.splitlines():
        marker = _fence_marker(line)
        if in_fence:
            if marker == fence_marker:
                in_fence = False
            continue
        if marker is not None:
            in_fence = True
            fence_marker = marker
            continue
        level = _heading_level(line)
        if level is not None:
            headings.append((level, line))
    return headings


def _extract_memory_title(body: str) -> str | None:
    """Return the text of the first H1 (``# ``) heading in *body*, fence-aware.

    Returns ``None`` when *body* contains no H1 heading outside a fenced block.
    """
    for level, line in _iter_headings(body):
        if level == 1:
            return line.lstrip("#").strip()
    return None


def validate_short_memory_structure(body: str) -> str | None:
    """Validate that *body* can be inlined as a short-term memory section.

    Returns an error message describing the first structural violation, or
    ``None`` when *body* is valid. The contract enforced is:

    - exactly one H1 (``# ``) heading, and it is the first heading,
    - headings only at H1/H2/H3 (no H4 or deeper),
    - ``#`` characters inside fenced code blocks are ignored.
    """
    headings = _iter_headings(body)
    if not headings or headings[0][0] != 1:
        return "short memory note must begin with a single H1 (`# Title`) heading"
    h1_count = sum(1 for level, _ in headings if level == 1)
    if h1_count != 1:
        return (
            "short memory note must contain exactly one H1 (`# `) heading, "
            f"found {h1_count}"
        )
    for level, line in headings:
        if level > 3:
            return (
                "short memory note must not contain headings deeper than H3; "
                f"found {line.strip()!r}"
            )
    return None


def _numbered_heading(line: str, level: int, prefix: str | None) -> str:
    """Return *line* shifted two levels, with *prefix* before its text."""
    text = line[level:].strip()
    hashes = "#" * (level + 2)
    parts = [part for part in (hashes, prefix, text) if part]
    return " ".join(parts)


def _shift_body(body: str, *, number: int | None = None) -> list[str]:
    """Strip the first H1 and shift remaining headings +2, fence-aware.

    Code fences (and their contents) are copied verbatim. Leading and trailing
    blank lines are trimmed so the result embeds cleanly under a section header.
    When *number* is provided, H2 headings are numbered ``N.S`` and H3 headings
    are numbered ``N.S.T``.
    """
    result: list[str] = []
    in_fence = False
    fence_marker = ""
    h1_consumed = False
    section_number = 0
    subsection_number = 0
    for line in body.splitlines():
        marker = _fence_marker(line)
        if in_fence:
            result.append(line)
            if marker == fence_marker:
                in_fence = False
            continue
        if marker is not None:
            in_fence = True
            fence_marker = marker
            result.append(line)
            continue
        level = _heading_level(line)
        if level is not None:
            if level == 1 and not h1_consumed:
                h1_consumed = True
                continue
            prefix = None
            if number is not None and level == 2:
                section_number += 1
                subsection_number = 0
                prefix = f"{number}.{section_number}"
            elif number is not None and level == 3:
                subsection_number += 1
                prefix = f"{number}.{section_number}.{subsection_number}"
            result.append(_numbered_heading(line, level, prefix))
            continue
        result.append(line)

    while result and not result[0].strip():
        result.pop(0)
    while result and not result[-1].strip():
        result.pop()
    return result


def inline_memory_section(
    relative_path: str,
    body: str,
    *,
    number: int | None = None,
) -> str:
    """Render *body* as an inlined Tier 1 memory section for *relative_path*.

    The note's H1 title is consumed into the section header
    ``### {title} ({basename})``. When *number* is provided, the header is
    prefixed as ``### {number}. {title} ({basename})``. The remaining body has
    every heading shifted down two levels (H2->H4, H3->H5) with code fences
    copied verbatim; numbered sections become ``{number}.{section}`` and nested
    subsections become ``{number}.{section}.{subsection}``. If the body has no
    title, the header falls back to ``### {basename}`` or
    ``### {number}. {basename}``. The returned block ends with a single trailing
    newline.
    """
    title = _extract_memory_title(body)
    basename = Path(relative_path).stem
    prefix = f"{number}. " if number is not None else ""
    if title:
        header = f"### {prefix}{title} ({basename})"
    else:
        header = f"### {prefix}{basename}"
    transformed = _shift_body(body, number=number)
    if transformed:
        return header + "\n\n" + "\n".join(transformed) + "\n"
    return header + "\n"


__all__ = [
    "inline_memory_section",
    "validate_short_memory_structure",
]
