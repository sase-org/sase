"""Tests for live xprompt syntax highlighting in ``PromptTextArea``."""

from __future__ import annotations

from rich.color import Color
from rich.style import Style

from sase.ace.tui.widgets._jinja_highlight import _MAX_OVERLAY_LINES
from sase.ace.tui.widgets._vim_search import find_search_matches
from sase.ace.tui.widgets._xprompt_syntax_highlight import _derive_argument_color
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

from ._completion_helpers import CompletionTestApp


def _highlight_names(ta: PromptTextArea) -> list[str]:
    return [name for row in ta._highlights.values() for *_range, name in row]


async def test_xprompt_highlight_overlay_marks_spans_and_registers_styles() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        ta.load_text("#gh:sase %auto #pr:my_change %m:opus\n---")
        ta._build_highlight_map()

        names = _highlight_names(ta)
        for name in (
            "xprompt.invocation",
            "xprompt.invocation_arg",
            "xprompt.directive",
            "xprompt.directive_arg",
            "xprompt.separator",
        ):
            assert name in names
            assert name in ta._theme.syntax_styles

        styles = ta._theme.syntax_styles
        assert styles["xprompt.invocation"].color == Color.parse(
            app.current_theme.success
        )
        assert styles["xprompt.directive"].color == Color.parse(
            app.current_theme.warning
        )
        assert (
            styles["xprompt.invocation_arg"].color != styles["xprompt.invocation"].color
        )
        assert (
            styles["xprompt.directive_arg"].color != styles["xprompt.directive"].color
        )


def test_derive_argument_color_is_theme_adaptive() -> None:
    assert (
        _derive_argument_color(
            "#66800B",
            foreground="#FFFCF0",
            background="#100F0F",
        )
        == "#A3B166"
    )
    assert (
        _derive_argument_color(
            "#66800B",
            foreground=None,
            background="#FFFCF0",
        )
        == "#3D4C06"
    )


def test_derive_argument_color_preserves_missing_base() -> None:
    assert (
        _derive_argument_color(
            "",
            foreground="#FFFCF0",
            background="#100F0F",
        )
        == ""
    )
    assert (
        _derive_argument_color(
            None,
            foreground="#FFFCF0",
            background="#100F0F",
        )
        is None
    )


async def test_xprompt_overlay_coexists_with_jinja_alt_and_search() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        ta.load_text("%{ %m:opus | slow=plain} {{ root }} #gh:sase")
        spans = find_search_matches(ta.text, "%m")
        ta._set_search_highlights(spans, current_index=0)
        ta._build_highlight_map()

        names = _highlight_names(ta)
        assert "xprompt.directive" in names
        assert "xprompt.invocation" in names
        assert "jinja.delimiter" in names
        assert "jinja.variable" in names
        assert "search.current" in names
        assert "alt.delimiter" in names
        assert "alt.separator" in names
        assert "alt.branch_name" in names

        # Overlay build order keeps search above xprompt and alt uppermost.
        assert names.index("xprompt.directive") < names.index("search.current")
        assert names.index("search.current") < names.index("alt.delimiter")

        styles = ta._theme.syntax_styles
        for family in ("xprompt.", "jinja.", "search.", "alt."):
            assert any(name.startswith(family) for name in styles)


async def test_xprompt_overlay_skips_fences_and_disabled_regions() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        ta.load_text(
            "```\n#fenced %auto\n```\n"
            "%xprompts_enabled:false\n#disabled %m:opus\n"
            "%xprompts_enabled:true\nplain"
        )
        ta._build_highlight_map()

        assert not any(name.startswith("xprompt.") for name in _highlight_names(ta))


async def test_xprompt_overlay_skips_large_buffers() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        ta.load_text("#foo %auto\n" * (_MAX_OVERLAY_LINES + 1))
        ta._build_highlight_map()

        assert not any(name.startswith("xprompt.") for name in _highlight_names(ta))


async def test_xprompt_overlay_reregisters_after_app_theme_switch() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        sentinel = Style(color="red")
        ta._theme.syntax_styles["xprompt.invocation"] = sentinel

        app.theme = "textual-light"
        await pilot.pause()

        after = ta._theme.syntax_styles["xprompt.invocation"]
        assert after.color == Color.parse(app.current_theme.success)
        assert after.bold is True
        assert after != sentinel


async def test_xprompt_overlay_tokenizer_failure_is_fail_open(monkeypatch) -> None:
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        ta.load_text("#foo remains visible")

        def _raise(_text: str):
            raise RuntimeError("boom")

        monkeypatch.setattr(
            "sase.ace.tui.widgets._xprompt_syntax_highlight.xprompt_inspect.tokenize",
            _raise,
        )
        ta._build_highlight_map()

        assert ta.text == "#foo remains visible"
        assert not any(name.startswith("xprompt.") for name in _highlight_names(ta))
