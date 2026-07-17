"""Pure and widget tests for prompt-local word completion."""

from __future__ import annotations

from unittest.mock import patch

from textual.content import Content
from textual.widgets import Static

from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.ace.tui.widgets.prompt_word_completion import (
    PROMPT_WORD_COMPLETION_KIND,
    _PromptWordCompletionResult,
    build_prompt_word_completion_result,
)

from ._completion_helpers import CompletionTestApp


def _result(
    text: str,
    cursor_offset: int | None = None,
) -> _PromptWordCompletionResult:
    if cursor_offset is None:
        cursor_offset = len(text)
    result = build_prompt_word_completion_result(text, cursor_offset)
    assert result is not None
    return result


def test_multiline_candidates_are_deduplicated_and_sorted() -> None:
    text = "alpha Alpine\napplication alpha\nal"

    result = _result(text)

    assert result.prefix == "al"
    assert (result.replacement_start, result.replacement_end) == (
        text.rindex("al"),
        len(text),
    )
    assert [candidate.insertion for candidate in result.candidates] == [
        "alpha",
        "Alpine",
    ]
    assert result.shared_extension == "p"


def test_cursor_in_middle_replaces_the_complete_word() -> None:
    text = "publish publication then pubZZZ"
    cursor_offset = text.rindex("pubZZZ") + len("pub")

    result = _result(text, cursor_offset)

    assert result.prefix == "pub"
    assert text[result.replacement_start : result.replacement_end] == "pubZZZ"
    assert [candidate.insertion for candidate in result.candidates] == [
        "publication",
        "publish",
    ]


def test_punctuation_underscore_and_unicode_word_boundaries() -> None:
    text = "naïve,naïveté snake_case snake_case_extra naï"

    result = _result(text)

    assert [candidate.insertion for candidate in result.candidates] == [
        "naïve",
        "naïveté",
    ]

    underscore_result = _result(text, text.index("snake_case") + len("snake_"))
    assert underscore_result.prefix == "snake_"
    assert [candidate.insertion for candidate in underscore_result.candidates] == [
        "snake_case_extra"
    ]


def test_case_insensitive_filter_preserves_exact_spellings() -> None:
    result = _result("Alpha ALPINE alphabet aL")

    assert [candidate.insertion for candidate in result.candidates] == [
        "Alpha",
        "alphabet",
        "ALPINE",
    ]


def test_current_word_and_exact_duplicates_are_excluded() -> None:
    assert build_prompt_word_completion_result("alpha alpha al", 5) is None

    result = _result("alpha alpha alpine al")
    assert [candidate.insertion for candidate in result.candidates] == [
        "alpha",
        "alpine",
    ]


def test_empty_prefix_outside_word_and_no_match_are_noops() -> None:
    assert build_prompt_word_completion_result("alpha beta", 0) is None
    assert build_prompt_word_completion_result("alpha beta", 6) is None
    assert build_prompt_word_completion_result("alpha z", len("alpha z")) is None


def test_shared_extension_is_empty_without_multiple_matches() -> None:
    result = _result("alphabet al")

    assert [candidate.insertion for candidate in result.candidates] == ["alphabet"]
    assert result.shared_extension == ""


async def test_ctrl_t_opens_multiple_prompt_words_and_renders_plain_rows() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        ta.load_text("alpha alpine al")
        ta.cursor_location = (0, len(ta.text))

        await pilot.press("ctrl+t")

        assert ta.text == "alpha alpine alp"
        assert ta._completion_kind == PROMPT_WORD_COMPLETION_KIND
        assert [
            candidate.insertion for candidate in ta._file_completion_candidates
        ] == ["alpha", "alpine"]
        panel = bar.query_one("#prompt-completion", Static)
        rendered = panel.render()
        assert isinstance(rendered, Content)
        assert panel.border_title == "prompt words"
        assert "alpha" in rendered.plain
        assert "alpine" in rendered.plain
        assert "📁" not in rendered.plain
        assert "📄" not in rendered.plain


async def test_ctrl_t_immediately_accepts_one_prompt_word_match() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("alpha al")
        ta.cursor_location = (0, len(ta.text))

        await pilot.press("ctrl+t")

        assert ta.text == "alpha alpha"
        assert ta.cursor_location == (0, len(ta.text))
        assert ta._file_completion_active is False


async def test_ctrl_t_mid_word_accept_replaces_right_hand_suffix() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("publish then pubZZZ")
        ta.cursor_location = (0, ta.text.rindex("pubZZZ") + len("pub"))

        await pilot.press("ctrl+t")

        assert ta.text == "publish then publish"
        assert ta.cursor_location == (0, len(ta.text))


async def test_ctrl_t_scans_all_prompt_lines() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("alpha\nalpine\nal")
        ta.cursor_location = (2, 2)

        await pilot.press("ctrl+t")

        assert ta.text == "alpha\nalpine\nalp"
        assert [
            candidate.insertion for candidate in ta._file_completion_candidates
        ] == ["alpha", "alpine"]


async def test_prompt_word_navigation_and_enter_acceptance() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("alpha alpine al")
        ta.cursor_location = (0, len(ta.text))

        await pilot.press("ctrl+t", "down", "enter")

        assert ta.text == "alpha alpine alpine"
        assert ta._file_completion_active is False


async def test_prompt_word_candidates_refresh_and_preserve_selection() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("algebra alpha alpine al")
        ta.cursor_location = (0, len(ta.text))

        await pilot.press("ctrl+t", "down", "down")
        assert ta._file_completion_candidates[ta._file_completion_index].insertion == (
            "alpine"
        )

        await pilot.press("p")

        assert [
            candidate.insertion for candidate in ta._file_completion_candidates
        ] == ["alpha", "alpine"]
        assert ta._file_completion_candidates[ta._file_completion_index].insertion == (
            "alpine"
        )

        await pilot.press("backspace")

        assert [
            candidate.insertion for candidate in ta._file_completion_candidates
        ] == ["algebra", "alpha", "alpine"]
        assert ta._file_completion_candidates[ta._file_completion_index].insertion == (
            "alpine"
        )

        await pilot.press("z")

        assert ta._file_completion_active is False


async def test_prompt_word_cursor_movement_dismisses_without_prefix() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("alpha alpine al")
        ta.cursor_location = (0, len(ta.text))

        await pilot.press("ctrl+t", "home")

        assert ta.cursor_location == (0, 0)
        assert ta._file_completion_active is False


async def test_structured_token_keeps_precedence_over_prompt_words() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("model manual %")
        ta.cursor_location = (0, len(ta.text))

        await pilot.press("ctrl+t")

        assert ta._completion_kind == "directive"
        assert all(
            candidate.insertion.startswith("%")
            for candidate in ta._file_completion_candidates
        )


async def test_whitespace_keeps_recent_file_history_precedence() -> None:
    history = CompletionCandidate(
        display="docs/readme.md",
        insertion="docs/readme.md",
        is_dir=False,
        name="docs/readme.md",
    )
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("alpha ")
        ta.cursor_location = (0, len(ta.text))

        with patch(
            "sase.ace.tui.widgets._file_completion_open."
            "build_file_history_completion_candidates",
            return_value=([history], ""),
        ):
            await pilot.press("ctrl+t")

        assert ta._completion_kind == "file_history"
        assert ta._file_completion_candidates == [history]
