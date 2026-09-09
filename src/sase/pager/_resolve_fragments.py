"""Fragment parsing for pager file-path links."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote

_LINE_FRAGMENT_RE = re.compile(r"L(\d+)(?:-L?\d+)?", re.IGNORECASE)
_HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$")
_MARKDOWN_SUFFIXES = frozenset({".md", ".markdown", ".mdown", ".mkd"})


def fragment_target_line(
    path: Path,
    fragment: str | None,
) -> tuple[int | None, str | None]:
    if fragment is None:
        return None, None
    decoded = unquote(fragment)
    if not decoded:
        return None, None
    line_match = _LINE_FRAGMENT_RE.fullmatch(decoded)
    if line_match is not None:
        return int(line_match.group(1)), None
    if decoded[:1].lower() == "l" and any(char.isdigit() for char in decoded):
        return None, f"fragment #{decoded} is not a supported line fragment for {path}"
    if not _is_markdown_path(path):
        return None, f"fragment #{decoded} is not supported for {path}"
    line = _heading_fragment_line(path, decoded)
    if line is None:
        return None, f"fragment #{decoded} was not found in {path}"
    return line, None


def _is_markdown_path(path: Path) -> bool:
    return path.suffix.lower() in _MARKDOWN_SUFFIXES


def _heading_fragment_line(path: Path, fragment: str) -> int | None:
    wanted = _heading_slug(fragment)
    if not wanted:
        return None
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    seen: dict[str, int] = {}
    for line_number, line in enumerate(lines, start=1):
        match = _HEADING_RE.match(line)
        if match is None:
            continue
        base = _heading_slug(match.group(1))
        if not base:
            continue
        ordinal = seen.get(base, 0)
        seen[base] = ordinal + 1
        slug = base if ordinal == 0 else f"{base}-{ordinal}"
        if slug == wanted:
            return line_number
    return None


def _heading_slug(text: str) -> str:
    output: list[str] = []
    last_dash = False
    for character in text.strip().lower():
        if character.isspace() or character == "-":
            if output and not last_dash:
                output.append("-")
                last_dash = True
            continue
        if character.isalnum() or character == "_":
            output.append(character)
            last_dash = False
    while output and output[-1] == "-":
        output.pop()
    return "".join(output)


__all__ = ["fragment_target_line"]
