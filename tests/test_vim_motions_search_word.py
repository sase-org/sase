"""Table-driven tests for the ``find_search_word`` vim ``*`` word resolver."""

from __future__ import annotations

import pytest

from sase.ace.tui.widgets._vim_motions import find_search_word


class _FakeDocument:
    """Minimal single-line-aware document double for ``find_search_word``."""

    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    def get_line(self, row: int) -> str:
        return self._lines[row]


@pytest.mark.parametrize(
    ("line", "col", "expected"),
    [
        # Cursor on the first character of a word.
        ("cat dog", 0, (0, 0, "cat")),
        # Cursor mid-word expands left and right over the full keyword run.
        ("catalog dog", 3, (0, 0, "catalog")),
        # Cursor on the word's last character.
        ("cat dog", 2, (0, 0, "cat")),
        # Cursor on whitespace scans forward to the next keyword character.
        ("   cat", 0, (0, 3, "cat")),
        ("cat   dog", 3, (0, 6, "dog")),
        # Cursor on punctuation scans forward past it.
        ("(cat)", 0, (0, 1, "cat")),
        # Underscore is a keyword character, like vim.
        ("foo_bar baz", 0, (0, 0, "foo_bar")),
        # Digits are keyword characters too.
        ("x1 y2", 0, (0, 0, "x1")),
        # Cursor already on the sole remaining keyword run.
        ("!!! cat", 4, (0, 4, "cat")),
    ],
)
def test_find_search_word_resolves_expected_word(
    line: str,
    col: int,
    expected: tuple[int, int, str],
) -> None:
    doc = _FakeDocument([line])

    assert find_search_word(doc, 0, col) == expected


@pytest.mark.parametrize(
    ("line", "col"),
    [
        ("", 0),
        ("   ", 0),
        ("!!!", 0),
        ("cat", 3),
        ("cat   ", 4),
    ],
)
def test_find_search_word_returns_none_when_line_has_no_keyword_char(
    line: str,
    col: int,
) -> None:
    doc = _FakeDocument([line])

    assert find_search_word(doc, 0, col) is None


def test_find_search_word_never_crosses_a_line_boundary() -> None:
    doc = _FakeDocument(["   ", "cat"])

    assert find_search_word(doc, 0, 0) is None
