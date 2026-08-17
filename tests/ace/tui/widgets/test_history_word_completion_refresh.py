"""Refresh and narrowing tests for prompt-history word completion."""

from __future__ import annotations

from sase.ace.tui.widgets.history_word_completion import (
    HISTORY_WORD_COMPLETION_KIND,
)
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.ace.tui.widgets.prompt_word_completion import PROMPT_WORD_COMPLETION_KIND

from ._history_word_completion_helpers import (
    HistoryCompletionTestApp,
    skip_unrelated_vcs_catalog_warm,  # noqa: F401 (registers the autouse fixture)
)


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
