"""Tests for prompt ``g`` prefix hint panel lifecycle and key handling."""

from __future__ import annotations

import pytest
from textual.events import Key

from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from tests.ace.tui.widgets.prompt_g_prefix_hint_test_support import (
    GPrefixHintApp,
    hint_panel,
)


async def test_g_in_normal_mode_shows_g_prefix_hints() -> None:
    app = GPrefixHintApp("solo draft")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        panel = hint_panel(bar)

        assert panel.has_class("hidden")
        await pilot.press("escape")
        await pilot.press("g")
        await pilot.pause()

        assert not panel.has_class("hidden")
        assert panel.border_title == " g "
        assert panel.border_subtitle == "\\[esc] cancel"
        plain = panel.render().plain
        assert "gf   format prompt" in plain
        assert "gG   glossary…" in plain
        assert "g<enter>   submit this draft" in plain
        assert "g-   add pane" in plain
        assert "g=   toggle frontmatter" in plain
        assert "gx   save as xprompt" in plain
        assert "g^X" not in plain
        # Multi-pane and stash-open entries are absent on the bare g surface.
        assert "gs" not in plain
        assert "gS" not in plain
        assert "gj" not in plain
        assert "gp" not in plain
        assert "gP" not in plain


async def test_ctrl_g_in_insert_mode_shows_insert_prefix_hints() -> None:
    app = GPrefixHintApp("solo draft", stash_exists=True)

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        panel = hint_panel(bar)

        assert panel.has_class("hidden")
        await pilot.press("ctrl+g")
        await pilot.pause()

        assert not panel.has_class("hidden")
        assert panel.border_title == " ^G "
        assert panel.border_subtitle == "\\[esc] cancel"
        plain = panel.render().plain
        assert "^Gg / ^G^G   edit in editor" in plain
        assert "^Gf   format prompt" in plain
        assert "^GG   glossary…" in plain
        assert "^G<enter>   submit this draft" in plain
        assert "^G^C   cancel all panes" in plain
        assert "^G-   add pane" in plain
        assert "^G=   toggle frontmatter" in plain
        assert "^Gx / ^G^X   save as xprompt" in plain
        assert "^Gp   stashed prompts…" in plain
        assert "^Gs" not in plain
        assert "^GS" not in plain
        assert "^GP" not in plain


async def test_ctrl_g_in_normal_mode_shows_same_prefix_hints_as_insert() -> None:
    app = GPrefixHintApp("solo draft")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        panel = hint_panel(bar)

        assert panel.has_class("hidden")
        await pilot.press("escape")  # enter NORMAL mode
        await pilot.press("ctrl+g")
        await pilot.pause()

        # NORMAL-mode ``Ctrl+G`` shares the INSERT-mode ``^G`` hint surface,
        # including the editor continuation and the prompt-specific entries.
        assert not panel.has_class("hidden")
        assert panel.border_title == " ^G "
        assert panel.border_subtitle == "\\[esc] cancel"
        plain = panel.render().plain
        assert "^Gg / ^G^G   edit in editor" in plain
        assert "^Gf   format prompt" in plain
        assert "^GG   glossary…" in plain
        assert "^G<enter>   submit this draft" in plain
        assert "^G^C   cancel all panes" in plain
        assert "^G-   add pane" in plain
        assert "^G=   toggle frontmatter" in plain
        assert "^Gx / ^G^X   save as xprompt" in plain
        assert "^Gs" not in plain
        assert "^GS" not in plain
        assert bar.active_text_area()._vim_mode == "normal"
        assert bar.active_text_area()._normal_g_prefix_pending is True


async def test_normal_ctrl_g_continuation_dispatches_in_normal_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = GPrefixHintApp("solo draft")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        panel = hint_panel(bar)

        calls: list[str] = []
        monkeypatch.setattr(bar, "toggle_frontmatter_panel", lambda: calls.append("="))

        await pilot.press("escape", "ctrl+g", "=")
        await pilot.pause()

        # The non-editor continuation dispatched through the prompt bar and the
        # hint panel closed afterward, leaving the pane in NORMAL mode.
        assert calls == ["="]
        assert panel.has_class("hidden")
        assert bar._g_prefix_hints_visible is False
        assert bar.active_text_area()._normal_g_prefix_pending is False
        assert bar.active_text_area()._vim_mode == "normal"


@pytest.mark.parametrize("continuation", ["x", "ctrl+x"])
@pytest.mark.parametrize("start_normal", [False, True], ids=["insert", "normal"])
async def test_ctrl_g_save_continuations_preserve_draft_and_clear_prefix(
    continuation: str,
    start_normal: bool,
) -> None:
    app = GPrefixHintApp("reusable draft")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()

        if start_normal:
            await pilot.press("escape")
        await pilot.press("ctrl+g", continuation)
        await pilot.pause()

        assert len(app.save_xprompt_requests) == 1
        assert [pane.text for pane in app.save_xprompt_requests[0].panes] == [
            "reusable draft"
        ]
        assert bar.all_prompt_texts() == ["reusable draft"]
        assert text_area._insert_g_prefix_pending is False
        assert text_area._normal_g_prefix_pending is False
        assert bar._g_prefix_hints_visible is False
        assert text_area._vim_mode == ("normal" if start_normal else "insert")


