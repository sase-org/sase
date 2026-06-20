"""Tests for ``%{...}`` alt-shorthand prompt highlighting (overlay layer)."""

from __future__ import annotations

from sase.ace.tui.widgets._jinja_highlight import _MAX_OVERLAY_LINES
from sase.ace.tui.widgets._vim_search import find_search_matches
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

from ._completion_helpers import CompletionTestApp


def _highlight_names(ta: PromptTextArea) -> list[str]:
    return [name for row in ta._highlights.values() for *_range, name in row]


async def test_alt_highlight_overlay_marks_spans() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        ta.load_text("%{fast=a | b}")
        ta._build_highlight_map()

        names = _highlight_names(ta)
        assert "alt.delimiter" in names
        assert "alt.separator" in names
        assert "alt.branch_name" in names

        styles = ta._theme.syntax_styles
        assert "alt.delimiter" in styles
        assert "alt.separator" in styles
        assert "alt.branch_name" in styles
        assert "alt.error" in styles


async def test_alt_highlight_overlay_coexists_with_jinja_and_search() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        ta.load_text("%{root | other}\nuse {{ root }}")
        ta.cursor_location = (0, 0)
        spans = find_search_matches(ta.text, "root")
        ta._set_search_highlights(spans, current_index=0)
        ta._build_highlight_map()

        names = _highlight_names(ta)
        # Alt overlay.
        assert "alt.delimiter" in names
        assert "alt.separator" in names
        # Jinja overlay still present.
        assert "jinja.delimiter" in names
        assert "jinja.variable" in names
        # Search overlay still present.
        assert "search.match" in names or "search.current" in names

        # All overlay style families share the one prompt theme.
        styles = ta._theme.syntax_styles
        assert "alt.delimiter" in styles
        assert "jinja.delimiter" in styles
        assert "search.match" in styles


async def test_alt_highlight_overlay_marks_unmatched_opener() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        ta.load_text("%{a | b")
        ta._build_highlight_map()

        names = _highlight_names(ta)
        assert "alt.error" in names
        assert "alt.delimiter" not in names


async def test_alt_highlight_overlay_skips_large_buffers() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        ta.load_text("%{a | b}\n" * (_MAX_OVERLAY_LINES + 1))
        ta._build_highlight_map()

    assert not any(name.startswith("alt.") for name in _highlight_names(ta))
