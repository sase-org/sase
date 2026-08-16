"""Pure and widget tests for prompt-history word completion."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from textual.content import Content
from textual.widgets import Static

from sase.ace.tui.widgets.history_word_completion import (
    HISTORY_WORD_COMPLETION_KIND,
    HistoryWordCompletionPlaceholder,
    build_history_word_completion_result,
)
from sase.ace.tui.widgets.prompt_completion import PromptCompletionSettings
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.ace.tui.widgets.prompt_word_completion import PROMPT_WORD_COMPLETION_KIND

from ._completion_helpers import CompletionTestApp


@pytest.fixture(autouse=True)
def _skip_unrelated_vcs_catalog_warm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.widgets._file_completion_base._warm_vcs_completion_catalogs",
        lambda: None,
    )


class HistoryCompletionTestApp(CompletionTestApp):
    """Completion harness with an app-level history-word cache."""

    def __init__(
        self,
        words: list[str] | None,
        *,
        settings: PromptCompletionSettings | None = None,
    ) -> None:
        super().__init__()
        self.words = words
        self.settings = settings or PromptCompletionSettings()
        self.warm_requests = 0

    def get_prompt_completion_settings(self) -> PromptCompletionSettings:
        return self.settings

    def history_prompt_words(self) -> list[str] | None:
        return self.words

    def warm_history_prompt_words(self) -> None:
        self.warm_requests += 1


def test_history_builder_filters_casefold_prefix_in_mru_order() -> None:
    result = build_history_word_completion_result(
        "aL",
        2,
        ["ALPINE", "Alpha", "alphabet", "other"],
    )

    assert result is not None
    assert [candidate.insertion for candidate in result.candidates] == [
        "ALPINE",
        "Alpha",
        "alphabet",
    ]
    assert result.shared_extension == "P"


def test_history_builder_replaces_only_the_prefix_and_preserves_suffix() -> None:
    text = "pubZZZ"
    result = build_history_word_completion_result(
        text,
        len("pub"),
        ["pub", "publish", "publication"],
    )

    assert result is not None
    assert text[result.replacement_start : result.replacement_end] == "pub"
    assert result.replacement_end == len("pub")
    assert result.has_word_suffix is True
    assert [candidate.insertion for candidate in result.candidates] == [
        "pub",
        "publish",
        "publication",
    ]


def test_history_builder_suppresses_exact_prefix_spelling_without_suffix() -> None:
    result = build_history_word_completion_result(
        "pub",
        len("pub"),
        ["pub", "publish", "publication"],
    )

    assert result is not None
    assert result.has_word_suffix is False
    assert [candidate.insertion for candidate in result.candidates] == [
        "publish",
        "publication",
    ]


def test_history_builder_ignores_suffix_when_filtering() -> None:
    with_suffix = build_history_word_completion_result(
        "pubZZZ", len("pub"), ["publish", "publication"]
    )
    without_suffix = build_history_word_completion_result(
        "pub", len("pub"), ["publish", "publication"]
    )

    assert with_suffix is not None
    assert without_suffix is not None
    assert (
        [candidate.insertion for candidate in with_suffix.candidates]
        == [candidate.insertion for candidate in without_suffix.candidates]
        == ["publish", "publication"]
    )


def test_history_builder_uses_hyphenated_prefix_and_prefix_only_range() -> None:
    text = "bob-maZZZ"
    result = build_history_word_completion_result(
        text,
        len("bob-ma"),
        ["bob-mac-capture"],
    )

    assert result is not None
    assert result.prefix == "bob-ma"
    assert text[result.replacement_start : result.replacement_end] == "bob-ma"
    assert result.replacement_end == len("bob-ma")
    assert result.has_word_suffix is True
    assert [candidate.insertion for candidate in result.candidates] == [
        "bob-mac-capture"
    ]


async def test_ctrl_t_opens_history_words_after_local_miss() -> None:
    app = HistoryCompletionTestApp(["alpine", "alpha"])
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        ta.load_text("al")
        ta.cursor_location = (0, 2)

        await pilot.press("ctrl+t")

        assert ta.text == "alp"
        assert ta._completion_kind == HISTORY_WORD_COMPLETION_KIND
        assert [
            candidate.insertion for candidate in ta._file_completion_candidates
        ] == ["alpine", "alpha"]
        panel = bar.query_one("#prompt-completion", Static)
        rendered = panel.render()
        assert isinstance(rendered, Content)
        assert panel.border_title == "history words"
        assert panel.border_subtitle == "[^L] accept  [^D] delete"
        assert "📁" not in rendered.plain
        assert "📄" not in rendered.plain


async def test_ctrl_d_deletes_history_word_keeps_menu_open_and_toasts() -> None:
    app = HistoryCompletionTestApp(["review", "revise"])
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("re")
        ta.cursor_location = (0, 2)

        with (
            patch(
                "sase.ace.tui.util.io_async.schedule_persist",
            ) as schedule,
            patch.object(app, "notify") as notify,
        ):
            await pilot.press("ctrl+t", "ctrl+d")

        assert app.forgotten_history_words == ["review"]
        assert app.words == ["revise"]
        assert ta._file_completion_active is True
        assert [
            candidate.insertion for candidate in ta._file_completion_candidates
        ] == ["revise"]
        notify.assert_called_once_with(
            "Deleted history word: review",
            severity="information",
            markup=False,
        )
        assert schedule.call_args.args[0] is app
        assert schedule.call_args.args[2] == "review"
        before = app.warm_requests
        schedule.call_args.kwargs["on_error"](OSError("disk full"))
        assert app.warm_requests == before + 1


async def test_ctrl_d_history_word_falls_back_to_local_row_removal() -> None:
    app = HistoryCompletionTestApp(["review", "revise"])
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("re")
        ta.cursor_location = (0, 2)

        with (
            patch.object(
                CompletionTestApp,
                "forget_history_prompt_word",
                None,
            ),
            patch("sase.ace.tui.util.io_async.schedule_persist"),
        ):
            await pilot.press("ctrl+t", "ctrl+d")

        assert ta._file_completion_active is True
        assert [
            candidate.insertion for candidate in ta._file_completion_candidates
        ] == ["revise"]


async def test_ctrl_d_deleting_last_history_word_closes_menu() -> None:
    app = HistoryCompletionTestApp(["review", "revise"])
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("re")
        ta.cursor_location = (0, 2)

        with patch("sase.ace.tui.util.io_async.schedule_persist") as schedule:
            await pilot.press("ctrl+t", "ctrl+d", "ctrl+d")

        assert app.forgotten_history_words == ["review", "revise"]
        assert ta._file_completion_active is False
        assert schedule.call_count == 2


async def test_short_local_match_does_not_block_history_fallback() -> None:
    app = HistoryCompletionTestApp(["tiger"])
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("tiny ti")
        ta.cursor_location = (0, len(ta.text))

        await pilot.press("ctrl+t")

        assert ta.text == "tiny tiger"
        assert ta._file_completion_active is False


async def test_history_ctrl_t_mid_word_matches_goal_example() -> None:
    """The plan's motivating example: ``foo<cursor>baz`` -> ``foobar<cursor> baz``."""
    app = HistoryCompletionTestApp(["foobar"])
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("foobaz")
        ta.cursor_location = (0, len("foo"))

        await pilot.press("ctrl+t")

        assert ta.text == "foobar baz"
        assert ta.cursor_location == (0, len("foobar"))
        assert ta._file_completion_active is False


