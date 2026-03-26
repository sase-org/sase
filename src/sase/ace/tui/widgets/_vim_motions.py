"""Vim-style word motion helpers for the prompt text area."""

from __future__ import annotations

from typing import Any


def _char_class(ch: str) -> str:
    """Classify a character for vim word motions."""
    if ch.isalnum() or ch == "_":
        return "word"
    if ch.isspace():
        return "space"
    return "punct"


def find_next_word_start(doc: Any, row: int, col: int) -> tuple[int, int]:
    """Find start of next word (vim 'w')."""
    line_count = doc.line_count
    line = doc.get_line(row)

    if col < len(line):
        cc = _char_class(line[col])
        if cc != "space":
            while col < len(line) and _char_class(line[col]) == cc:
                col += 1

    while True:
        while col < len(line) and line[col].isspace():
            col += 1
        if col < len(line):
            return (row, col)
        row += 1
        if row >= line_count:
            last = line_count - 1
            return (last, len(doc.get_line(last)))
        line = doc.get_line(row)
        col = 0
        if len(line) == 0:
            return (row, 0)


def find_next_WORD_start(doc: Any, row: int, col: int) -> tuple[int, int]:
    """Find start of next WORD (vim 'W')."""
    line_count = doc.line_count
    line = doc.get_line(row)

    if col < len(line) and not line[col].isspace():
        while col < len(line) and not line[col].isspace():
            col += 1

    while True:
        while col < len(line) and line[col].isspace():
            col += 1
        if col < len(line):
            return (row, col)
        row += 1
        if row >= line_count:
            last = line_count - 1
            return (last, len(doc.get_line(last)))
        line = doc.get_line(row)
        col = 0
        if len(line) == 0:
            return (row, 0)


def find_prev_word_start(doc: Any, row: int, col: int) -> tuple[int, int]:
    """Find start of previous word (vim 'b')."""
    line = doc.get_line(row)

    col -= 1
    while col < 0:
        row -= 1
        if row < 0:
            return (0, 0)
        line = doc.get_line(row)
        col = len(line) - 1
        if col < 0:
            return (row, 0)

    while True:
        while col >= 0 and line[col].isspace():
            col -= 1
        if col >= 0:
            break
        row -= 1
        if row < 0:
            return (0, 0)
        line = doc.get_line(row)
        col = len(line) - 1
        if col < 0:
            return (row, 0)

    cc = _char_class(line[col])
    while col > 0 and _char_class(line[col - 1]) == cc:
        col -= 1
    return (row, col)


def find_prev_WORD_start(doc: Any, row: int, col: int) -> tuple[int, int]:
    """Find start of previous WORD (vim 'B')."""
    line = doc.get_line(row)

    col -= 1
    while col < 0:
        row -= 1
        if row < 0:
            return (0, 0)
        line = doc.get_line(row)
        col = len(line) - 1
        if col < 0:
            return (row, 0)

    while True:
        while col >= 0 and line[col].isspace():
            col -= 1
        if col >= 0:
            break
        row -= 1
        if row < 0:
            return (0, 0)
        line = doc.get_line(row)
        col = len(line) - 1
        if col < 0:
            return (row, 0)

    while col > 0 and not line[col - 1].isspace():
        col -= 1
    return (row, col)


def find_next_word_end(doc: Any, row: int, col: int) -> tuple[int, int]:
    """Find end of next word (vim 'e')."""
    line_count = doc.line_count
    line = doc.get_line(row)

    col += 1
    while col >= len(line):
        row += 1
        if row >= line_count:
            last = line_count - 1
            return (last, max(0, len(doc.get_line(last)) - 1))
        line = doc.get_line(row)
        col = 0

    while True:
        while col < len(line) and line[col].isspace():
            col += 1
        if col < len(line):
            break
        row += 1
        if row >= line_count:
            last = line_count - 1
            return (last, max(0, len(doc.get_line(last)) - 1))
        line = doc.get_line(row)
        col = 0

    cc = _char_class(line[col])
    while col + 1 < len(line) and _char_class(line[col + 1]) == cc:
        col += 1
    return (row, col)


def find_next_WORD_end(doc: Any, row: int, col: int) -> tuple[int, int]:
    """Find end of next WORD (vim 'E')."""
    line_count = doc.line_count
    line = doc.get_line(row)

    col += 1
    while col >= len(line):
        row += 1
        if row >= line_count:
            last = line_count - 1
            return (last, max(0, len(doc.get_line(last)) - 1))
        line = doc.get_line(row)
        col = 0

    while True:
        while col < len(line) and line[col].isspace():
            col += 1
        if col < len(line):
            break
        row += 1
        if row >= line_count:
            last = line_count - 1
            return (last, max(0, len(doc.get_line(last)) - 1))
        line = doc.get_line(row)
        col = 0

    while col + 1 < len(line) and not line[col + 1].isspace():
        col += 1
    return (row, col)


def find_inner_word(
    doc: Any, row: int, col: int, count: int = 1
) -> tuple[int, int, int, int]:
    """Find inner word text object (vim ``iw``).

    Returns ``(start_row, start_col, end_row, end_col)`` with end exclusive.
    Selects the word (or whitespace/punctuation group) under the cursor.
    With *count* > 1, extends forward to include additional groups.
    """
    line = doc.get_line(row)
    if not line or col >= len(line):
        return (row, col, row, col)

    cc = _char_class(line[col])

    # Find start of current group
    start = col
    while start > 0 and _char_class(line[start - 1]) == cc:
        start -= 1

    # Find end of current group (inclusive)
    end = col
    while end + 1 < len(line) and _char_class(line[end + 1]) == cc:
        end += 1

    # For count > 1, extend to include more groups
    for _ in range(count - 1):
        if end + 1 >= len(line):
            break
        next_cc = _char_class(line[end + 1])
        end += 1
        while end + 1 < len(line) and _char_class(line[end + 1]) == next_cc:
            end += 1

    return (row, start, row, end + 1)


