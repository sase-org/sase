"""Tests for context-aware prompt ``g`` prefix hint entries."""

from __future__ import annotations

from textual.events import Key

from sase.ace.tui.widgets._prompt_text_area_key_g_prefix import (
    _resolve_g_prefix_second_key,
)
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from tests.ace.tui.widgets.prompt_g_prefix_hint_test_support import (
    GPrefixHintApp,
    entry_pairs,
)


def test_resolve_g_prefix_second_key_uses_printable_characters_only() -> None:
    assert _resolve_g_prefix_second_key(Key("ctrl+c", "\x03")) == "ctrl+c"
    assert _resolve_g_prefix_second_key(Key("ctrl+x", "\x18")) == "ctrl+x"
    assert _resolve_g_prefix_second_key(Key("enter", "\r")) == "enter"
    assert _resolve_g_prefix_second_key(Key("minus", "-")) == "-"
    assert _resolve_g_prefix_second_key(Key("equals_sign", "=")) == "="
    assert _resolve_g_prefix_second_key(Key("j", "j")) == "j"


# --- context-aware hint entries --------------------------------------------


async def test_single_pane_hint_entries_hide_multi_pane_and_stash_actions() -> None:
    app = GPrefixHintApp("solo draft")

    async with app.run_test(size=(80, 24)):
        bar = app.query_one(PromptInputBar)

        # No multi-pane nav (single pane), no stash restore (empty stash).
        assert entry_pairs(bar) == [
            ("f", "format prompt"),
            ("G", "glossary…"),
            ("m", "memory…"),
            ("enter", "submit this draft"),
            ("-", "add pane"),
            ("=", "toggle frontmatter"),
            ("t", "new snippet…"),
            ("x", "save as xprompt"),
            ("X", "save as local xprompt"),
        ]


async def test_single_pane_with_stash_hides_open_stash_on_bare_g() -> None:
    app = GPrefixHintApp("solo draft", stash_exists=True)

    async with app.run_test(size=(80, 24)):
        bar = app.query_one(PromptInputBar)

        assert entry_pairs(bar) == [
            ("f", "format prompt"),
            ("G", "glossary…"),
            ("m", "memory…"),
            ("enter", "submit this draft"),
            ("-", "add pane"),
            ("=", "toggle frontmatter"),
            ("t", "new snippet…"),
            ("x", "save as xprompt"),
            ("X", "save as local xprompt"),
        ]


async def test_single_pane_with_stash_includes_open_stash_on_ctrl_g() -> None:
    app = GPrefixHintApp("solo draft", stash_exists=True)

    async with app.run_test(size=(80, 24)):
        bar = app.query_one(PromptInputBar)

        assert entry_pairs(bar, via_ctrl_g=True) == [
            ("f", "format prompt"),
            ("G", "glossary…"),
            ("m", "memory…"),
            ("enter", "submit this draft"),
            ("ctrl+c", "cancel all panes"),
            ("-", "add pane"),
            ("=", "toggle frontmatter"),
            ("t", "new snippet…"),
            ("x", "save as xprompt"),
            ("X", "save as local xprompt"),
            ("p", "stashed prompts…"),
        ]

        bare_save = next(
            entry for entry in bar.g_prefix_hint_entries() if entry.key == "x"
        )
        ctrl_g_save = next(
            entry
            for entry in bar.g_prefix_hint_entries(via_ctrl_g=True)
            if entry.key == "x"
        )
        assert bare_save.aliases == ()
        assert ctrl_g_save.aliases == ("ctrl+x",)


async def test_single_pane_with_pin_includes_update_pin_on_bare_and_ctrl_g() -> None:
    app = GPrefixHintApp("solo draft", stash_exists=True, pinned_exists=True)

    async with app.run_test(size=(80, 24)):
        bar = app.query_one(PromptInputBar)

        assert entry_pairs(bar) == [
            ("f", "format prompt"),
            ("G", "glossary…"),
            ("m", "memory…"),
            ("enter", "submit this draft"),
            ("-", "add pane"),
            ("=", "toggle frontmatter"),
            ("S", "update pinned stash"),
            ("t", "new snippet…"),
            ("x", "save as xprompt"),
            ("X", "save as local xprompt"),
        ]
        assert entry_pairs(bar, via_ctrl_g=True) == [
            ("f", "format prompt"),
            ("G", "glossary…"),
            ("m", "memory…"),
            ("enter", "submit this draft"),
            ("ctrl+c", "cancel all panes"),
            ("-", "add pane"),
            ("=", "toggle frontmatter"),
            ("S", "update pinned stash"),
            ("t", "new snippet…"),
            ("x", "save as xprompt"),
            ("X", "save as local xprompt"),
            ("p", "stashed prompts…"),
        ]


async def test_update_pin_hint_requires_non_empty_prompt() -> None:
    app = GPrefixHintApp("", stash_exists=True, pinned_exists=True)

    async with app.run_test(size=(80, 24)):
        bar = app.query_one(PromptInputBar)

        assert ("f", "format prompt") not in entry_pairs(bar)
        assert ("S", "update pinned stash") not in entry_pairs(bar)


async def test_multi_pane_hint_entries_include_nav_and_stash() -> None:
    app = GPrefixHintApp(
        "first\n---\nsecond",
        stash_exists=True,
        pinned_exists=True,
    )

    async with app.run_test(size=(80, 24)):
        bar = app.query_one(PromptInputBar)

        assert entry_pairs(bar) == [
            ("f", "format prompt"),
            ("G", "glossary…"),
            ("m", "memory…"),
            ("enter", "launch this pane"),
            ("j", "focus next pane"),
            ("k", "focus prev pane"),
            ("J", "move pane down"),
            ("K", "move pane up"),
            ("-", "add pane"),
            ("=", "toggle frontmatter"),
            ("s", "stash all panes"),
            ("S", "update pinned stash"),
            ("t", "new snippet…"),
            ("x", "save as xprompt"),
            ("X", "save as local xprompt"),
        ]

        ctrl_g_entries = entry_pairs(bar, via_ctrl_g=True)
        assert ("ctrl+c", "cancel all panes") in ctrl_g_entries
        assert ctrl_g_entries[-1] == ("p", "stashed prompts…")


async def test_multi_pane_without_stash_hides_load_and_restore() -> None:
    app = GPrefixHintApp("first\n---\nsecond")

    async with app.run_test(size=(80, 24)):
        bar = app.query_one(PromptInputBar)

        keys = [key for key, _ in entry_pairs(bar)]
        assert "p" not in keys
        assert "P" not in keys
        # Multi-pane nav and stash-all stay available.
        assert keys == [
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
            "t",
            "x",
            "X",
        ]


async def test_feedback_bar_hints_prompt_formatting_only() -> None:
    app = GPrefixHintApp("plan note", mode="feedback", stash_exists=True)

    async with app.run_test(size=(80, 24)):
        bar = app.query_one(PromptInputBar)

        assert entry_pairs(bar) == [("f", "format prompt")]
