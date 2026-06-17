"""Tests for prompt search highlighting."""

from __future__ import annotations

from sase.ace.tui.widgets._jinja_highlight import _MAX_OVERLAY_LINES
from sase.ace.tui.widgets._vim_search import SearchSelection, find_search_matches
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.xprompt import jinja_inspect

from ._completion_helpers import CompletionTestApp


def _highlight_names(ta: PromptTextArea) -> list[str]:
    return [name for row in ta._highlights.values() for *_range, name in row]


async def test_search_highlight_overlay_coexists_with_jinja(
    monkeypatch,
) -> None:
    monkeypatch.setattr(jinja_inspect, "known_toplevel_context", lambda: {"root"})
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        ta.load_text("Hello {{ root }} root")
        ta.cursor_location = (0, len(ta.text))
        spans = find_search_matches(ta.text, "root")
        ta._set_search_highlights(spans, current_index=1)
        ta._build_highlight_map()

    names = _highlight_names(ta)
    assert "jinja.delimiter" in names
    assert "jinja.variable" in names
    assert "search.match" in names
    assert "search.current" in names
    assert "jinja.delimiter" in ta._theme.syntax_styles
    assert "search.match" in ta._theme.syntax_styles
    assert "search.current" in ta._theme.syntax_styles


async def test_search_highlight_overlay_splits_multiline_spans() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        ta.load_text("one\ntwo\none")
        spans = find_search_matches(ta.text, "two\none")
        ta._set_search_highlights(spans, current_index=0)
        ta._build_highlight_map()

    names_by_row = {
        row: [name for *_range, name in spans] for row, spans in ta._highlights.items()
    }
    assert names_by_row[1] == ["search.current"]
    assert names_by_row[2] == ["search.current"]


async def test_search_highlight_preview_hook_computes_selection() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        ta.load_text("alpha beta alpha")
        selection = ta._preview_search_query_highlights("alpha", 1, "forward")

    assert selection == SearchSelection(index=1, wrapped=False)
    names = _highlight_names(ta)
    assert names.count("search.match") == 1
    assert names.count("search.current") == 1


async def test_search_highlight_overlay_skips_large_buffers() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        ta.load_text("needle\n" * (_MAX_OVERLAY_LINES + 1))
        ta._set_search_highlights(((0, 6),), current_index=0)
        ta._build_highlight_map()

    assert not any(name.startswith("search.") for name in _highlight_names(ta))
