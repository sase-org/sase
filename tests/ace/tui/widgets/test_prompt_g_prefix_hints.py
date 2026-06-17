"""Widget-level tests for the prompt ``g`` prefix hint panel."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static

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
    ) -> None:
        super().__init__()
        self._initial_value = initial_value
        self._mode = mode
        self._stash_exists = stash_exists
        self.stashed: list[PromptInputBar.Stashed] = []
        self.restore_requests: list[PromptInputBar.RestoreRequested] = []

    def compose(self) -> ComposeResult:
        yield PromptInputBar(
            initial_value=self._initial_value,
            mode=self._mode,
            id="prompt-input-bar",
        )

    def _has_stashed_prompts(self) -> bool:
        return self._stash_exists

    def on_prompt_input_bar_stashed(self, event: PromptInputBar.Stashed) -> None:
        self.stashed.append(event)

    def on_prompt_input_bar_restore_requested(
        self, event: PromptInputBar.RestoreRequested
    ) -> None:
        self.restore_requests.append(event)


def _entry_pairs(bar: PromptInputBar) -> list[tuple[str, str]]:
    return [(entry.key, entry.label) for entry in bar.g_prefix_hint_entries()]


def _hint_panel(bar: PromptInputBar) -> Static:
    return bar.query_one("#prompt-g-prefix-hints", Static)


# --- context-aware hint entries --------------------------------------------


async def test_single_pane_hint_entries_hide_multi_pane_and_stash_actions() -> None:
    app = _GPrefixHintApp("solo draft")

    async with app.run_test(size=(80, 24)):
        bar = app.query_one(PromptInputBar)

        # No multi-pane nav (single pane), no stash restore (empty stash).
        assert _entry_pairs(bar) == [
            ("-", "add pane"),
            ("=", "toggle frontmatter"),
            ("s", "stash this draft"),
        ]


async def test_single_pane_with_stash_includes_load_and_restore() -> None:
    app = _GPrefixHintApp("solo draft", stash_exists=True)

    async with app.run_test(size=(80, 24)):
        bar = app.query_one(PromptInputBar)

        assert _entry_pairs(bar) == [
            ("-", "add pane"),
            ("=", "toggle frontmatter"),
            ("s", "stash this draft"),
            ("p", "load stash…"),
            ("P", "restore stash…"),
        ]


async def test_multi_pane_hint_entries_include_nav_stash_and_restore() -> None:
    app = _GPrefixHintApp(
        "first\n---\nsecond",
        stash_exists=True,
    )

    async with app.run_test(size=(80, 24)):
        bar = app.query_one(PromptInputBar)

        assert _entry_pairs(bar) == [
            ("j", "focus next pane"),
            ("k", "focus prev pane"),
            ("J", "move pane down"),
            ("K", "move pane up"),
            ("-", "add pane"),
            ("=", "toggle frontmatter"),
            ("s", "stash this pane"),
            ("S", "stash all panes"),
            ("p", "load stash…"),
            ("P", "restore stash…"),
        ]


async def test_multi_pane_without_stash_hides_load_and_restore() -> None:
    app = _GPrefixHintApp("first\n---\nsecond")

    async with app.run_test(size=(80, 24)):
        bar = app.query_one(PromptInputBar)

        keys = [key for key, _ in _entry_pairs(bar)]
        assert "p" not in keys
        assert "P" not in keys
        # Multi-pane nav and stash-all stay available.
        assert keys == ["j", "k", "J", "K", "-", "=", "s", "S"]


async def test_feedback_bar_has_no_prompt_g_prefix_hints() -> None:
    app = _GPrefixHintApp("plan note", mode="feedback", stash_exists=True)

    async with app.run_test(size=(80, 24)):
        bar = app.query_one(PromptInputBar)

        assert _entry_pairs(bar) == []


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
        assert "g-   add pane" in plain
        assert "g=   toggle frontmatter" in plain
        assert "gs   stash this draft" in plain
        # Multi-pane and stash entries are absent for a single empty-stash pane.
        assert "gS" not in plain
        assert "gj" not in plain
        assert "gP" not in plain


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


async def test_panel_stays_hidden_when_no_entries_are_available() -> None:
    app = _GPrefixHintApp("plan note", mode="feedback", stash_exists=True)

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        panel = _hint_panel(bar)

        await pilot.press("escape", "g")
        await pilot.pause()

        assert panel.has_class("hidden")
        assert bar._g_prefix_hints_visible is False


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
        monkeypatch.setattr(bar, "add_bottom_pane", lambda: calls.append("-"))
        monkeypatch.setattr(bar, "toggle_frontmatter_panel", lambda: calls.append("="))
        monkeypatch.setattr(bar, "stash_active_pane", lambda: calls.append("s"))
        monkeypatch.setattr(bar, "stash_all_panes", lambda: calls.append("S"))
        monkeypatch.setattr(bar, "request_load_stash", lambda: calls.append("p"))
        monkeypatch.setattr(bar, "request_restore_stash", lambda: calls.append("P"))

        for key in ("j", "k", "J", "K", "-", "=", "s", "S", "p", "P"):
            assert bar.dispatch_g_prefix_key(key) is True
        # Unknown / vim-owned continuations fall through to vim.
        assert bar.dispatch_g_prefix_key("g") is False
        assert bar.dispatch_g_prefix_key("u") is False
        assert bar.dispatch_g_prefix_key("z") is False

        assert calls == [
            "focus+1",
            "focus-1",
            "move+1",
            "move-1",
            "-",
            "=",
            "s",
            "S",
            "p",
            "P",
        ]