async def test_history_single_match_auto_accepts_and_preserves_suffix() -> None:
    app = HistoryCompletionTestApp(["publish"])
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("pubZZZ")
        ta.cursor_location = (0, len("pub"))

        await pilot.press("ctrl+t")

        assert ta.text == "publish ZZZ"
        assert ta.cursor_location == (0, len("publish"))
        assert ta._file_completion_active is False


async def test_history_hyphenated_prefix_auto_accepts_from_prompt_history() -> None:
    app = HistoryCompletionTestApp(["bob-mac-capture"])
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("bob-ma")
        ta.cursor_location = (0, len("bob-ma"))

        await pilot.press("ctrl+t")

        assert ta.text == "bob-mac-capture"
        assert ta._file_completion_active is False


async def test_history_hyphenated_acceptance_preserves_right_hand_suffix() -> None:
    app = HistoryCompletionTestApp(["bob-mac-capture"])
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("bob-maZZZ")
        ta.cursor_location = (0, len("bob-ma"))

        await pilot.press("ctrl+t")

        assert ta.text == "bob-mac-capture ZZZ"
        assert ta.cursor_location == (0, len("bob-mac-capture"))
        assert ta._file_completion_active is False


async def test_history_navigation_enter_accept_preserves_suffix() -> None:
    app = HistoryCompletionTestApp(["review", "revise"])
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("revZZZ")
        ta.cursor_location = (0, len("rev"))

        await pilot.press("ctrl+t", "down", "enter")

        assert ta.text == "revise ZZZ"
        assert ta.cursor_location == (0, len("revise"))
        assert ta._file_completion_active is False


