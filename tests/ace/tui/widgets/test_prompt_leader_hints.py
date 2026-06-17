"""Widget-level tests for prompt comma-leader hints."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static

from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar


class _LeaderHintApp(App[None]):
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
    return [(entry.key, entry.label) for entry in bar.leader_hint_entries()]


def _leader_panel(bar: PromptInputBar) -> Static:
    return bar.query_one("#prompt-leader-hints", Static)


async def test_single_pane_hint_entries_hide_noop_actions() -> None:
    app = _LeaderHintApp("solo draft")

    async with app.run_test(size=(80, 24)):
        bar = app.query_one(PromptInputBar)

        assert _entry_pairs(bar) == [
            ("s", "stash this draft"),
            ("f", "toggle frontmatter"),
        ]


async def test_multi_pane_hint_entries_include_available_stash_restore() -> None:
    app = _LeaderHintApp(
        "first\n---\nsecond",
        stash_exists=True,
    )

    async with app.run_test(size=(80, 24)):
        bar = app.query_one(PromptInputBar)

        assert _entry_pairs(bar) == [
            ("s", "stash this pane"),
            ("S", "stash all panes"),
            ("P", "restore stash…"),
            ("f", "toggle frontmatter"),
        ]


async def test_feedback_bar_has_no_prompt_leader_hints() -> None:
    app = _LeaderHintApp("plan note", mode="feedback", stash_exists=True)

    async with app.run_test(size=(80, 24)):
        bar = app.query_one(PromptInputBar)

        assert _entry_pairs(bar) == []


async def test_comma_in_normal_mode_shows_leader_hints() -> None:
    app = _LeaderHintApp("solo draft")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        panel = _leader_panel(bar)

        assert panel.has_class("hidden")
        await pilot.press("escape")
        await pilot.press("comma")
        await pilot.pause()

        assert not panel.has_class("hidden")
        assert panel.border_title == " leader "
        assert panel.border_subtitle == "\\[esc] cancel"
        plain = panel.render().plain
        assert ",s   stash this draft" in plain
        assert ",f   toggle frontmatter" in plain
        assert ",S" not in plain
        assert ",P" not in plain


async def test_second_leader_key_hides_hints_after_dispatch() -> None:
    app = _LeaderHintApp("solo draft")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        panel = _leader_panel(bar)

        await pilot.press("escape", "comma", "f")
        await pilot.pause()

        assert panel.has_class("hidden")
        assert bar._leader_hints_visible is False


async def test_escape_hides_pending_leader_hints() -> None:
    app = _LeaderHintApp("solo draft")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        panel = _leader_panel(bar)

        await pilot.press("escape", "comma")
        await pilot.pause()
        assert not panel.has_class("hidden")

        await pilot.press("escape")
        await pilot.pause()

        assert panel.has_class("hidden")
        assert bar._leader_hints_visible is False


async def test_unknown_leader_key_hides_hints() -> None:
    app = _LeaderHintApp("solo draft")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        panel = _leader_panel(bar)

        await pilot.press("escape", "comma")
        await pilot.pause()
        assert not panel.has_class("hidden")

        await pilot.press("x")
        await pilot.pause()

        assert panel.has_class("hidden")
        assert app.stashed == []
        assert app.restore_requests == []


async def test_panel_stays_hidden_when_no_entries_are_available() -> None:
    app = _LeaderHintApp("plan note", mode="feedback", stash_exists=True)

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        panel = _leader_panel(bar)

        await pilot.press("escape", "comma")
        await pilot.pause()

        assert panel.has_class("hidden")
        assert bar._leader_hints_visible is False


async def test_dispatch_leader_key_routes_existing_chords(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _LeaderHintApp("solo draft")

    async with app.run_test(size=(80, 24)):
        bar = app.query_one(PromptInputBar)
        calls: list[str] = []
        monkeypatch.setattr(bar, "stash_active_pane", lambda: calls.append("s"))
        monkeypatch.setattr(bar, "stash_all_panes", lambda: calls.append("S"))
        monkeypatch.setattr(bar, "request_restore_stash", lambda: calls.append("P"))
        monkeypatch.setattr(bar, "focus_frontmatter_panel", lambda: calls.append("f"))

        assert bar.dispatch_leader_key("s") is True
        assert bar.dispatch_leader_key("S") is True
        assert bar.dispatch_leader_key("P") is True
        assert bar.dispatch_leader_key("f") is True
        assert bar.dispatch_leader_key("x") is False
        assert calls == ["s", "S", "P", "f"]
