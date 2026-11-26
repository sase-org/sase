"""Discoverability cues on the question pane (border, underlines, also-copyable)."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.app import App
from textual.containers import VerticalScroll
from textual.widgets import Static

from sase.ace.tui.modals.question_pane_cues import (
    ALSO_COPYABLE_HEADER,
    build_also_copyable_text,
    build_copy_border_subtitle,
    build_question_prose_text,
    missing_copy_items,
    pane_keys_for_items,
)
from sase.ace.tui.modals.user_question_modal import UserQuestionModal
from sase.core.question_copy_facade import QuestionCopyItem


def _subtitle_plain(total: int, copied: int, unavailable: int) -> str:
    subtitle = build_copy_border_subtitle(total, copied, unavailable)
    assert isinstance(subtitle, Text)
    return subtitle.plain


def _rendered_subtitle(subtitle: object) -> str:
    """Return the visible text of a widget border subtitle.

    Textual normalizes an assigned ``Text`` into a markup string, so accept
    either form here; the builder-level tests above pin the ``Text`` shape.
    """
    if isinstance(subtitle, Text):
        return subtitle.plain
    return str(subtitle)


def test_prose_plain_equals_question_and_markup_is_literal() -> None:
    question = "Run [bold]x against [/] now"
    items = (QuestionCopyItem(text="[bold]x"), QuestionCopyItem(text="[/]"))
    text = build_question_prose_text(question, items, frozenset())
    assert text.plain == question
    assert len(text.spans) == 2


def test_prose_longest_first_wins_overlaps() -> None:
    question = "paste /Users/bbugyi/.sase here"
    items = (
        QuestionCopyItem(text="/Users/bbugyi"),
        QuestionCopyItem(text="/Users/bbugyi/.sase", label=".sase"),
    )
    text = build_question_prose_text(question, items, frozenset())
    assert text.plain == question
    assert len(text.spans) == 1
    span = text.spans[0]
    assert question[span.start : span.end] == "/Users/bbugyi/.sase"


def test_prose_marks_every_occurrence_and_copied_turns_green() -> None:
    question = "a /tmp/x b /tmp/x c"
    items = (QuestionCopyItem(text="/tmp/x"),)
    text = build_question_prose_text(question, items, frozenset())
    assert len(text.spans) == 2
    assert all("green" not in span.style for span in text.spans)
    copied = build_question_prose_text(question, items, frozenset({"/tmp/x"}))
    assert len(copied.spans) == 2
    assert all("green" in span.style for span in copied.spans)


def test_prose_without_items_has_no_spans() -> None:
    text = build_question_prose_text("plain?", (), frozenset({"x"}))
    assert text.plain == "plain?"
    assert text.spans == []


def test_border_subtitle_states() -> None:
    assert _subtitle_plain(8, 0, 0) == "8 copyable · y"
    assert _subtitle_plain(1, 0, 0) == "1 copyable · y"
    assert _subtitle_plain(8, 3, 0) == "3/8 copied · y"
    done = build_copy_border_subtitle(8, 8, 0)
    assert isinstance(done, Text)
    assert done.plain == "✓ 8/8 copied"
    assert _subtitle_plain(8, 3, 2) == "3/8 copied · y · 2 unavailable"
    assert _subtitle_plain(8, 8, 1) == "✓ 8/8 copied · 1 unavailable"
    assert build_copy_border_subtitle(0, 0, 0) == ""


def test_missing_copy_items_detects_out_of_prose() -> None:
    items = (
        QuestionCopyItem(text="chrome://settings/performance"),
        QuestionCopyItem(text="do the thing"),
    )
    missing = missing_copy_items("open chrome://settings/performance", items)
    assert missing == (items[1],)
    assert missing_copy_items("paste /a and /b", ()) == ()


def test_pane_keys_match_panel_allocator() -> None:
    keys = pane_keys_for_items(3)
    assert keys == ("1", "2", "3")
    assert pane_keys_for_items(0) == ()


def test_also_copyable_block_shows_key_label_and_full_value() -> None:
    block = build_also_copyable_text(
        (
            (
                "7",
                QuestionCopyItem(
                    text="launchctl kickstart -k gui/501/x", label="Reset"
                ),
            ),
            ("8", QuestionCopyItem(text="line one\nline two")),
        )
    )
    assert block.plain.splitlines()[0] == ALSO_COPYABLE_HEADER
    assert "Reset" in block.plain
    assert "launchctl kickstart -k gui/501/x" in block.plain
    # Multi-line values are kept verbatim.
    assert "line one\nline two" in block.plain


class _QuestionApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def __init__(self, questions: list[dict[str, Any]], **kwargs: Any) -> None:
        super().__init__()
        self._questions = questions
        self._modal_kwargs = kwargs

    def on_mount(self) -> None:
        self.push_screen(UserQuestionModal(self._questions, **self._modal_kwargs))


def _spotlight_questions() -> list[dict[str, Any]]:
    return [
        {
            "header": "Mac GUI",
            "question": (
                "Open chrome://settings/performance and paste each folder. "
                "What did you do?"
            ),
            "options": [{"label": "Done, both"}],
            "copy": [
                {"label": ".sase", "text": "/Users/bbugyi/.sase"},
                {
                    "label": "Chrome Memory Saver",
                    "text": "chrome://settings/performance",
                },
            ],
        }
    ]


async def test_modal_shows_subtitle_underlines_and_also_block() -> None:
    app = _QuestionApp(_spotlight_questions())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        modal = app.screen_stack[-1]
        assert isinstance(modal, UserQuestionModal)
        scroll = modal.query_one("#user-question-text-scroll", VerticalScroll)
        assert "2 copyable · y" in _rendered_subtitle(scroll.border_subtitle)
        prose = modal.query_one("#user-question-text", Static)
        rendered = prose.visual
        assert rendered.plain == _spotlight_questions()[0]["question"]
        # chrome:// URL occurs verbatim, so it is underlined; .sase is not.
        url_at = _spotlight_questions()[0]["question"].index("chrome://")
        assert rendered.get_style_at_offset(url_at).underline
        assert not rendered.get_style_at_offset(0).underline
        also = modal.query_one("#user-question-also-copyable", Static)
        assert "hidden" not in also.classes
        assert "/Users/bbugyi/.sase" in str(also.visual)


async def test_modal_all_in_prose_hides_also_block() -> None:
    questions = [
        {
            "header": "H",
            "question": "Paste /tmp/a now",
            "options": [{"label": "Done"}],
            "copy": [{"text": "/tmp/a"}],
        }
    ]
    app = _QuestionApp(questions)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        modal = app.screen_stack[-1]
        assert isinstance(modal, UserQuestionModal)
        also = modal.query_one("#user-question-also-copyable", Static)
        assert "hidden" in also.classes
        scroll = modal.query_one("#user-question-text-scroll", VerticalScroll)
        assert "1 copyable · y" in _rendered_subtitle(scroll.border_subtitle)


async def test_modal_without_copy_is_unchanged() -> None:
    questions = [
        {
            "header": "H",
            "question": "What did you do?",
            "options": [{"label": "Done"}],
        }
    ]
    app = _QuestionApp(questions)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        modal = app.screen_stack[-1]
        assert isinstance(modal, UserQuestionModal)
        scroll = modal.query_one("#user-question-text-scroll", VerticalScroll)
        assert scroll.border_subtitle == ""
        also = modal.query_one("#user-question-also-copyable", Static)
        assert "hidden" in also.classes
        prose = modal.query_one("#user-question-text", Static)
        rendered = prose.visual
        assert rendered.plain == "What did you do?"
        assert not rendered.get_style_at_offset(0).underline


async def test_mark_copied_updates_subtitle_and_underline() -> None:
    app = _QuestionApp(_spotlight_questions())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        modal = app.screen_stack[-1]
        assert isinstance(modal, UserQuestionModal)
        url_at = _spotlight_questions()[0]["question"].index("chrome://")
        prose = modal.query_one("#user-question-text", Static)
        before = prose.visual.get_style_at_offset(url_at).foreground
        modal._mark_question_copied({"chrome://settings/performance"})
        await pilot.pause()
        scroll = modal.query_one("#user-question-text-scroll", VerticalScroll)
        assert "1/2 copied · y" in _rendered_subtitle(scroll.border_subtitle)
        after = prose.visual.get_style_at_offset(url_at)
        assert after.underline
        assert str(after.foreground) != str(before)
