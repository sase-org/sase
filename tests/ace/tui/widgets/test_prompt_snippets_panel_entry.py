"""Widget-level tests for prompt ``gT`` / ``^GT`` snippets-panel requests."""

from __future__ import annotations

from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from tests.ace.tui.widgets.prompt_g_prefix_hint_test_support import GPrefixHintApp


async def test_gt_from_normal_posts_snippets_request() -> None:
    app = GPrefixHintApp("solo draft")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.press("escape", "g", "T")
        await pilot.pause()

        assert len(app.snippet_panel_requests) == 1
        event = app.snippet_panel_requests[0]
        assert event.mode == "prompt"
        assert event.trigger is None


async def test_ctrl_g_t_from_insert_posts_snippets_request() -> None:
    app = GPrefixHintApp("solo draft")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.press("ctrl+g", "T")
        await pilot.pause()

        assert len(app.snippet_panel_requests) == 1
        assert app.snippet_panel_requests[0].mode == "prompt"


async def test_lowercase_gt_does_not_open_snippets_panel() -> None:
    app = GPrefixHintApp("solo draft")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.press("escape", "g", "t")
        await pilot.pause()

        assert app.snippet_panel_requests == []


async def test_snippets_request_seeds_call_under_cursor() -> None:
    app = GPrefixHintApp("see #[greet] here")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()
        text_area.cursor_location = (0, 7)

        await pilot.press("escape", "g", "T")
        await pilot.pause()

        assert len(app.snippet_panel_requests) == 1
        assert app.snippet_panel_requests[0].trigger == "greet"


async def test_snippets_request_seeds_known_bare_trigger() -> None:
    app = GPrefixHintApp("expand greet now")
    app._snippets_cache = {"greet": "hello$0"}

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        bar.active_text_area().cursor_location = (0, 8)

        await pilot.press("escape", "g", "T")
        await pilot.pause()

        assert len(app.snippet_panel_requests) == 1
        assert app.snippet_panel_requests[0].trigger == "greet"


async def test_feedback_bar_does_not_hint_snippets() -> None:
    app = GPrefixHintApp("plan note", mode="feedback")

    async with app.run_test(size=(80, 24)):
        bar = app.query_one(PromptInputBar)
        keys = [entry.key for entry in bar.g_prefix_hint_entries()]
        assert "T" not in keys