async def test_history_navigation_ctrl_l_accept_preserves_suffix() -> None:
    app = HistoryCompletionTestApp(["review", "revise"])
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("revZZZ")
        ta.cursor_location = (0, len("rev"))

        await pilot.press("ctrl+t", "ctrl+l")

        assert ta.text == "review ZZZ"
        assert ta.cursor_location == (0, len("review"))
        assert ta._file_completion_active is False


async def test_history_refresh_narrows_and_switches_back_to_local() -> None:
    app = HistoryCompletionTestApp(["alpha", "alpine", "alps"])
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("algebra alp")
        ta.cursor_location = (0, len(ta.text))

        await pilot.press("ctrl+t", "h")
        assert [
            candidate.insertion for candidate in ta._file_completion_candidates
        ] == ["alpha"]

        await pilot.press("backspace", "backspace")

        assert ta.text == "algebra al"
        assert ta._completion_kind == PROMPT_WORD_COMPLETION_KIND
        assert [
            candidate.insertion for candidate in ta._file_completion_candidates
        ] == ["algebra"]


async def test_history_refresh_preserves_hyphenated_shared_prefix() -> None:
    app = HistoryCompletionTestApp(["bob-mac-capture", "bob-mac-camera"])
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("bob-ma")
        ta.cursor_location = (0, len("bob-ma"))

        await pilot.press("ctrl+t")

        assert ta.text == "bob-mac-ca"
        assert ta._completion_kind == HISTORY_WORD_COMPLETION_KIND
        assert [
            candidate.insertion for candidate in ta._file_completion_candidates
        ] == ["bob-mac-capture", "bob-mac-camera"]

        await pilot.press("p")

        assert ta.text == "bob-mac-cap"
        assert [
            candidate.insertion for candidate in ta._file_completion_candidates
        ] == ["bob-mac-capture"]

        await pilot.press("enter")

        assert ta.text == "bob-mac-capture"
        assert ta._file_completion_active is False


async def test_history_refresh_preserves_shared_prefix_narrowing_with_suffix() -> None:
    app = HistoryCompletionTestApp(["bob-mac-capture", "bob-mac-camera"])
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("bob-maZZZ")
        ta.cursor_location = (0, len("bob-ma"))

        await pilot.press("ctrl+t")

        assert ta.text == "bob-mac-caZZZ"
        assert ta._completion_kind == HISTORY_WORD_COMPLETION_KIND
        assert [
            candidate.insertion for candidate in ta._file_completion_candidates
        ] == ["bob-mac-capture", "bob-mac-camera"]

        await pilot.press("p")

        assert ta.text == "bob-mac-capZZZ"
        assert [
            candidate.insertion for candidate in ta._file_completion_candidates
        ] == ["bob-mac-capture"]

        await pilot.press("enter")

        assert ta.text == "bob-mac-capture ZZZ"
        assert ta.cursor_location == (0, len("bob-mac-capture"))
        assert ta._file_completion_active is False


