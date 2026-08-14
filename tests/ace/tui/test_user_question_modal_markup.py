"""Regression coverage for bracket-markup tokens in question gate options.

``UserQuestionModal._build_selections()`` used to hand raw ``str`` prompts to
``SelectionList``, which markup-parses them as Textual content markup. Agent
option text containing bracket sequences like ``[/]`` (a Textual
auto-closing tag with nothing to close) raised ``MarkupError`` inside
``compose()`` -- see the ``question_gate_markup_freeze`` plan.
"""

from __future__ import annotations

from textual.app import App
from textual.content import Content
from textual.widgets import SelectionList, Static

from sase.ace.tui.modals.user_question_modal import (
    UserQuestionModal,
    UserQuestionResult,
)


class _TestApp(App[None]):
    ENABLE_COMMAND_PALETTE = False


def _questions_with_bracket_markup() -> list[dict[str, object]]:
    return [
        {
            "question": "Q1 raw text with [x] token",
            "options": [
                {
                    "label": "Yes, drop Blocked",
                    "description": (
                        "Jump targets become exactly `[ ]`, `[/]`, `[*]`. "
                        "Blocked `[?]` tasks are skipped."
                    ),
                },
                {
                    "label": "Keep [bold] style",
                    "description": "Literal [x] and [-] tokens, not markup.",
                },
            ],
        },
        {
            "question": "Q2 raw text with [/] token",
            "options": [{"label": "Second", "description": "Second option [?]"}],
        },
    ]


async def test_modal_composes_without_raising_on_bracket_markup() -> None:
    modal = UserQuestionModal(_questions_with_bracket_markup())

    async with _TestApp().run_test(size=(100, 34)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        assert pilot.app._exception is None


async def test_option_prompts_render_bracket_tokens_verbatim() -> None:
    modal = UserQuestionModal(_questions_with_bracket_markup())

    async with _TestApp().run_test(size=(100, 34)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        sel_list = modal.query_one("#user-question-options", SelectionList)

        first_prompt = sel_list.get_option_at_index(0).prompt
        assert isinstance(first_prompt, Content)
        first_plain = first_prompt.plain
        assert "[ ]" in first_plain
        assert "[/]" in first_plain
        assert "[*]" in first_plain
        assert "[?]" in first_plain
        assert "\\[" not in first_plain

        second_prompt = sel_list.get_option_at_index(1).prompt
        assert isinstance(second_prompt, Content)
        second_plain = second_prompt.plain
        assert "[bold]" in second_plain
        assert "[x]" in second_plain
        assert "[-]" in second_plain
        assert "\\[" not in second_plain


async def test_next_and_prev_question_rebuild_list_without_raising() -> None:
    modal = UserQuestionModal(_questions_with_bracket_markup())

    async with _TestApp().run_test(size=(100, 34)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("n")
        await pilot.pause()
        assert pilot.app._exception is None
        assert modal._current_idx == 1

        # #user-question-text is constructed with markup=False and Static.update()
        # preserves that flag, so Q2's raw text (including its bracket token)
        # must still render literally after the rebuild.
        text_widget = modal.query_one("#user-question-text", Static)
        assert text_widget.visual.plain == "Q2 raw text with [/] token"

        sel_list = modal.query_one("#user-question-options", SelectionList)
        assert sel_list.get_option_at_index(0).prompt.plain.count("[?]") == 1

        await pilot.press("p")
        await pilot.pause()
        assert pilot.app._exception is None
        assert modal._current_idx == 0


async def test_submit_preserves_unescaped_labels_in_result() -> None:
    """The submitted label -- itself a SelectionList value -- must survive
    with its bracket token intact, since a stray escape would corrupt what
    the requesting agent reads back from ``question_response.json``."""
    results: list[UserQuestionResult | None] = []
    modal = UserQuestionModal(_questions_with_bracket_markup())

    async with _TestApp().run_test(size=(100, 34)) as pilot:
        pilot.app.push_screen(modal, results.append)
        await pilot.pause()
        # Select the second Q1 option, whose label itself contains "[bold]".
        await pilot.press("j")
        await pilot.press("space")
        await pilot.press("n")
        await pilot.pause()
        # Rebuilding the list via clear_options()/add_option() drops the
        # highlighted index, so a cursor move is needed before "space" can
        # toggle anything.
        await pilot.press("j")
        await pilot.press("space")
        await pilot.press("enter")
        await pilot.pause()

    assert results[0] is not None
    assert results[0].answers[0].selected == ["Keep [bold] style"]
    assert results[0].answers[1].selected == ["Second"]
