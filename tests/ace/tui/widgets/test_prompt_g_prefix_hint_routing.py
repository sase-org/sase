"""Tests for prompt ``g`` prefix dispatch and Vim routing."""

from __future__ import annotations

import pytest

from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from tests.ace.tui.widgets.prompt_g_prefix_hint_test_support import (
    GPrefixHintApp,
    hint_panel,
)


async def test_gg_still_jumps_to_buffer_start_after_hint_integration() -> None:
    app = GPrefixHintApp("line0\nline1\nline2")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()
        await pilot.press("escape")
        text_area.cursor_location = (2, 0)

        await pilot.press("g", "g")
        await pilot.pause()

        assert text_area.cursor_location == (0, 0)
        assert hint_panel(bar).has_class("hidden")


async def test_counted_gg_jumps_to_target_line_after_hint_integration() -> None:
    app = GPrefixHintApp("line0\nline1\nline2\nline3")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()
        await pilot.press("escape")
        text_area.cursor_location = (0, 0)

        await pilot.press("3", "g", "g")
        await pilot.pause()

        assert text_area.cursor_location == (2, 0)
        assert hint_panel(bar).has_class("hidden")


# --- dispatch routing ------------------------------------------------------


async def test_dispatch_g_prefix_key_routes_each_continuation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = GPrefixHintApp("solo draft")

    async with app.run_test(size=(80, 24)):
        bar = app.query_one(PromptInputBar)
        calls: list[str] = []
        monkeypatch.setattr(
            bar, "focus_relative", lambda delta, **_: calls.append(f"focus{delta:+d}")
        )
        monkeypatch.setattr(
            bar, "move_active_pane", lambda delta, **_: calls.append(f"move{delta:+d}")
        )
        monkeypatch.setattr(bar, "format_active_prompt", lambda: calls.append("f"))
        monkeypatch.setattr(bar, "submit_active_pane", lambda: calls.append("enter"))
        monkeypatch.setattr(bar, "action_cancel_all", lambda: calls.append("ctrl+c"))
        monkeypatch.setattr(bar, "add_bottom_pane", lambda: calls.append("-"))
        monkeypatch.setattr(bar, "toggle_frontmatter_panel", lambda: calls.append("="))
        monkeypatch.setattr(bar, "stash_all_panes", lambda: calls.append("s"))
        monkeypatch.setattr(
            bar, "request_update_pinned_stash", lambda: calls.append("S")
        )
        monkeypatch.setattr(
            bar, "request_snippet_target_pane", lambda: calls.append("t")
        )
        monkeypatch.setattr(
            bar, "request_mini_xprompt_target_pane", lambda: calls.append("x")
        )
        monkeypatch.setattr(bar, "request_save_as_xprompt", lambda: calls.append("X"))
        monkeypatch.setattr(
            bar,
            "convert_active_pane_to_local_xprompt",
            lambda **_: calls.append("L"),
        )
        monkeypatch.setattr(bar, "request_open_prompt_stash", lambda: calls.append("p"))
        monkeypatch.setattr(
            bar, "request_open_glossary_panel", lambda: calls.append("G")
        )
        monkeypatch.setattr(bar, "request_open_memory_panel", lambda: calls.append("m"))
        monkeypatch.setattr(
            bar, "request_open_snippets_panel", lambda: calls.append("T")
        )

        for key in (
            "f",
            "G",
            "m",
            "enter",
            "j",
            "k",
            "J",
            "K",
            "-",
            "=",
            "s",
            "S",
            "t",
            "T",
            "x",
            "X",
            "L",
        ):
            assert bar.dispatch_g_prefix_key(key) is True
        assert bar.dispatch_g_prefix_key("ctrl+c") is False
        assert bar.dispatch_g_prefix_key("ctrl+c", via_ctrl_g=True) is True
        assert bar.dispatch_g_prefix_key("ctrl+x") is False
        assert bar.dispatch_g_prefix_key("ctrl+x", via_ctrl_g=True) is True
        assert bar.dispatch_g_prefix_key("p") is False
        assert bar.dispatch_g_prefix_key("p", via_ctrl_g=True) is True
        assert bar.dispatch_g_prefix_key("S", via_ctrl_g=True) is True
        assert bar.dispatch_g_prefix_key("P", via_ctrl_g=True) is False
        # Unknown / vim-owned continuations fall through to vim.
        assert bar.dispatch_g_prefix_key("g") is False
        assert bar.dispatch_g_prefix_key("u") is False
        assert bar.dispatch_g_prefix_key("z") is False

        assert calls == [
            "f",
            "G",
            "m",
            "enter",
            "focus+1",
            "focus-1",
            "move+1",
            "move-1",
            "-",
            "=",
            "s",
            "S",
            "t",
            "T",
            "x",
            "X",
            "L",
            "ctrl+c",
            "X",
            "p",
            "S",
        ]


async def test_dispatch_g_prefix_key_can_target_insert_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = GPrefixHintApp("one\n---\ntwo")

    async with app.run_test(size=(80, 24)):
        bar = app.query_one(PromptInputBar)
        calls: list[str] = []
        monkeypatch.setattr(
            bar,
            "focus_relative",
            lambda delta, *, target_mode="normal": calls.append(
                f"focus{delta:+d}:{target_mode}"
            ),
        )
        monkeypatch.setattr(
            bar,
            "move_active_pane",
            lambda delta, *, target_mode="normal": calls.append(
                f"move{delta:+d}:{target_mode}"
            ),
        )
        monkeypatch.setattr(
            bar,
            "convert_active_pane_to_local_xprompt",
            lambda *, target_mode="normal": calls.append(f"L:{target_mode}"),
        )

        assert bar.dispatch_g_prefix_key("j", target_mode="insert") is True
        assert bar.dispatch_g_prefix_key("K", target_mode="insert") is True
        assert bar.dispatch_g_prefix_key("L", target_mode="insert") is True

        assert calls == ["focus+1:insert", "move-1:insert", "L:insert"]
