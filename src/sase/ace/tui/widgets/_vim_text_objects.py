"""Vim quote/bracket text object and matching-bracket helpers."""

from __future__ import annotations

from typing import Any

Location = tuple[int, int]
TextRange = tuple[int, int, int, int]

_QUOTE_CHARS = {"'", '"', "`"}
_OPEN_TO_CLOSE = {
    "(": ")",
    "[": "]",
    "{": "}",
    "<": ">",
}
_CLOSE_TO_OPEN = {close: open_ for open_, close in _OPEN_TO_CLOSE.items()}
_BRACKET_ALIASES = {
    "(": ("(", ")"),
    ")": ("(", ")"),
    "b": ("(", ")"),
    "[": ("[", "]"),
    "]": ("[", "]"),
    "{": ("{", "}"),
    "}": ("{", "}"),
    "B": ("{", "}"),
    "<": ("<", ">"),
    ">": ("<", ">"),
}
_BRACKET_CHARS = set(_OPEN_TO_CLOSE) | set(_CLOSE_TO_OPEN)


def location_after_char(doc: Any, location: Location) -> Location:
    """Return the exclusive location immediately after *location*."""
    row, col = location
    line = doc.get_line(row)
    if col < len(line):
        return (row, col + 1)
    return (row, col)


def is_quote_or_bracket_text_object_key(key: str) -> bool:
    """Return whether *key* can finish an ``a``/``i`` quote/bracket object."""
    return key in _QUOTE_CHARS or key in _BRACKET_ALIASES


def find_quote_or_bracket_text_object(
    doc: Any,
    row: int,
    col: int,
    prefix: str,
    key: str,
    count: int = 1,
) -> TextRange | None:
    """Find a quote/bracket text object range.

    Returns ``(start_row, start_col, end_row, end_col)`` with end exclusive.
    ``prefix`` is ``i`` for inner objects or ``a`` for around objects.
    """
    count = max(1, count)
    inner = prefix == "i"
    if key in _QUOTE_CHARS:
        return _find_quote_text_object(doc, row, col, key, inner=inner, count=count)
    if key in _BRACKET_ALIASES:
        open_char, close_char = _BRACKET_ALIASES[key]
        return _find_bracket_text_object(
            doc,
            row,
            col,
            open_char,
            close_char,
            inner=inner,
            count=count,
        )
    return None


def _find_quote_text_object(
    doc: Any,
    row: int,
    col: int,
    quote: str,
    *,
    inner: bool,
    count: int = 1,
) -> TextRange | None:
    """Find a single-line quote text object."""
    line = doc.get_line(row)
    pairs = _quote_pairs(line, quote)
    if not pairs:
        return None

    pair_index = _quote_pair_index_at_or_after(pairs, col)
    if pair_index is None:
        return None

    end_index = min(pair_index + max(1, count) - 1, len(pairs) - 1)
    start_quote = pairs[pair_index][0]
    end_quote = pairs[end_index][1]
    if inner:
        return (row, start_quote + 1, row, end_quote)

    start = start_quote
    end = end_quote + 1
    trailing = end
    while trailing < len(line) and line[trailing].isspace():
        trailing += 1
    if trailing > end:
        end = trailing
    else:
        while start > 0 and line[start - 1].isspace():
            start -= 1
    return (row, start, row, end)


def _quote_pairs(line: str, quote: str) -> list[tuple[int, int]]:
    positions: list[int] = []
    for index, char in enumerate(line):
        if char == quote and not _is_escaped(line, index):
            positions.append(index)
    return [
        (positions[index], positions[index + 1])
        for index in range(0, len(positions) - 1, 2)
    ]


def _is_escaped(line: str, index: int) -> bool:
    backslashes = 0
    cursor = index - 1
    while cursor >= 0 and line[cursor] == "\\":
        backslashes += 1
        cursor -= 1
    return backslashes % 2 == 1


def _quote_pair_index_at_or_after(
    pairs: list[tuple[int, int]],
    col: int,
) -> int | None:
    for index, (start, end) in enumerate(pairs):
        if start <= col <= end or start >= col:
            return index
    return None


