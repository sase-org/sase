"""Pure and widget tests for prompt-local word completion."""

from __future__ import annotations

from unittest.mock import patch

from textual.content import Content
from textual.widgets import Static

from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.prompt_completion import PromptCompletionSettings
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.ace.tui.widgets.prompt_word_completion import (
    PROMPT_WORD_COMPLETION_KIND,
    WordCompletionResult,
    apply_word_case,
    build_prompt_word_completion_result,
    shared_word_extension,
    word_range_at_cursor,
    _word_ranges,
)

from ._completion_helpers import CompletionTestApp


class WordCompletionTestApp(CompletionTestApp):
    """Completion harness with configurable shared word settings."""

    def __init__(self, *, word_min_length: int) -> None:
        super().__init__()
        self.settings = PromptCompletionSettings(word_min_length=word_min_length)

    def get_prompt_completion_settings(self) -> PromptCompletionSettings:
        return self.settings


def _result(
    text: str,
    cursor_offset: int | None = None,
) -> WordCompletionResult:
    if cursor_offset is None:
        cursor_offset = len(text)
    result = build_prompt_word_completion_result(text, cursor_offset)
    assert result is not None
    return result


def test_apply_word_case_examples() -> None:
    cases = [
        ("SPECTAC", "spectacular", "SPECTACULAR"),
        ("spectac", "spectacular", "spectacular"),
        ("Spectac", "spectacular", "Spectacular"),
        ("S", "spectacular", "Spectacular"),
        ("als", "Also", "also"),
        ("githu", "GitHub", "GitHub"),
        ("GITHU", "GitHub", "GITHUB"),
        ("readm", "README", "README"),
        ("nas", "NASA", "NASA"),
        ("sPectac", "spectacular", "sPectacular"),
        ("stras", "Straße", "Straße"),
        ("123", "123abc", "123abc"),
        ("X-1", "x-123", "X-123"),
    ]

    for prefix, canonical, expected in cases:
        result = apply_word_case(canonical, prefix)

        assert result == expected
        assert result == canonical or result.casefold().startswith(prefix.casefold())


def test_shared_word_extension_is_recased_to_typed_prefix() -> None:
    assert shared_word_extension(["spectacular", "spectacle"], "SPEC") == "TAC"
    assert shared_word_extension(["spectacular", "spectacle"], "spec") == "tac"
    assert shared_word_extension(["Straße", "Straßen"], "stras") == ""


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
        "alpine",
    ]
    assert result.shared_extension == "p"


def test_cursor_in_middle_replaces_only_the_left_hand_prefix() -> None:
    text = "publish publication then pubZZZ"
    cursor_offset = text.rindex("pubZZZ") + len("pub")

    result = _result(text, cursor_offset)

    assert result.prefix == "pub"
    assert text[result.replacement_start : result.replacement_end] == "pub"
    assert result.replacement_end == cursor_offset
    assert result.has_word_suffix is True
    assert [candidate.insertion for candidate in result.candidates] == [
        "publication",
        "publish",
    ]


def test_hyphenated_words_are_single_ranges_and_candidates() -> None:
    text = "bob-mac-capture bob-maZZZ"
    cursor_offset = text.rindex("bob-maZZZ") + len("bob-ma")

    result = _result(text, cursor_offset)

    assert result.prefix == "bob-ma"
    assert word_range_at_cursor(text, cursor_offset) == (
        text.rindex("bob-maZZZ"),
        len(text),
    )
    assert text[result.replacement_start : result.replacement_end] == "bob-ma"
    assert result.has_word_suffix is True
    assert [candidate.insertion for candidate in result.candidates] == [
        "bob-mac-capture"
    ]


def test_punctuation_underscore_and_unicode_word_boundaries() -> None:
    text = "naïve,naïveté snake_case_extra snake_case naï"

    result = _result(text)

    assert [candidate.insertion for candidate in result.candidates] == [
        "naïveté",
        "naïve",
    ]

    underscore_result = _result(text, text.rindex("snake_case") + len("snake_"))
    assert underscore_result.prefix == "snake_"
    assert underscore_result.has_word_suffix is True
    assert [candidate.insertion for candidate in underscore_result.candidates] == [
        "snake_case_extra"
    ]
    range_text = "alpha.beta bob-mac-capture omega"
    assert [range_text[start:end] for start, end in _word_ranges(range_text)] == [
        "alpha",
        "beta",
        "bob-mac-capture",
        "omega",
    ]


