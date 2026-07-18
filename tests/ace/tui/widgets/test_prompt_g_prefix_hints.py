"""Widget-level tests for the prompt ``g`` prefix hint panel."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.events import Key
from textual.widgets import Static

from sase.ace.tui.widgets._prompt_text_area_key_handling import (
    _resolve_g_prefix_second_key,
)
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar


class _GPrefixHintApp(App[None]):
    """Hosts a prompt bar and exposes prompt-stash availability."""

    ENABLE_COMMAND_PALETTE = False

    def __init__(
        self,
        initial_value: str = "",
        *,
        mode: str = "prompt",
        stash_exists: bool = False,
        pinned_exists: bool = False,
    ) -> None:
        super().__init__()
        self._initial_value = initial_value
        self._mode = mode
        self._stash_exists = stash_exists
        self._pinned_exists = pinned_exists
        self.cancelled: list[PromptInputBar.Cancelled] = []
        self.stashed: list[PromptInputBar.Stashed] = []
        self.restore_requests: list[PromptInputBar.RestoreRequested] = []
        self.update_requests: list[PromptInputBar.UpdatePinnedRequested] = []
        self.save_xprompt_requests: list[PromptInputBar.SaveAsXpromptRequested] = []

    def compose(self) -> ComposeResult:
        yield PromptInputBar(
            initial_value=self._initial_value,
            mode=self._mode,
            id="prompt-input-bar",
        )

    def _has_stashed_prompts(self) -> bool:
        return self._stash_exists

    def _has_pinned_stashed_prompts(self) -> bool:
        return self._pinned_exists

    def on_prompt_input_bar_stashed(self, event: PromptInputBar.Stashed) -> None:
        self.stashed.append(event)

    def on_prompt_input_bar_restore_requested(
        self, event: PromptInputBar.RestoreRequested
    ) -> None:
        self.restore_requests.append(event)

    def on_prompt_input_bar_update_pinned_requested(
        self, event: PromptInputBar.UpdatePinnedRequested
    ) -> None:
        self.update_requests.append(event)

    def on_prompt_input_bar_save_as_xprompt_requested(
        self, event: PromptInputBar.SaveAsXpromptRequested
    ) -> None:
        self.save_xprompt_requests.append(event)

    def on_prompt_input_bar_cancelled(self, event: PromptInputBar.Cancelled) -> None:
        self.cancelled.append(event)


def _entry_pairs(
    bar: PromptInputBar, *, via_ctrl_g: bool = False
) -> list[tuple[str, str]]:
    return [
        (entry.key, entry.label)
        for entry in bar.g_prefix_hint_entries(via_ctrl_g=via_ctrl_g)
    ]


def _hint_panel(bar: PromptInputBar) -> Static:
    return bar.query_one("#prompt-g-prefix-hints", Static)


def test_resolve_g_prefix_second_key_uses_printable_characters_only() -> None:
    assert _resolve_g_prefix_second_key(Key("ctrl+c", "\x03")) == "ctrl+c"
    assert _resolve_g_prefix_second_key(Key("ctrl+x", "\x18")) == "ctrl+x"
    assert _resolve_g_prefix_second_key(Key("enter", "\r")) == "enter"
    assert _resolve_g_prefix_second_key(Key("minus", "-")) == "-"
    assert _resolve_g_prefix_second_key(Key("equals_sign", "=")) == "="
    assert _resolve_g_prefix_second_key(Key("j", "j")) == "j"


# --- context-aware hint entries --------------------------------------------


async def test_single_pane_hint_entries_hide_multi_pane_and_stash_actions() -> None:
    app = _GPrefixHintApp("solo draft")

    async with app.run_test(size=(80, 24)):
        bar = app.query_one(PromptInputBar)

        # No multi-pane nav (single pane), no stash restore (empty stash).
        assert _entry_pairs(bar) == [
            ("f", "format prompt"),
            ("enter", "submit this draft"),
            ("-", "add pane"),
            ("=", "toggle frontmatter"),
            ("x", "save as xprompt"),
            ("X", "save as local xprompt"),
        ]


async def test_single_pane_with_stash_hides_open_stash_on_bare_g() -> None:
    app = _GPrefixHintApp("solo draft", stash_exists=True)

    async with app.run_test(size=(80, 24)):
        bar = app.query_one(PromptInputBar)

        assert _entry_pairs(bar) == [
            ("f", "format prompt"),
            ("enter", "submit this draft"),
            ("-", "add pane"),
            ("=", "toggle frontmatter"),
            ("x", "save as xprompt"),
            ("X", "save as local xprompt"),
        ]


async def test_single_pane_with_stash_includes_open_stash_on_ctrl_g() -> None:
    app = _GPrefixHintApp("solo draft", stash_exists=True)

    async with app.run_test(size=(80, 24)):
        bar = app.query_one(PromptInputBar)

        assert _entry_pairs(bar, via_ctrl_g=True) == [
            ("f", "format prompt"),
            ("enter", "submit this draft"),
            ("ctrl+c", "cancel all panes"),
            ("-", "add pane"),
            ("=", "toggle frontmatter"),
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
    app = _GPrefixHintApp("solo draft", stash_exists=True, pinned_exists=True)

    async with app.run_test(size=(80, 24)):
        bar = app.query_one(PromptInputBar)

        assert _entry_pairs(bar) == [
            ("f", "format prompt"),
            ("enter", "submit this draft"),
            ("-", "add pane"),
            ("=", "toggle frontmatter"),
            ("S", "update pinned stash"),
            ("x", "save as xprompt"),
            ("X", "save as local xprompt"),
        ]
        assert _entry_pairs(bar, via_ctrl_g=True) == [
            ("f", "format prompt"),
            ("enter", "submit this draft"),
            ("ctrl+c", "cancel all panes"),
            ("-", "add pane"),
            ("=", "toggle frontmatter"),
            ("S", "update pinned stash"),
            ("x", "save as xprompt"),
            ("X", "save as local xprompt"),
            ("p", "stashed prompts…"),
        ]


async def test_update_pin_hint_requires_non_empty_prompt() -> None:
    app = _GPrefixHintApp("", stash_exists=True, pinned_exists=True)

    async with app.run_test(size=(80, 24)):
        bar = app.query_one(PromptInputBar)

        assert ("f", "format prompt") not in _entry_pairs(bar)
        assert ("S", "update pinned stash") not in _entry_pairs(bar)


async def test_multi_pane_hint_entries_include_nav_and_stash() -> None:
    app = _GPrefixHintApp(
        "first\n---\nsecond",
        stash_exists=True,
        pinned_exists=True,
    )

    async with app.run_test(size=(80, 24)):
        bar = app.query_one(PromptInputBar)

        assert _entry_pairs(bar) == [
            ("f", "format prompt"),
            ("enter", "launch this pane"),
            ("j", "focus next pane"),
            ("k", "focus prev pane"),
            ("J", "move pane down"),
            ("K", "move pane up"),
            ("-", "add pane"),
            ("=", "toggle frontmatter"),
            ("s", "stash all panes"),
            ("S", "update pinned stash"),
            ("x", "save as xprompt"),
            ("X", "save as local xprompt"),
        ]

        ctrl_g_entries = _entry_pairs(bar, via_ctrl_g=True)
        assert ("ctrl+c", "cancel all panes") in ctrl_g_entries
        assert ctrl_g_entries[-1] == ("p", "stashed prompts…")


async def test_multi_pane_without_stash_hides_load_and_restore() -> None:
    app = _GPrefixHintApp("first\n---\nsecond")

    async with app.run_test(size=(80, 24)):
        bar = app.query_one(PromptInputBar)

        keys = [key for key, _ in _entry_pairs(bar)]
        assert "p" not in keys
        assert "P" not in keys
        # Multi-pane nav and stash-all stay available.
        assert keys == [
            "f",
            "enter",
            "j",
            "k",
            "J",
            "K",
            "-",
            "=",
            "s",
            "x",
            "X",
        ]


async def test_feedback_bar_hints_prompt_formatting_only() -> None:
    app = _GPrefixHintApp("plan note", mode="feedback", stash_exists=True)

    async with app.run_test(size=(80, 24)):
        bar = app.query_one(PromptInputBar)

        assert _entry_pairs(bar) == [("f", "format prompt")]


# --- show / hide lifecycle -------------------------------------------------


async def test_g_in_normal_mode_shows_g_prefix_hints() -> None:
    app = _GPrefixHintApp("solo draft")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        panel = _hint_panel(bar)

        assert panel.has_class("hidden")
        await pilot.press("escape")
        await pilot.press("g")
        await pilot.pause()

        assert not panel.has_class("hidden")
        assert panel.border_title == " g "
        assert panel.border_subtitle == "\\[esc] cancel"
        plain = panel.render().plain
        assert "gf   format prompt" in plain
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
    app = _GPrefixHintApp("solo draft", stash_exists=True)

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        panel = _hint_panel(bar)

        assert panel.has_class("hidden")
        await pilot.press("ctrl+g")
        await pilot.pause()

        assert not panel.has_class("hidden")
        assert panel.border_title == " ^G "
        assert panel.border_subtitle == "\\[esc] cancel"
        plain = panel.render().plain
        assert "^Gg / ^G^G   edit in editor" in plain
        assert "^Gf   format prompt" in plain
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
    app = _GPrefixHintApp("solo draft")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        panel = _hint_panel(bar)

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
    app = _GPrefixHintApp("solo draft")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        panel = _hint_panel(bar)

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
    app = _GPrefixHintApp("reusable draft")

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
    app = _GPrefixHintApp("first\n---\nsecond")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        panel = _hint_panel(bar)

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
    app = _GPrefixHintApp("first\n---\nsecond")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        panel = _hint_panel(bar)

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
    app = _GPrefixHintApp("solo draft")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        panel = _hint_panel(bar)

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
    app = _GPrefixHintApp("solo draft", stash_exists=True)

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        panel = _hint_panel(bar)

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
    app = _GPrefixHintApp("solo draft")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        panel = _hint_panel(bar)

        await pilot.press("escape", "g", "=")
        await pilot.pause()

        assert panel.has_class("hidden")
        assert bar._g_prefix_hints_visible is False


async def test_escape_hides_pending_g_prefix_hints() -> None:
    app = _GPrefixHintApp("solo draft")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        panel = _hint_panel(bar)

        await pilot.press("escape", "g")
        await pilot.pause()
        assert not panel.has_class("hidden")

        await pilot.press("escape")
        await pilot.pause()

        assert panel.has_class("hidden")
        assert bar._g_prefix_hints_visible is False


async def test_escape_cancels_insert_prefix_and_stays_insert_mode() -> None:
    app = _GPrefixHintApp("solo draft")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        panel = _hint_panel(bar)

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
    app = _GPrefixHintApp("solo draft", stash_exists=True)

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        panel = _hint_panel(bar)

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
    app = _GPrefixHintApp("solo draft", stash_exists=True)

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        panel = _hint_panel(bar)

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
    app = _GPrefixHintApp("plan note", mode="feedback", stash_exists=True)

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        panel = _hint_panel(bar)

        await pilot.press("escape", "g")
        await pilot.pause()

        assert not panel.has_class("hidden")
        assert "gf   format prompt" in panel.render().plain
        assert bar._g_prefix_hints_visible is True


# --- vim ``g`` commands still resolve --------------------------------------


async def test_gg_still_jumps_to_buffer_start_after_hint_integration() -> None:
    app = _GPrefixHintApp("line0\nline1\nline2")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()
        await pilot.press("escape")
        text_area.cursor_location = (2, 0)

        await pilot.press("g", "g")
        await pilot.pause()

        assert text_area.cursor_location == (0, 0)
        assert _hint_panel(bar).has_class("hidden")


async def test_counted_gg_jumps_to_target_line_after_hint_integration() -> None:
    app = _GPrefixHintApp("line0\nline1\nline2\nline3")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()
        await pilot.press("escape")
        text_area.cursor_location = (0, 0)

        await pilot.press("3", "g", "g")
        await pilot.pause()

        assert text_area.cursor_location == (2, 0)
        assert _hint_panel(bar).has_class("hidden")


# --- dispatch routing ------------------------------------------------------


async def test_dispatch_g_prefix_key_routes_each_continuation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _GPrefixHintApp("solo draft")

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
        monkeypatch.setattr(bar, "request_save_as_xprompt", lambda: calls.append("x"))
        monkeypatch.setattr(
            bar,
            "convert_active_pane_to_local_xprompt",
            lambda **_: calls.append("X"),
        )
        monkeypatch.setattr(bar, "request_open_prompt_stash", lambda: calls.append("p"))

        for key in (
            "f",
            "enter",
            "j",
            "k",
            "J",
            "K",
            "-",
            "=",
            "s",
            "S",
            "x",
            "X",
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
            "enter",
            "focus+1",
            "focus-1",
            "move+1",
            "move-1",
            "-",
            "=",
            "s",
            "S",
            "x",
            "X",
            "ctrl+c",
            "x",
            "p",
            "S",
        ]


async def test_dispatch_g_prefix_key_can_target_insert_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _GPrefixHintApp("one\n---\ntwo")

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
            lambda *, target_mode="normal": calls.append(f"X:{target_mode}"),
        )

        assert bar.dispatch_g_prefix_key("j", target_mode="insert") is True
        assert bar.dispatch_g_prefix_key("K", target_mode="insert") is True
        assert bar.dispatch_g_prefix_key("X", target_mode="insert") is True

        assert calls == ["focus+1:insert", "move-1:insert", "X:insert"]