def _find_bracket_text_object(
    doc: Any,
    row: int,
    col: int,
    open_char: str,
    close_char: str,
    *,
    inner: bool,
    count: int = 1,
) -> TextRange | None:
    """Find an innermost enclosing bracket text object."""
    cursor = (row, col)
    candidates = _enclosing_bracket_pairs(doc, cursor, open_char, close_char)
    if not candidates:
        return None
    candidate_index = min(max(1, count) - 1, len(candidates) - 1)
    open_loc, close_loc = candidates[candidate_index]
    if inner:
        start = location_after_char(doc, open_loc)
        end = close_loc
    else:
        start = open_loc
        end = location_after_char(doc, close_loc)
    return (start[0], start[1], end[0], end[1])


def _enclosing_bracket_pairs(
    doc: Any,
    cursor: Location,
    open_char: str,
    close_char: str,
) -> list[tuple[Location, Location]]:
    flat = _flat_chars(doc)
    location_index = {location: index for index, (location, _char) in enumerate(flat)}
    stack: list[Location] = []
    candidates: list[tuple[Location, Location]] = []
    for location, char in flat:
        if char == open_char:
            stack.append(location)
        elif char == close_char and stack:
            open_loc = stack.pop()
            if open_loc <= cursor <= location:
                candidates.append((open_loc, location))

    return sorted(
        candidates,
        key=lambda pair: location_index[pair[1]] - location_index[pair[0]],
    )


def find_matching_bracket(
    doc: Any, row: int, col: int
) -> tuple[Location, Location] | None:
    """Find the bracket at/after the cursor on this line and its match.

    Returns ``(bracket_location, matching_location)``.
    """
    bracket_loc = _find_bracket_at_or_after_on_line(doc, row, col)
    if bracket_loc is None:
        return None

    line = doc.get_line(bracket_loc[0])
    bracket = line[bracket_loc[1]]
    flat = _flat_chars(doc)
    start_index = _flat_index(flat, bracket_loc)
    if start_index is None:
        return None

    if bracket in _OPEN_TO_CLOSE:
        match = _find_forward_match(
            flat,
            start_index,
            bracket,
            _OPEN_TO_CLOSE[bracket],
        )
    else:
        match = _find_backward_match(
            flat,
            start_index,
            _CLOSE_TO_OPEN[bracket],
            bracket,
        )
    if match is None:
        return None
    return (bracket_loc, match)


def _find_bracket_at_or_after_on_line(
    doc: Any,
    row: int,
    col: int,
) -> Location | None:
    if row < 0 or row >= doc.line_count:
        return None
    line = doc.get_line(row)
    for target_col in range(max(0, col), len(line)):
        if line[target_col] in _BRACKET_CHARS:
            return (row, target_col)
    return None


def _flat_chars(doc: Any) -> list[tuple[Location, str]]:
    chars: list[tuple[Location, str]] = []
    for row in range(doc.line_count):
        line = doc.get_line(row)
        for col, char in enumerate(line):
            chars.append(((row, col), char))
    return chars


def _flat_index(
    flat: list[tuple[Location, str]],
    location: Location,
) -> int | None:
    for index, (candidate, _char) in enumerate(flat):
        if candidate == location:
            return index
    return None


def _find_forward_match(
    flat: list[tuple[Location, str]],
    start_index: int,
    open_char: str,
    close_char: str,
) -> Location | None:
    depth = 0
    for location, char in flat[start_index:]:
        if char == open_char:
            depth += 1
        elif char == close_char:
            depth -= 1
            if depth == 0:
                return location
    return None


def _find_backward_match(
    flat: list[tuple[Location, str]],
    start_index: int,
    open_char: str,
    close_char: str,
) -> Location | None:
    depth = 0
    for location, char in reversed(flat[: start_index + 1]):
        if char == close_char:
            depth += 1
        elif char == open_char:
            depth -= 1
            if depth == 0:
                return location
    return None
