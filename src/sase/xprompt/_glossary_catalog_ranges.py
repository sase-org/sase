"""Source ranges for glossary config nodes, derived from round-trip YAML.

The ranges are LSP-shaped (zero-based line/character start and end pairs) and
are built from the ``lc`` location data ruamel attaches to round-trip mappings.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def key_range(node: Mapping[Any, Any], key: str) -> dict[str, object] | None:
    """Return the range covering *key* itself within *node*."""

    location = _node_key_location(node, key)
    if location is None:
        return None
    line, column, _, _ = location
    return {
        "start": {"line": line, "character": column},
        "end": {"line": line, "character": column + len(key)},
    }


def value_range(
    node: Mapping[Any, Any],
    key: str,
    lines: Sequence[str],
) -> dict[str, object] | None:
    """Return the range covering *key*'s value, including block continuations."""

    location = _node_key_location(node, key)
    if location is None:
        return None
    key_line, key_col, value_line, value_col = location
    end_line = _block_end(lines, key_line, key_col) - 1
    end_line = max(value_line, min(end_line, len(lines) - 1)) if lines else value_line
    end_char = len(lines[end_line]) if 0 <= end_line < len(lines) else value_col
    return {
        "start": {"line": value_line, "character": value_col},
        "end": {"line": end_line, "character": end_char},
    }


def _node_key_location(
    node: Mapping[Any, Any],
    key: str,
) -> tuple[int, int, int, int] | None:
    data = getattr(getattr(node, "lc", None), "data", None)
    if not isinstance(data, dict):
        return None
    location = data.get(key)
    if not isinstance(location, list | tuple) or len(location) < 4:
        return None
    try:
        return (
            int(location[0]),
            int(location[1]),
            int(location[2]),
            int(location[3]),
        )
    except (TypeError, ValueError):
        return None


def _block_end(lines: Sequence[str], start_line: int, indent: int) -> int:
    if not lines or start_line < 0 or start_line >= len(lines):
        return start_line + 1
    last_content_end = start_line + 1
    for index in range(start_line + 1, len(lines)):
        line = lines[index]
        stripped = line.strip()
        if stripped and _line_indent(line) <= indent:
            break
        if stripped:
            last_content_end = index + 1
    return last_content_end


def _line_indent(line: str) -> int:
    return len(line) - len(line.lstrip(" \t"))