async def test_history_refresh_does_not_yield_to_short_local_match() -> None:
    app = HistoryCompletionTestApp(["tiger", "title"])
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("tiny ti")
        ta.cursor_location = (0, len(ta.text))

        await pilot.press("ctrl+t", "g", "backspace")

        assert ta._completion_kind == HISTORY_WORD_COMPLETION_KIND
        assert [
            candidate.insertion for candidate in ta._file_completion_candidates
        ] == ["tiger", "title"]


async def test_local_refresh_falls_through_when_only_short_match_remains() -> None:
    app = HistoryCompletionTestApp(["tinyhouse", "tinydesk"])
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("tiny tinker tinted ti")
        ta.cursor_location = (0, len(ta.text))

        await pilot.press("ctrl+t")
        assert ta._completion_kind == PROMPT_WORD_COMPLETION_KIND
        assert ta.text.endswith("tin")

        await pilot.press("y")

        assert ta._completion_kind == HISTORY_WORD_COMPLETION_KIND
        assert [
            candidate.insertion for candidate in ta._file_completion_candidates
        ] == ["tinyhouse", "tinydesk"]


async def test_structured_cursor_dismisses_active_history_words() -> None:
    app = HistoryCompletionTestApp(["alpha", "alpine"])
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("%model:coder alp")
        ta.cursor_location = (0, len(ta.text))

        await pilot.press("ctrl+t", "home")

        assert ta.cursor_location == (0, 0)
        assert ta._file_completion_active is False


async def test_cold_cache_placeholder_applies_loaded_words() -> None:
    app = HistoryCompletionTestApp(None)
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        ta.load_text("rev")
        ta.cursor_location = (0, 3)

        await pilot.press("ctrl+t")

        assert ta._completion_kind == HISTORY_WORD_COMPLETION_KIND
        assert isinstance(
            ta._file_completion_candidates[0].metadata,
            HistoryWordCompletionPlaceholder,
        )
        panel = bar.query_one("#prompt-completion", Static)
        assert "loading history words…" in panel.render().plain
        assert panel.border_subtitle == ""
        assert app.warm_requests >= 1

        with (
            patch("sase.ace.tui.util.io_async.schedule_persist") as schedule,
            patch.object(app, "notify") as notify,
        ):
            await pilot.press("ctrl+d")

        assert isinstance(
            ta._file_completion_candidates[0].metadata,
            HistoryWordCompletionPlaceholder,
        )
        schedule.assert_not_called()
        notify.assert_not_called()

        app.words = ["review", "revise"]
        ta._apply_history_word_completion_result(app.words)
        assert [
            candidate.insertion for candidate in ta._file_completion_candidates
        ] == ["review", "revise"]


async def test_cold_cache_no_matches_dismisses_and_placeholder_is_not_accepted() -> (
    None
):
    app = HistoryCompletionTestApp(None)
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("rev")
        ta.cursor_location = (0, 3)

        await pilot.press("ctrl+t", "enter")
        assert ta.text == "rev"
        assert ta._file_completion_active is False

        await pilot.press("ctrl+t")
        app.words = ["unrelated"]
        ta._apply_history_word_completion_result(app.words)
        assert ta._file_completion_active is False


async def test_history_word_count_zero_disables_fallback() -> None:
    app = HistoryCompletionTestApp(
        ["review"],
        settings=PromptCompletionSettings(history_word_count=0),
    )
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("rev")
        ta.cursor_location = (0, 3)

        await pilot.press("ctrl+t")

        assert ta.text == "rev"
        assert ta._file_completion_active is False


async def test_warm_history_with_no_prefix_match_is_a_noop() -> None:
    app = HistoryCompletionTestApp(["unrelated"])
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("rev")
        ta.cursor_location = (0, 3)

        await pilot.press("ctrl+t")

        assert ta.text == "rev"
        assert ta._file_completion_active is False
