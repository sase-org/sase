"""PromptTextArea fenced and inline code highlighting coverage."""

from __future__ import annotations

from rich.color import Color
from rich.style import Style

from sase.ace.tui.util.code_injection import language_for_info_string
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

from ._completion_helpers import CompletionTestApp


def _highlight_names(text_area: PromptTextArea) -> list[str]:
    return [name for row in text_area._highlights.values() for *_range, name in row]


def test_codeblock_info_string_language_aliases_and_unknowns() -> None:
    assert language_for_info_string("py title=demo") == "python"
    assert language_for_info_string("ZSH") == "bash"
    assert language_for_info_string("yml") == "yaml"
    assert language_for_info_string("not-a-parser") is None


async def test_codeblock_overlay_registers_styles_and_injects_python() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        text_area = app.query_one(PromptTextArea)
        text_area.load_text(
            "```python\ndef greet(name):\n    return f'hello {name}'\n```\n"
            "Use `#literal` but expand #active"
        )
        text_area._build_highlight_map()

        names = _highlight_names(text_area)
        for name in (
            "codeblock.fence",
            "codeblock.lang",
            "codeblock.content",
            "codeblock.inline",
            "codeblock.delimiter",
        ):
            assert name in names
            assert name in text_area._theme.syntax_styles
        assert "keyword.function" in names
        assert "function" in names
        assert names.index("codeblock.content") < names.index("xprompt.invocation")

        styles = text_area._theme.syntax_styles
        assert styles["codeblock.content"].color is None
        assert styles["codeblock.content"].bgcolor is not None
        assert styles["codeblock.inline"].bgcolor is not None
        assert styles["codeblock.lang"].color == Color.parse(app.current_theme.accent)
        assert styles["codeblock.lang"].italic is True


async def test_codeblock_overlay_suppresses_other_syntax_inside_literals() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        text_area = app.query_one(PromptTextArea)
        text_area.load_text(
            "```text\n#fenced %auto {{ fenced }}\n```\n`#inline %m:opus {{ inline }}`"
        )
        text_area._build_highlight_map()

        names = _highlight_names(text_area)
        assert any(name.startswith("codeblock.") for name in names)
        assert not any(name.startswith("xprompt.") for name in names)
        assert not any(name.startswith("jinja.") for name in names)


async def test_codeblock_styles_reregister_after_app_theme_switch() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        text_area = app.query_one(PromptTextArea)
        sentinel = Style(bgcolor="red")
        text_area._theme.syntax_styles["codeblock.content"] = sentinel

        app.theme = "textual-light"
        await pilot.pause()

        after = text_area._theme.syntax_styles["codeblock.content"]
        assert after.bgcolor is not None
        assert after != sentinel


async def test_unclosed_fence_tints_to_eof_then_gains_closing_fence() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        text_area = app.query_one(PromptTextArea)
        text_area.load_text("```python\nvalue = 1")
        text_area._build_highlight_map()

        open_names = _highlight_names(text_area)
        assert "codeblock.content" in open_names
        assert open_names.count("codeblock.fence") == 1

        text_area.load_text("```python\nvalue = 1\n```")
        text_area._build_highlight_map()

        closed_names = _highlight_names(text_area)
        assert "codeblock.content" in closed_names
        assert closed_names.count("codeblock.fence") == 2


async def test_oversized_block_keeps_tint_but_skips_injection() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        text_area = app.query_one(PromptTextArea)
        text_area.load_text("```python\nvalue = '" + ("x" * 41_000) + "'\n```")
        text_area._build_highlight_map()

        names = _highlight_names(text_area)
        assert "codeblock.content" in names
        assert "codeblock.fence" in names
        assert "keyword" not in names
        assert "string" not in names
