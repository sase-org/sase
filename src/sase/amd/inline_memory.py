"""Pure helpers for inlining core memory notes into ``AGENTS.md``.

These functions translate a memory note's Markdown body into the inlined
``### Title (file)`` section shape used inside the Core Memory and Memory
Webs blocks. They also validate that an inlined note's heading structure can
be inlined safely. Generated agent-document headings are numbered by the
document-wide pass in ``sase.amd._section_numbers`` after template rendering.

Heading detection is *fence-aware*: ``#`` characters at the start of lines inside
fenced code blocks (for example ``# comment`` lines in a ``bash`` block) are
content, never headings. The fence handling mirrors
``sase.main.init_memory.formatting.format_generated_memory_markdown`` rather than
the non-fence-aware ``sase.history.chat._increment_markdown_headings``.
"""

from __future__ import annotations

from pathlib import Path

from ._headings import fence_marker, heading_level, iter_headings


def _extract_memory_title(body: str) -> str | None:
    """Return the text of the first H1 (``# ``) heading in *body*, fence-aware.

    Returns ``None`` when *body* contains no H1 heading outside a fenced block.
    """
    for level, line in iter_headings(body):
        if level == 1:
            return line.lstrip("#").strip()
    return None


def validate_short_memory_structure(body: str) -> str | None:
    """Validate that *body* can be inlined as a core memory section.

    Returns an error message describing the first structural violation, or
    ``None`` when *body* is valid. The contract enforced is:

    - exactly one H1 (``# ``) heading, and it is the first heading,
    - headings only at H1/H2/H3 (no H4 or deeper),
    - ``#`` characters inside fenced code blocks are ignored.
    """
    headings = iter_headings(body)
    if not headings or headings[0][0] != 1:
        return "core memory note must begin with a single H1 (`# Title`) heading"
    h1_count = sum(1 for level, _ in headings if level == 1)
    if h1_count != 1:
        return (
            "core memory note must contain exactly one H1 (`# `) heading, "
            f"found {h1_count}"
        )
    for level, line in headings:
        if level > 3:
            return (
                "core memory note must not contain headings deeper than H3; "
                f"found {line.strip()!r}"
            )
    return None


def _shifted_heading(line: str, level: int) -> str:
    """Return *line* shifted two levels."""
    text = line[level:].strip()
    hashes = "#" * (level + 2)
    if text:
        return f"{hashes} {text}"
    return hashes


def _shift_body(body: str) -> list[str]:
    """Strip the first H1 and shift remaining headings +2, fence-aware.

    Code fences (and their contents) are copied verbatim. Leading and trailing
    blank lines are trimmed so the result embeds cleanly under a section header.
    """
    result: list[str] = []
    in_fence = False
    active_fence_marker = ""
    h1_consumed = False
    for line in body.splitlines():
        marker = fence_marker(line)
        if in_fence:
            result.append(line)
            if marker == active_fence_marker:
                in_fence = False
            continue
        if marker is not None:
            in_fence = True
            active_fence_marker = marker
            result.append(line)
            continue
        level = heading_level(line)
        if level is not None:
            if level == 1 and not h1_consumed:
                h1_consumed = True
                continue
            result.append(_shifted_heading(line, level))
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
) -> str:
    """Render *body* as an inlined memory section for *relative_path*.

    The note's H1 title is consumed into the section header
    ``### {title} ({basename})``. The remaining body has
    every heading shifted down two levels (H2->H4, H3->H5) with code fences
    copied verbatim. If the body has no title, the header falls back to
    ``### {basename}``. The returned block ends with a single trailing newline.
    """
    title = _extract_memory_title(body)
    basename = Path(relative_path).stem
    if title:
        header = f"### {title} ({basename})"
    else:
        header = f"### {basename}"
    transformed = _shift_body(body)
    if transformed:
        return header + "\n\n" + "\n".join(transformed) + "\n"
    return header + "\n"


__all__ = [
    "inline_memory_section",
    "validate_short_memory_structure",
]