def test_candidates_exclude_words_later_in_the_prompt() -> None:
    text = "alpine zzz alp alpaca"
    cursor_offset = len("alpine zzz alp")

    result = _result(text, cursor_offset)

    assert result.prefix == "alp"
    assert result.has_word_suffix is False
    assert [candidate.insertion for candidate in result.candidates] == ["alpine"]


def test_hyphen_only_runs_are_not_prompt_word_candidates() -> None:
    assert (
        build_prompt_word_completion_result("----- -", len("----- -"), min_length=1)
        is None
    )


def test_case_insensitive_filter_recases_plain_spellings() -> None:
    result = _result("Alpha ALPINE alphabet aL")

    assert [candidate.insertion for candidate in result.candidates] == [
        "aLphabet",
        "ALPINE",
        "aLpha",
    ]
    assert [candidate.name for candidate in result.candidates] == [
        "alphabet",
        "ALPINE",
        "Alpha",
    ]


def test_case_variants_collapse_to_latest_prompt_local_spelling() -> None:
    result = build_prompt_word_completion_result(
        "Also also ALSO al",
        len("Also also ALSO al"),
        min_length=1,
    )

    assert result is not None
    assert [candidate.name for candidate in result.candidates] == ["ALSO"]
    assert [candidate.insertion for candidate in result.candidates] == ["ALSO"]


def test_current_word_and_exact_duplicates_are_excluded() -> None:
    assert build_prompt_word_completion_result("alpha alpha al", 5) is None

    result = _result("alpha alpha alpine al")
    assert [candidate.insertion for candidate in result.candidates] == [
        "alpine",
        "alpha",
    ]


def test_earlier_exact_prefix_spelling_is_suppressed_without_suffix() -> None:
    text = "title other title"

    assert build_prompt_word_completion_result(text, len(text)) is None


def test_earlier_exact_prefix_spelling_is_kept_with_suffix() -> None:
    text = "title other titleZZZ"
    cursor_offset = text.rindex("titleZZZ") + len("title")

    result = _result(text, cursor_offset)

    assert result.prefix == "title"
    assert result.has_word_suffix is True
    assert [candidate.insertion for candidate in result.candidates] == ["title"]


def test_empty_prefix_outside_word_and_no_match_are_noops() -> None:
    assert build_prompt_word_completion_result("alpha beta", 0) is None
    assert build_prompt_word_completion_result("alpha beta", 6) is None
    assert build_prompt_word_completion_result("alpha z", len("alpha z")) is None


def test_shared_extension_is_empty_without_multiple_matches() -> None:
    result = _result("alphabet al")

    assert [candidate.insertion for candidate in result.candidates] == ["alphabet"]
    assert result.shared_extension == ""


def test_candidates_use_shared_minimum_not_typed_prefix_length() -> None:
    result = _result("tiny tiger title ti")

    assert [candidate.insertion for candidate in result.candidates] == [
        "title",
        "tiger",
    ]
    assert build_prompt_word_completion_result("tiny ti", len("tiny ti")) is None

    lowered = build_prompt_word_completion_result(
        "tiny ti",
        len("tiny ti"),
        min_length=4,
    )
    assert lowered is not None
    assert [candidate.insertion for candidate in lowered.candidates] == ["tiny"]


def test_candidate_minimum_is_clamped_to_one() -> None:
    text = "al a"
    result = build_prompt_word_completion_result(text, len(text), min_length=0)

    assert result is not None
    assert [candidate.insertion for candidate in result.candidates] == ["al"]


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
        ] == ["alpine", "alpha"]
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


async def test_ctrl_t_skips_short_prompt_word_match_by_default() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("tiny ti")
        ta.cursor_location = (0, len(ta.text))

        await pilot.press("ctrl+t")

        assert ta.text == "tiny ti"
        assert ta._file_completion_active is False


async def test_lowered_minimum_restores_short_prompt_word_completion() -> None:
    app = WordCompletionTestApp(word_min_length=4)
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("tiny ti")
        ta.cursor_location = (0, len(ta.text))

        await pilot.press("ctrl+t")

        assert ta.text == "tiny tiny"
        assert ta._file_completion_active is False


async def test_ctrl_t_mid_word_matches_goal_example() -> None:
    """The plan's motivating example: ``foo<cursor>baz`` -> ``foobar<cursor> baz``."""
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("foobar foobaz")
        ta.cursor_location = (0, len("foobar foo"))

        await pilot.press("ctrl+t")

        assert ta.text == "foobar foobar baz"
        assert ta.cursor_location == (0, len("foobar foobar"))


