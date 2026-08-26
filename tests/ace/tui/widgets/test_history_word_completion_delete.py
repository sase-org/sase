"""Ctrl+D deletion tests for prompt-history word completion."""

from __future__ import annotations

from unittest.mock import patch

from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

from ._completion_helpers import CompletionTestApp
from ._history_word_completion_helpers import (
    HistoryCompletionTestApp,
    RankedHistoryCompletionTestApp,
    seeded_index,
    skip_unrelated_vcs_catalog_warm,  # noqa: F401 (registers the autouse fixture)
)


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


async def test_smart_mode_ctrl_d_deletes_instantly_without_rebuilding_index() -> None:
    index = seeded_index([("review", "260814_000000"), ("revise", "260813_000000")])
    app = RankedHistoryCompletionTestApp(index)
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("re")
        ta.cursor_location = (0, 2)

        with (
            patch("sase.ace.tui.util.io_async.schedule_persist"),
            patch.object(app, "notify"),
        ):
            before = app.warm_requests
            await pilot.press("ctrl+t", "ctrl+d")

        assert app.forgotten_history_words == ["review"]
        assert [
            candidate.insertion for candidate in ta._file_completion_candidates
        ] == ["revise"]
        assert app.index is index
        assert app.warm_requests == before


async def test_smart_mode_ctrl_d_persists_canonical_word_for_uppercase_prefix() -> None:
    index = seeded_index(
        [
            ("review", "260814_000000"),
            ("Review", "260813_000000"),
            ("revise", "260812_000000"),
        ]
    )
    app = RankedHistoryCompletionTestApp(index)
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("RE")
        ta.cursor_location = (0, len("RE"))

        with patch("sase.ace.tui.util.io_async.schedule_persist") as schedule:
            await pilot.press("ctrl+t", "ctrl+d")

    assert app.forgotten_history_words == ["review"]
    assert schedule.call_args.args[2] == "review"
    assert ta._file_completion_active is True
    assert [candidate.insertion for candidate in ta._file_completion_candidates] == [
        "REVISE"
    ]
