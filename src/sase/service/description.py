"""Lenient description split for service procs.

Service proc descriptions use the AXE description grammar (summary line, blank
line, optional body) for display, but unlike routine/job descriptions they are
not shape-validated in the Rust core. The core ``split_axe_description`` ignores
line 2 by design (it splits on ``lines[0]`` + ``lines[2..]``), so a description
written without the blank separator would silently drop line 2. This adapter
inserts the missing blank line so no authored text is lost, then delegates to
the core split.
"""

from __future__ import annotations

import functools

from sase.core.axe_chop_facade import split_axe_description


@functools.lru_cache(maxsize=128)
def split_service_description(description: str | None) -> tuple[str, str]:
    """Split a service proc description into ``(summary, body)``.

    Returns ``("", "")`` for ``None`` or blank input. Normalizes CRLF/CR to LF
    first; when the normalized text has a non-blank line 2, a blank line is
    inserted after line 1 so the whole remainder becomes the body.
    """
    if description is None:
        return ("", "")
    normalized = description.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.strip():
        return ("", "")
    lines = normalized.split("\n")
    if len(lines) >= 2 and lines[1].strip():
        normalized = lines[0] + "\n\n" + "\n".join(lines[1:])
    return split_axe_description(normalized)
