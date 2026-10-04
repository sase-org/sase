"""Prompt editing for continuing a closed macro argument list."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from textual.app import App, ComposeResult
from textual.widgets.text_area import Selection

from sase.ace.testing import PromptPage
from sase.ace.tui.widgets._paired_text_editing import plan_pair_insert
from sase.ace.tui.widgets.macro_arg_assist import (
    ActiveMacroArgHint,
    MacroAssistEntry,
    MacroInputHint,
)
from sase.ace.tui.widgets.prompt_completion import PromptCompletionSettings
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

from ._completion_helpers import CompletionTestApp


class PairEditTestApp(App[None]):
    """Minimal app that hosts a PromptTextArea without frontmatter dependencies."""

    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield PromptInputBar(mode="feedback")


def _location(text: str, offset: int) -> tuple[int, int]:
    row = text.count("\n", 0, offset)
    line_start = text.rfind("\n", 0, offset) + 1
    return row, offset - line_start


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("#foo(bar=1)<cursor>", "#foo(bar=1,<cursor>)"),
        (
            "#foo(bar=1):: <cursor>Some text.",
            "#foo(bar=1,<cursor>):: Some text.",
        ),
        (
            "#foo(bar=1)::<cursor>",
            "#foo(bar=1,<cursor>)::",
        ),
        (
            "#foo(bar=1)::   <cursor>body",
            "#foo(bar=1,<cursor>)::   body",
        ),
        ("#foo()<cursor>", "#foo(<cursor>)"),
        (
            "#foo(bar=1,)<cursor>",
            "#foo(bar=1,<cursor>)",
        ),
        (
            "#foo(bar=1, )<cursor>",
            "#foo(bar=1, <cursor>)",
        ),
        (
            "#foo(bar=1 )<cursor>",
            "#foo(bar=1, <cursor>)",
        ),
        (
            "#foo(\n  bar=1\n)<cursor>",
            "#foo(\n  bar=1,\n<cursor>)",
        ),
        (
            "#outer(#inner(a=1)<cursor>)",
            "#outer(#inner(a=1,<cursor>))",
        ),
        (
            '#foo(a=")", b=[[x)y]])<cursor>',
            '#foo(a=")", b=[[x)y]],<cursor>)',
        ),
        (
            "🙂\n#foo(bar=1)<cursor>",
            "🙂\n#foo(bar=1,<cursor>)",
        ),
        (
            "#foo(bar=1):: <cursor>Some text for the first positional input.",
            "#foo(bar=1,<cursor>):: Some text for the first positional input.",
        ),
    ],
)
async def test_typing_paren_continues_macro_argument_list(
    source: str,
    expected: str,
) -> None:
    cursor = source.index("<cursor>")
    text = source.replace("<cursor>", "")
    expected_cursor = expected.index("<cursor>")
    expected_text = expected.replace("<cursor>", "")
    app = PairEditTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text(text)
        ta.cursor_location = _location(text, cursor)

        await pilot.press("(")

        assert ta.text == expected_text
        assert ta.cursor_location == _location(expected_text, expected_cursor)


def _ordinary_pair_result(marked: str) -> tuple[str, int]:
    cursor = marked.index("<cursor>")
    text = marked.replace("<cursor>", "")
    plan = plan_pair_insert(text, cursor, "(")
    if plan is None:
        return text[:cursor] + "(" + text[cursor:], cursor + 1
    return (
        text[: plan.start] + plan.text + text[plan.end :],
        plan.cursor,
    )


@pytest.mark.parametrize(
    "source",
    [
        "%q(capacity=1)<cursor>",
        "%wait(ready=true)<cursor>",
        "%proc(a)::<cursor>",
        "%(a,b)<cursor>",
        "%alt(a,b)<cursor>",
        "(note)<cursor>",
        "foo(bar)<cursor>",
        r"\#foo(a)<cursor>",
        "word#foo(a)<cursor>",
        "https://x.test/#foo(a)<cursor>",
        "#foo(a) <cursor>",
        "#foo(a):<cursor>",
        "#foo(a): <cursor>",
        "#foo(a)::\t<cursor>",
        "#foo(a)::\u00a0<cursor>",
        "#foo(a)::<cursor>:",
        "#foo(a):::<cursor>",
        "#foo(a):: body<cursor>",
        "#foo(a)x<cursor>",
        "#foo(a<cursor>)",
        "#foo(a<cursor>",
        "`#foo(a)<cursor>`",
        "```\n#foo(a)<cursor>\n```",
        "%xprompts_enabled:false\n#foo(a)<cursor>\n%xprompts_enabled:true\n",
        "---\nname: #foo(a)<cursor>\n---\n#foo(a)",
        "{{ #foo(a)<cursor> }}",
        "{% set value = '#foo(a)<cursor>' %}",
    ],
)
async def test_ineligible_sources_keep_ordinary_pairing(source: str) -> None:
    expected, expected_cursor = _ordinary_pair_result(source)
    text = source.replace("<cursor>", "")
    cursor = source.index("<cursor>")
    app = PairEditTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text(text)
        ta.cursor_location = _location(text, cursor)

        await pilot.press("(")

        assert ta.text == expected
        assert ta.cursor_location == _location(expected, expected_cursor)


async def test_selected_text_gets_literal_paren() -> None:
    app = PairEditTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("#foo(bar=1)")
        ta.selection = Selection((0, 5), (0, 10))

        await pilot.press("(")

        assert ta.text == "#foo(()"


async def test_continuation_is_one_undo_checkpoint() -> None:
    original = "#foo(bar=1):: body"
    async with PromptPage(
        original,
        cursor=(0, len("#foo(bar=1):: ")),
        mode="insert",
    ) as page:
        await page.press("(")
        assert page.text == "#foo(bar=1,):: body"

        await page.press("escape", "u")

        assert page.text == original


async def test_typing_continues_inside_reopened_list() -> None:
    app = PairEditTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("#foo(bar=1):: body")
        ta.cursor_location = (0, len("#foo(bar=1):: "))

        await pilot.press("(", "b", "a", "z", "=", "2")

        assert ta.text == "#foo(bar=1,baz=2):: body"
        assert ta.cursor_location == (0, len("#foo(bar=1,baz=2"))


def _input(
    name: str,
    type_: str,
    *,
    required: bool,
    position: int = 0,
) -> MacroInputHint:
    return MacroInputHint(
        name=name,
        type=type_,
        required=required,
        default_display=None,
        position=position,
    )


def _entry(name: str = "foo") -> MacroAssistEntry:
    return MacroAssistEntry(
        name=name,
        insertion=f"#{name}",
        reference_prefix="#",
        kind="macro",
        input_signature=None,
        inputs=(
            _input("bar", "word", required=False, position=0),
            _input("baz", "word", required=False, position=1),
        ),
        content_preview=None,
    )


def _seed_entries(ta: PromptTextArea) -> None:
    ta._macro_arg_assist_entries_by_project[None] = [_entry()]


@pytest.mark.parametrize(
    ("text", "cursor"),
    [
        ("#foo(bar=1)", len("#foo(bar=1)")),
        ("#foo(bar=1):: text", len("#foo(bar=1):: ")),
    ],
)
async def test_continuation_opens_remaining_macro_argument_menu(
    text: str,
    cursor: int,
) -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        _seed_entries(ta)
        ta.load_text(text)
        ta.cursor_location = (0, cursor)

        await pilot.press("(")

        assert ta._file_completion_active is True
        assert ta._completion_kind == "macro_arg_name"
        assert [
            candidate.insertion for candidate in ta._file_completion_candidates
        ] == ["baz="]


async def test_continuation_edit_works_when_auto_menu_is_disabled() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        _seed_entries(ta)
        ta.load_text("#foo(bar=1)")
        ta.cursor_location = (0, len("#foo(bar=1)"))
        with patch.object(
            type(ta),
            "_prompt_completion_settings",
            return_value=PromptCompletionSettings(auto_xprompt_menu=False),
        ):
            await pilot.press("(")

        assert ta.text == "#foo(bar=1,)"
        assert ta.cursor_location == (0, len("#foo(bar=1,"))
        assert ta._file_completion_active is False


async def test_other_accepted_macro_hint_does_not_intercept_continuation() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("#other #foo(bar=1)")
        ta.cursor_location = (0, len(ta.text))
        other = MacroAssistEntry(
            name="other",
            insertion="#other",
            reference_prefix="#",
            kind="macro",
            input_signature=None,
            inputs=(_input("name", "word", required=True),),
            content_preview=None,
        )
        ta._active_macro_arg_hint = ActiveMacroArgHint(
            entry=other,
            reference_start=0,
            reference_end=len("#other"),
            reference_text="#other",
            trigger_mode="accepted",
        )

        await pilot.press("(")

        assert ta.text == "#other #foo(bar=1,)"
        assert ta.cursor_location == (0, len("#other #foo(bar=1,"))
