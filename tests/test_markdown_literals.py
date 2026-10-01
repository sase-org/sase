"""Unit tests for the literal-preserving emphasis protection."""

from __future__ import annotations

import re

import pytest

from sase.markdown_literals import (
    protect_emphasis_literals,
    restore_emphasis_literals,
)

_THEMATIC_RE = re.compile(r"^ {0,3}(?:(?:\*[ \t]*){3,}|(?:_[ \t]*){3,})\r?$")
_BULLET_RE = re.compile(r"^([ \t]*(?:>[ \t]*)*)\*(?=[ \t\r]|$)")
_GLUE_RE = re.compile(r"(?<=\S) (?=\*+(?:[ \t\r]|$))")

TABLE_ROWS = [
    "topic__cdx.md \u2026 topic__cld.md\n",
    "/x/gh_sase-org__sase/a__cdx.md\n",
    "__init__.py\n",
    "self.__dict__\n",
    "a___b and c___d\n",
    "src/*.py and tests/*.py\n",
    "x * y * z\n",
    "Snake_case_name and _leading and trailing_\n",
    "5 * 6\n",
    "{%- set _ = ns.layout_lines.append(...) -%}\n",
]

ROUND_TRIP_CORPUS = [
    *TABLE_ROWS,
    "* a\n",
    "  * b\n",
    "> * c\n",
    "* [ ] d\n",
    "***\n",
    "___\n",
    "* * *\n",
    "  ***\n",
    "| a | b |\n| --- | --- |\n| c__d | e*f |\n",
    "```python\nfoo__bar *baz*\n```\n",
    "Use `topic__cdx.md` here.\n",
    "---\nname: foo__bar\n---\nBody with *star*.\n",
    "{{ prompt }}\n",
    "ref \x00XPF_0\x00 with_underscore *\n",
    "ends foo_bar\r\nbaz__qux\r\n",
    "has \ue000 and \ue001 and \ue002 with_underscore *\n",
    "- wait_name=research.m.cdx label=research:202610/t/t__cdx.md\n",
    "line one\nline_two with * star\n\n- list * item\n",
]


@pytest.mark.parametrize("text", ROUND_TRIP_CORPUS)
def test_protect_restore_round_trip(text: str) -> None:
    """Protection is exactly reversible for every corpus entry."""
    protected, sentinels = protect_emphasis_literals(text)
    assert restore_emphasis_literals(protected, sentinels) == text


def test_sentinel_selection_skips_occupied_code_points() -> None:
    """Text already containing U+E000-U+E002 gets later sentinels."""
    text = "has \ue000 and \ue001 and \ue002 with_underscore *\n"
    _, sentinels = protect_emphasis_literals(text)
    for sentinel in (
        sentinels.underscore,
        sentinels.star,
        sentinels.glue,
    ):
        assert sentinel not in text
    assert sentinels.underscore == "\ue003"
    assert sentinels.star == "\ue004"
    assert sentinels.glue == "\ue005"


@pytest.mark.parametrize("text", ROUND_TRIP_CORPUS)
def test_protected_text_hides_underscores_and_stars(text: str) -> None:
    """No `_` or `*` remains except bullet prefixes and thematic lines."""
    protected, sentinels = protect_emphasis_literals(text)
    for original_line, protected_line in zip(
        text.split("\n"), protected.split("\n"), strict=True
    ):
        if _THEMATIC_RE.match(original_line):
            assert protected_line == original_line
            continue
        bullet = _BULLET_RE.match(original_line)
        if bullet is not None:
            prefix = original_line[: bullet.end()]
            protected_prefix = protected_line[: len(prefix)]
            assert protected_prefix == prefix
            remainder = protected_line[len(prefix) :]
            original_remainder = original_line[len(prefix) :]
        else:
            remainder = protected_line
            original_remainder = original_line
        assert "_" not in remainder
        assert "*" not in remainder
        # Every glue sits immediately before a star sentinel, i.e. only
        # before standalone star runs.
        for index, char in enumerate(remainder):
            if char == sentinels.glue:
                assert remainder[index + 1] == sentinels.star
        assert remainder.count(sentinels.glue) == len(
            _GLUE_RE.findall(original_remainder)
        )
