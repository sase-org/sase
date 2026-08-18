"""Widget-level tests for prompt ``gG`` / ``^GG`` glossary-panel requests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from tests.ace.tui.widgets.prompt_g_prefix_hint_test_support import GPrefixHintApp


async def test_gg_from_normal_posts_glossary_request() -> None:
    app = GPrefixHintApp("solo draft")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.press("escape", "g", "G")
        await pilot.pause()

        assert len(app.glossary_requests) == 1
        event = app.glossary_requests[0]
        assert event.mode == "prompt"
        assert event.term is None


async def test_ctrl_g_g_from_insert_posts_glossary_request() -> None:
    app = GPrefixHintApp("solo draft")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.press("ctrl+g", "G")
        await pilot.pause()

        assert len(app.glossary_requests) == 1
        assert app.glossary_requests[0].mode == "prompt"
        assert app.glossary_requests[0].term is None


async def test_ctrl_g_g_from_normal_posts_glossary_request() -> None:
    app = GPrefixHintApp("solo draft")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.press("escape", "ctrl+g", "G")
        await pilot.pause()

        assert len(app.glossary_requests) == 1
        assert app.glossary_requests[0].mode == "prompt"
        assert app.glossary_requests[0].term is None


async def test_glossary_request_carries_term_under_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = GPrefixHintApp("see Agent Hood here")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()
        monkeypatch.setattr(
            text_area,
            "_glossary_match_under_cursor",
            lambda *, schedule=False: (
                object(),
                object(),
                SimpleNamespace(term="Agent Hood"),
            ),
        )

        await pilot.press("escape", "g", "G")
        await pilot.pause()

        assert len(app.glossary_requests) == 1
        assert app.glossary_requests[0].term == "Agent Hood"


async def test_glossary_request_is_none_when_catalog_is_cold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = GPrefixHintApp("see Agent Hood here")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        monkeypatch.setattr(
            bar.active_text_area(),
            "_glossary_match_under_cursor",
            lambda *, schedule=False: object(),
        )

        bar.request_open_glossary_panel()
        await pilot.pause()

        assert len(app.glossary_requests) == 1
        assert app.glossary_requests[0].term is None


async def test_feedback_bar_does_not_hint_glossary() -> None:
    app = GPrefixHintApp("plan note", mode="feedback")

    async with app.run_test(size=(80, 24)):
        bar = app.query_one(PromptInputBar)
        keys = [entry.key for entry in bar.g_prefix_hint_entries()]
        assert "G" not in keys