def find_a_word(
    doc: Any, row: int, col: int, count: int = 1
) -> tuple[int, int, int, int]:
    """Find 'a word' text object (vim ``aw``).

    Returns ``(start_row, start_col, end_row, end_col)`` with end exclusive.
    Like ``iw`` but includes surrounding whitespace.
    """
    line = doc.get_line(row)
    if not line or col >= len(line):
        return (row, col, row, col)

    cc = _char_class(line[col])

    # Find start of current group
    start = col
    while start > 0 and _char_class(line[start - 1]) == cc:
        start -= 1

    # Find end of current group (inclusive)
    end = col
    while end + 1 < len(line) and _char_class(line[end + 1]) == cc:
        end += 1

    # For count > 1, extend by alternating groups
    for _ in range(count - 1):
        if end + 1 >= len(line):
            break
        next_cc = _char_class(line[end + 1])
        end += 1
        while end + 1 < len(line) and _char_class(line[end + 1]) == next_cc:
            end += 1

    end += 1  # make exclusive

    # Include surrounding whitespace
    if cc != "space":
        if end < len(line) and line[end].isspace():
            # Trailing whitespace
            while end < len(line) and line[end].isspace():
                end += 1
        elif start > 0 and line[start - 1].isspace():
            # No trailing whitespace, include leading
            while start > 0 and line[start - 1].isspace():
                start -= 1
    else:
        # On whitespace: include the following word
        if end < len(line):
            next_cc = _char_class(line[end])
            while end < len(line) and _char_class(line[end]) == next_cc:
                end += 1

    return (row, start, row, end)


def find_inner_WORD(
    doc: Any, row: int, col: int, count: int = 1
) -> tuple[int, int, int, int]:
    """Find inner WORD text object (vim ``iW``).

    Returns ``(start_row, start_col, end_row, end_col)`` with end exclusive.
    Like ``iw`` but uses WORD boundaries (whitespace-delimited).
    """
    line = doc.get_line(row)
    if not line or col >= len(line):
        return (row, col, row, col)

    on_space = line[col].isspace()

    start = col
    if on_space:
        while start > 0 and line[start - 1].isspace():
            start -= 1
    else:
        while start > 0 and not line[start - 1].isspace():
            start -= 1

    end = col
    if on_space:
        while end + 1 < len(line) and line[end + 1].isspace():
            end += 1
    else:
        while end + 1 < len(line) and not line[end + 1].isspace():
            end += 1

    # For count > 1, extend
    for _ in range(count - 1):
        if end + 1 >= len(line):
            break
        next_is_space = line[end + 1].isspace()
        end += 1
        if next_is_space:
            while end + 1 < len(line) and line[end + 1].isspace():
                end += 1
        else:
            while end + 1 < len(line) and not line[end + 1].isspace():
                end += 1

    return (row, start, row, end + 1)


def find_a_WORD(
    doc: Any, row: int, col: int, count: int = 1
) -> tuple[int, int, int, int]:
    """Find 'a WORD' text object (vim ``aW``).

    Returns ``(start_row, start_col, end_row, end_col)`` with end exclusive.
    Like ``iW`` but includes surrounding whitespace.
    """
    line = doc.get_line(row)
    if not line or col >= len(line):
        return (row, col, row, col)

    on_space = line[col].isspace()

    start = col
    if on_space:
        while start > 0 and line[start - 1].isspace():
            start -= 1
    else:
        while start > 0 and not line[start - 1].isspace():
            start -= 1

    end = col
    if on_space:
        while end + 1 < len(line) and line[end + 1].isspace():
            end += 1
    else:
        while end + 1 < len(line) and not line[end + 1].isspace():
            end += 1

    # For count > 1, extend
    for _ in range(count - 1):
        if end + 1 >= len(line):
            break
        next_is_space = line[end + 1].isspace()
        end += 1
        if next_is_space:
            while end + 1 < len(line) and line[end + 1].isspace():
                end += 1
        else:
            while end + 1 < len(line) and not line[end + 1].isspace():
                end += 1

    end += 1  # make exclusive

    # Include surrounding whitespace
    if not on_space:
        if end < len(line) and line[end].isspace():
            while end < len(line) and line[end].isspace():
                end += 1
        elif start > 0 and line[start - 1].isspace():
            while start > 0 and line[start - 1].isspace():
                start -= 1
    else:
        # On whitespace: include the following WORD
        if end < len(line):
            while end < len(line) and not line[end].isspace():
                end += 1

    return (row, start, row, end)


def find_char_forward(line: str, col: int, char: str, count: int = 1) -> int | None:
    """Find the *count*-th occurrence of *char* forward from *col* (exclusive).

    Returns the column index, or ``None`` if not found.
    """
    found = 0
    for i in range(col + 1, len(line)):
        if line[i] == char:
            found += 1
            if found == count:
                return i
    return None


def find_char_backward(line: str, col: int, char: str, count: int = 1) -> int | None:
    """Find the *count*-th occurrence of *char* backward from *col* (exclusive).

    Returns the column index, or ``None`` if not found.
    """
    found = 0
    for i in range(col - 1, -1, -1):
        if line[i] == char:
            found += 1
            if found == count:
                return i
    return None