async def test_ctrl_t_mid_word_accept_preserves_right_hand_suffix_as_word() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("publish then pubZZZ")
        ta.cursor_location = (0, ta.text.rindex("pubZZZ") + len("pub"))

        await pilot.press("ctrl+t")

        assert ta.text == "publish then publish ZZZ"
        assert ta.cursor_location == (0, len("publish then publish"))


async def test_prompt_word_menu_enter_accept_preserves_suffix() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("alpha alpine alpZZZ")
        ta.cursor_location = (0, ta.text.rindex("alpZZZ") + len("alp"))

        await pilot.press("ctrl+t", "down", "enter")

        assert ta.text == "alpha alpine alpha ZZZ"
        assert ta.cursor_location == (0, len("alpha alpine alpha"))


async def test_prompt_word_menu_ctrl_l_accept_preserves_suffix() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("alpha alpine alpZZZ")
        ta.cursor_location = (0, ta.text.rindex("alpZZZ") + len("alp"))

        await pilot.press("ctrl+t", "ctrl+l")

        assert ta.text == "alpha alpine alpine ZZZ"
        assert ta.cursor_location == (0, len("alpha alpine alpine"))


async def test_ctrl_t_narrowing_preserves_suffix_without_space_until_commit() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("bob-mac-capture bob-mac-camera bob-maZZZ")
        ta.cursor_location = (0, ta.text.rindex("bob-maZZZ") + len("bob-ma"))

        await pilot.press("ctrl+t")

        assert ta.text == "bob-mac-capture bob-mac-camera bob-mac-caZZZ"
        assert ta._completion_kind == PROMPT_WORD_COMPLETION_KIND
        assert [
            candidate.insertion for candidate in ta._file_completion_candidates
        ] == ["bob-mac-camera", "bob-mac-capture"]

        await pilot.press("enter")

        assert ta.text == "bob-mac-capture bob-mac-camera bob-mac-camera ZZZ"
        assert ta.cursor_location == (
            0,
            len("bob-mac-capture bob-mac-camera bob-mac-camera"),
        )


async def test_ctrl_t_accepts_hyphenated_prompt_word_and_preserves_suffix() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("bob-mac-capture then bob-maZZZ")
        ta.cursor_location = (0, ta.text.rindex("bob-maZZZ") + len("bob-ma"))

        await pilot.press("ctrl+t")

        assert ta.text == "bob-mac-capture then bob-mac-capture ZZZ"
        assert ta.cursor_location == (0, len("bob-mac-capture then bob-mac-capture"))


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
        ] == ["alpine", "alpha"]


async def test_prompt_word_navigation_and_enter_acceptance() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("alpha alpine al")
        ta.cursor_location = (0, len(ta.text))

        await pilot.press("ctrl+t", "down", "enter")

        assert ta.text == "alpha alpine alpha"
        assert ta._file_completion_active is False


async def test_prompt_word_candidates_refresh_and_preserve_selection() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("algebra alpha alpine al")
        ta.cursor_location = (0, len(ta.text))

        await pilot.press("ctrl+t", "down", "down")
        assert ta._file_completion_candidates[ta._file_completion_index].insertion == (
            "algebra"
        )

        await pilot.press("p")

        assert [
            candidate.insertion for candidate in ta._file_completion_candidates
        ] == ["alpine", "alpha"]
        assert ta._file_completion_candidates[ta._file_completion_index].insertion == (
            "alpha"
        )

        await pilot.press("backspace")

        assert [
            candidate.insertion for candidate in ta._file_completion_candidates
        ] == ["alpine", "alpha", "algebra"]
        assert ta._file_completion_candidates[ta._file_completion_index].insertion == (
            "alpha"
        )

        await pilot.press("z")

        assert ta._file_completion_active is False


async def test_prompt_word_refresh_never_reintroduces_short_candidates() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("tiny tiger title ti")
        ta.cursor_location = (0, len(ta.text))

        await pilot.press("ctrl+t", "g", "backspace")

        assert ta._completion_kind == PROMPT_WORD_COMPLETION_KIND
        assert [
            candidate.insertion for candidate in ta._file_completion_candidates
        ] == ["title", "tiger"]


async def test_stale_short_candidate_cannot_be_accepted() -> None:
    app = WordCompletionTestApp(word_min_length=5)
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("alpine alpha al")
        ta.cursor_location = (0, len(ta.text))

        await pilot.press("ctrl+t")
        assert ta._file_completion_candidates[0].insertion == "alpha"

        app.settings = PromptCompletionSettings(word_min_length=6)
        await pilot.press("enter")

        assert ta.text == "alpine alpha alp"
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
