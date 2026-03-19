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
