"""Fragment parsing for pager file-path links."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote

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
    if not _is_markdown_path(path):
        return None, f"fragment #{decoded} is not supported for {path}"
    line = _heading_fragment_line(path, fragment)
    if line is None:
        return None, f"fragment #{decoded} was not found in {path}"
    return line, None


def _is_markdown_path(path: Path) -> bool:
    return path.suffix.lower() in _MARKDOWN_SUFFIXES


def _heading_fragment_line(path: Path, fragment: str) -> int | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    from sase.pager.markdown_anchors import build_markdown_anchor_index

    return build_markdown_anchor_index(text).line_for(fragment)


__all__ = ["fragment_target_line"]
