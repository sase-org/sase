"""Tests for the Phase-6 lazy/capped Rich Syntax helper."""

from __future__ import annotations

from rich.console import Group
from rich.syntax import Syntax

from sase.ace.tui.util.lazy_syntax import (
    SYNTAX_HIGHLIGHT_MAX_BYTES,
    SYNTAX_HIGHLIGHT_MAX_LINES,
    _exceeds_cap,
    cap_ansi_output,
    lazy_renderable,
)


def test_lazy_renderable_under_cap_returns_syntax() -> None:
    out = lazy_renderable("# hello\n", "markdown")
    assert isinstance(out, Syntax)


def test_lazy_renderable_over_byte_cap_returns_plain_group() -> None:
    big = "x" * (SYNTAX_HIGHLIGHT_MAX_BYTES + 1)
    out = lazy_renderable(big, "markdown")
    assert isinstance(out, Group)


def test_lazy_renderable_over_line_cap_returns_plain_group() -> None:
    many = "\n".join(["a"] * (SYNTAX_HIGHLIGHT_MAX_LINES + 5))
    out = lazy_renderable(many, "markdown")
    assert isinstance(out, Group)


def test_lazy_renderable_diff_with_line_range_uses_visible_size() -> None:
    """Diff-style call that highlights only the trimmed range stays Syntax
    even when the whole file is huge."""
    huge_diff = "\n".join(["+ line"] * 50_000)
    out = lazy_renderable(huge_diff, "diff", line_numbers=True, line_range=(1, 100))
    assert isinstance(out, Syntax)


def test_exceeds_cap_measures_visible_range_only() -> None:
    huge = "\n".join(["+"] * (SYNTAX_HIGHLIGHT_MAX_LINES + 100))
    assert _exceeds_cap(huge) is True
    assert _exceeds_cap(huge, line_range=(1, 100)) is False


def test_cap_ansi_output_truncates_long_input() -> None:
    long_output = "a" * (SYNTAX_HIGHLIGHT_MAX_BYTES + 200)
    capped = cap_ansi_output(long_output)
    assert len(capped) <= SYNTAX_HIGHLIGHT_MAX_BYTES + 200
    assert capped.startswith("[…earlier output truncated")
    assert capped.endswith("a")


def test_cap_ansi_output_passthrough_when_short() -> None:
    short = "small log\n"
    assert cap_ansi_output(short) == short


def test_5mb_response_renders_as_plain_group() -> None:
    """A 5 MB response paints immediately as plain text and skips Syntax."""
    huge = "a" * (5 * 1024 * 1024)
    out = lazy_renderable(huge, "markdown")
    assert isinstance(out, Group)
    # The Group has the notice + a Text payload — never a Syntax.
    for child in out.renderables:
        assert not isinstance(child, Syntax)