async def test_real_terminal_ctrl_g_ctrl_c_cancels_all_from_insert() -> None:
    app = GPrefixHintApp("first\n---\nsecond")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        panel = hint_panel(bar)

        await pilot.press("ctrl+g")
        await pilot.pause()
        text_area = bar.active_text_area()

        assert text_area._insert_g_prefix_pending is True
        assert not panel.has_class("hidden")

        assert text_area._handle_insert_g_prefix_key(Key("ctrl+c", "\x03")) is True
        await pilot.pause()

        assert len(app.cancelled) == 1
        event = app.cancelled[0]
        assert event.cancelled_text == "first\n---\nsecond"
        assert event.keep_bar is False
        assert event.record_segments is False
        assert panel.has_class("hidden")
        assert bar._g_prefix_hints_visible is False
        assert text_area._insert_g_prefix_pending is False


async def test_real_terminal_ctrl_g_ctrl_c_cancels_all_from_normal() -> None:
    app = GPrefixHintApp("first\n---\nsecond")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        panel = hint_panel(bar)

        await pilot.press("escape", "ctrl+g")
        await pilot.pause()
        text_area = bar.active_text_area()

        assert text_area._vim_mode == "normal"
        assert text_area._normal_g_prefix_pending is True
        assert not panel.has_class("hidden")

        assert text_area._handle_normal_g_prefix_key(Key("ctrl+c", "\x03")) is True
        await pilot.pause()

        assert len(app.cancelled) == 1
        event = app.cancelled[0]
        assert event.cancelled_text == "first\n---\nsecond"
        assert event.keep_bar is False
        assert event.record_segments is False
        assert panel.has_class("hidden")
        assert bar._g_prefix_hints_visible is False
        assert text_area._normal_g_prefix_pending is False
        assert text_area._vim_mode == "normal"


async def test_normal_ctrl_g_escape_cancels_prefix_and_stays_normal_mode() -> None:
    app = GPrefixHintApp("solo draft")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        panel = hint_panel(bar)

        await pilot.press("escape", "ctrl+g")
        await pilot.pause()
        assert not panel.has_class("hidden")

        await pilot.press("escape")
        await pilot.pause()

        assert panel.has_class("hidden")
        assert bar._g_prefix_hints_visible is False
        assert bar.active_text_area()._normal_g_prefix_pending is False
        assert bar.active_text_area()._vim_mode == "normal"


async def test_normal_unknown_ctrl_g_key_hides_hints_without_side_effects() -> None:
    app = GPrefixHintApp("solo draft", stash_exists=True)

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        panel = hint_panel(bar)

        await pilot.press("escape", "ctrl+g")
        await pilot.pause()
        assert not panel.has_class("hidden")

        # ``^Gz`` is neither a prompt continuation nor an editor key.
        await pilot.press("z")
        await pilot.pause()

        assert panel.has_class("hidden")
        assert bar.active_text() == "solo draft"
        assert bar.active_text_area()._vim_mode == "normal"
        assert app.stashed == []
        assert app.restore_requests == []


async def test_second_g_prefix_key_hides_hints_after_dispatch() -> None:
    app = GPrefixHintApp("solo draft")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        panel = hint_panel(bar)

        await pilot.press("escape", "g", "=")
        await pilot.pause()

        assert panel.has_class("hidden")
        assert bar._g_prefix_hints_visible is False


async def test_escape_hides_pending_g_prefix_hints() -> None:
    app = GPrefixHintApp("solo draft")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        panel = hint_panel(bar)

        await pilot.press("escape", "g")
        await pilot.pause()
        assert not panel.has_class("hidden")

        await pilot.press("escape")
        await pilot.pause()

        assert panel.has_class("hidden")
        assert bar._g_prefix_hints_visible is False


async def test_escape_cancels_insert_prefix_and_stays_insert_mode() -> None:
    app = GPrefixHintApp("solo draft")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        panel = hint_panel(bar)

        await pilot.press("ctrl+g")
        await pilot.pause()
        assert not panel.has_class("hidden")

        await pilot.press("escape")
        await pilot.pause()

        assert panel.has_class("hidden")
        assert bar._g_prefix_hints_visible is False
        assert bar.active_text_area()._insert_g_prefix_pending is False
        assert bar.active_text_area()._vim_mode == "insert"


async def test_unknown_g_prefix_key_hides_hints_without_side_effects() -> None:
    app = GPrefixHintApp("solo draft", stash_exists=True)

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        panel = hint_panel(bar)

        await pilot.press("escape", "g")
        await pilot.pause()
        assert not panel.has_class("hidden")

        # ``gz`` is neither a prompt continuation nor a vim ``g`` command.
        await pilot.press("z")
        await pilot.pause()

        assert panel.has_class("hidden")
        assert app.stashed == []
        assert app.restore_requests == []


async def test_unknown_insert_prefix_key_hides_hints_without_inserting() -> None:
    app = GPrefixHintApp("solo draft", stash_exists=True)

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        panel = hint_panel(bar)

        await pilot.press("ctrl+g")
        await pilot.pause()
        assert not panel.has_class("hidden")

        await pilot.press("z")
        await pilot.pause()

        assert panel.has_class("hidden")
        assert bar.active_text() == "solo draft"
        assert app.stashed == []
        assert app.restore_requests == []


async def test_feedback_panel_shows_format_entry() -> None:
    app = GPrefixHintApp("plan note", mode="feedback", stash_exists=True)

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        panel = hint_panel(bar)

        await pilot.press("escape", "g")
        await pilot.pause()

        assert not panel.has_class("hidden")
        assert "gf   format prompt" in panel.render().plain
        assert bar._g_prefix_hints_visible is True
