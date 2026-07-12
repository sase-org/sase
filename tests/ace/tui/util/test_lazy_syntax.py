"""Tests for the Phase-6 lazy/capped Rich Syntax helper."""

from __future__ import annotations

from rich.console import Console
from rich.console import Group
from rich.syntax import Syntax

from sase.ace.tui.util.lazy_syntax import (
    MARKDOWN_SYNTAX_HIGHLIGHT_MAX_BYTES,
    MARKDOWN_SYNTAX_HIGHLIGHT_MAX_LINES,
    FILE_PANEL_MAX_RENDER_LINES,
    LazySyntaxRenderCache,
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


def test_lazy_renderable_uses_lower_markdown_byte_cap_only_for_markdown() -> None:
    content = "x" * (MARKDOWN_SYNTAX_HIGHLIGHT_MAX_BYTES + 1)

    assert isinstance(lazy_renderable(content, "markdown"), Group)
    assert isinstance(lazy_renderable(content, "python"), Syntax)


def test_lazy_renderable_uses_lower_markdown_line_cap_only_for_markdown() -> None:
    content = "\n".join(["x"] * (MARKDOWN_SYNTAX_HIGHLIGHT_MAX_LINES + 1))

    assert isinstance(lazy_renderable(content, "markdown"), Group)
    assert isinstance(lazy_renderable(content, "python"), Syntax)


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


def test_cached_lazy_renderable_reuses_segments_for_same_width(monkeypatch) -> None:
    original_highlight = Syntax.highlight
    calls = 0

    def counted_highlight(self, code, line_range=None):
        nonlocal calls
        calls += 1
        return original_highlight(self, code, line_range)

    monkeypatch.setattr(Syntax, "highlight", counted_highlight)
    cache = LazySyntaxRenderCache(max_entries=4)
    out = lazy_renderable("# hello\n\nbody", "markdown", render_cache=cache)
    assert hasattr(out, "code")

    from rich.console import Console

    console = Console(width=40, force_terminal=True)
    console.render_lines(out)
    list(console.render(out))

    assert calls == 1


def test_cached_lazy_renderable_reuses_segments_across_height(monkeypatch) -> None:
    original_highlight = Syntax.highlight
    calls = 0

    def counted_highlight(self, code, line_range=None):
        nonlocal calls
        calls += 1
        return original_highlight(self, code, line_range)

    monkeypatch.setattr(Syntax, "highlight", counted_highlight)
    cache = LazySyntaxRenderCache(max_entries=4)
    out = lazy_renderable(
        "def example():\n    return 'same width, different height'\n",
        "python",
        render_cache=cache,
    )
    console = Console(width=48, force_terminal=True)

    height_10_segments = tuple(
        out.__rich_console__(console, console.options.update(height=10))
    )
    height_20_segments = tuple(
        out.__rich_console__(console, console.options.update(height=20))
    )

    assert calls == 1
    assert height_10_segments == height_20_segments


def test_cached_lazy_renderable_renders_distinct_width(monkeypatch) -> None:
    original_highlight = Syntax.highlight
    calls = 0

    def counted_highlight(self, code, line_range=None):
        nonlocal calls
        calls += 1
        return original_highlight(self, code, line_range)

    monkeypatch.setattr(Syntax, "highlight", counted_highlight)
    cache = LazySyntaxRenderCache(max_entries=4)
    out = lazy_renderable(
        "def example():\n    return 'a long line that wraps at narrow widths'\n",
        "python",
        render_cache=cache,
    )
    console = Console(width=40, force_terminal=True)

    tuple(out.__rich_console__(console, console.options.update_width(40)))
    tuple(out.__rich_console__(console, console.options.update_width(72)))

    assert calls == 2


def test_cached_lazy_renderable_reuses_renderable_for_same_content() -> None:
    cache = LazySyntaxRenderCache(max_entries=4)
    first = lazy_renderable("# hello\n", "markdown", render_cache=cache)
    second = lazy_renderable("# hello\n", "markdown", render_cache=cache)

    assert first is second


def test_file_panel_plain_render_cap_adds_editor_notice() -> None:
    content = "\n".join(
        f"line {index}" for index in range(FILE_PANEL_MAX_RENDER_LINES + 3)
    )

    out = lazy_renderable(
        content,
        "diff",
        max_render_lines=FILE_PANEL_MAX_RENDER_LINES,
    )

    assert isinstance(out, Group)
    body = out.renderables[1]
    assert str(body).count("\n") + 1 == FILE_PANEL_MAX_RENDER_LINES
    assert str(out.renderables[2]) == ("\n… 3 more lines — press E to open in editor")


def test_cached_plain_renderable_reuses_same_body() -> None:
    cache = LazySyntaxRenderCache(max_entries=2)
    content = "\n".join(["line"] * (SYNTAX_HIGHLIGHT_MAX_LINES + 1))

    first = lazy_renderable(content, "diff", render_cache=cache)
    second = lazy_renderable(content, "diff", render_cache=cache)

    assert first is second
    assert cache.misses == 1
    assert cache.hits == 1


def test_5mb_response_renders_as_plain_group() -> None:
    """A 5 MB response paints immediately as plain text and skips Syntax."""
    huge = "a" * (5 * 1024 * 1024)
    out = lazy_renderable(huge, "markdown")
    assert isinstance(out, Group)
    # The Group has the notice + a Text payload — never a Syntax.
    for child in out.renderables:
        assert not isinstance(child, Syntax)
