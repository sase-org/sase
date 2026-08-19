"""Widget-level tests for prompt ``gm`` / ``^Gm`` memory-panel requests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from tests.ace.tui.widgets.prompt_g_prefix_hint_test_support import GPrefixHintApp


async def test_gm_from_normal_posts_memory_request() -> None:
    app = GPrefixHintApp("solo draft")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.press("escape", "g", "m")
        await pilot.pause()

        assert len(app.memory_requests) == 1
        event = app.memory_requests[0]
        assert event.mode == "prompt"
        assert event.note_reference is None


async def test_ctrl_g_m_from_insert_posts_memory_request() -> None:
    app = GPrefixHintApp("solo draft")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.press("ctrl+g", "m")
        await pilot.pause()

        assert len(app.memory_requests) == 1
        assert app.memory_requests[0].mode == "prompt"
        assert app.memory_requests[0].note_reference is None


async def test_ctrl_g_m_from_normal_posts_memory_request() -> None:
    app = GPrefixHintApp("solo draft")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.press("escape", "ctrl+g", "m")
        await pilot.pause()

        assert len(app.memory_requests) == 1
        assert app.memory_requests[0].mode == "prompt"
        assert app.memory_requests[0].note_reference is None


async def test_memory_request_detects_live_memory_reference() -> None:
    text = "see #memory/sase_beads here"
    app = GPrefixHintApp(text)

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()
        text_area.cursor_location = (0, text.index("sase_beads"))

        await pilot.press("escape", "g", "m")
        await pilot.pause()

        assert len(app.memory_requests) == 1
        assert app.memory_requests[0].note_reference == "#memory/sase_beads"


async def test_memory_request_carries_note_under_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = GPrefixHintApp("see #memory/sase_beads here")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        monkeypatch.setattr(
            "sase.ace.tui.widgets._prompt_jump_target.detect_jump_target_at_cursor",
            lambda *_args, **_kwargs: SimpleNamespace(
                kind="xprompt",
                target="memory/sase_beads",
            ),
        )

        await pilot.press("escape", "g", "m")
        await pilot.pause()

        assert len(app.memory_requests) == 1
        assert app.memory_requests[0].note_reference == "#memory/sase_beads"


async def test_memory_request_is_none_for_non_memory_xprompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = GPrefixHintApp("see #run here")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        monkeypatch.setattr(
            "sase.ace.tui.widgets._prompt_jump_target.detect_jump_target_at_cursor",
            lambda *_args, **_kwargs: SimpleNamespace(
                kind="xprompt",
                target="run",
            ),
        )

        bar.request_open_memory_panel()
        await pilot.pause()

        assert len(app.memory_requests) == 1
        assert app.memory_requests[0].note_reference is None


async def test_feedback_bar_does_not_hint_memory() -> None:
    app = GPrefixHintApp("plan note", mode="feedback")

    async with app.run_test(size=(80, 24)):
        bar = app.query_one(PromptInputBar)
        keys = [entry.key for entry in bar.g_prefix_hint_entries()]
        assert "m" not in keys
