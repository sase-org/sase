"""Cold-cache and disabled-fallback tests for prompt-history word completion."""

from __future__ import annotations

from unittest.mock import patch

from textual.widgets import Static

from sase.ace.tui.widgets.history_word_completion import (
    HISTORY_WORD_COMPLETION_KIND,
    HistoryWordCompletionPlaceholder,
)
from sase.ace.tui.widgets.prompt_completion import PromptCompletionSettings
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

from ._history_word_completion_helpers import (
    HistoryCompletionTestApp,
    skip_unrelated_vcs_catalog_warm,  # noqa: F401 (registers the autouse fixture)
)


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
