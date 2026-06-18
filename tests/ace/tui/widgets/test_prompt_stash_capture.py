"""Widget-level tests for prompt-stash capture (``gs`` / ``gS``).

Covers the capture deliverable of the prompt-stash feature: the bar's normal
-mode ``g`` prefix stashes the active pane (``gs``) or every non-empty pane
(``gS``), posting a presentation-only ``PromptInputBar.Stashed`` message that
carries the pane text(s) + shared frontmatter for the app to persist.  Capture
removes the stashed pane(s), keeps the bar mounted while others remain, and
asks the app to dismiss it once empty.  Empty panes and non-prompt bars are
no-ops.
"""

from __future__ import annotations

from textual.app import App, ComposeResult

from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar


class _CaptureApp(App[None]):
    """Hosts a prompt bar and records its Stashed messages."""

    ENABLE_COMMAND_PALETTE = False

    def __init__(self, initial_value: str = "", mode: str = "prompt") -> None:
        super().__init__()
        self._initial_value = initial_value
        self._mode = mode
        self.stashed: list[PromptInputBar.Stashed] = []

    def compose(self) -> ComposeResult:
        yield PromptInputBar(
            initial_value=self._initial_value,
            mode=self._mode,
            id="prompt-input-bar",
        )

    def on_prompt_input_bar_stashed(self, event: PromptInputBar.Stashed) -> None:
        self.stashed.append(event)


# --- stash current (gs) ----------------------------------------------------


async def test_gs_stashes_single_pane_and_asks_to_dismiss() -> None:
    app = _CaptureApp("solo draft")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        await pilot.press("escape")  # insert -> normal
        await pilot.press("g", "s")
        await pilot.pause()

        assert len(app.stashed) == 1
        event = app.stashed[0]
        assert event.source == "current"
        assert event.dismiss_bar is True  # last pane -> empty -> dismiss
        assert [p.text for p in event.panes] == ["solo draft"]
        assert event.panes[0].pane_index == 0
        assert event.panes[0].frontmatter == ""


async def test_ctrl_gs_stashes_single_pane_from_insert() -> None:
    app = _CaptureApp("solo draft")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        await pilot.press("ctrl+g", "s")
        await pilot.pause()

        assert len(app.stashed) == 1
        event = app.stashed[0]
        assert event.source == "current"
        assert event.dismiss_bar is True
        assert [p.text for p in event.panes] == ["solo draft"]


async def test_gs_in_multi_pane_keeps_bar_and_removes_only_active() -> None:
    app = _CaptureApp("first\n---\nsecond\n---\nthird")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        assert bar._stack.selected_index == 2  # bottom pane active

        await pilot.press("escape")
        await pilot.press("g", "s")  # stash "third"
        await pilot.pause()
        await pilot.pause()

        assert len(app.stashed) == 1
        event = app.stashed[0]
        assert event.source == "current"
        assert event.dismiss_bar is False  # other panes remain
        assert [p.text for p in event.panes] == ["third"]
        assert event.panes[0].pane_index == 2
        # The bar stays mounted with the remaining panes.
        assert bar.all_prompt_texts() == ["first", "second"]


async def test_gs_on_empty_pane_is_noop_with_empty_message() -> None:
    app = _CaptureApp("")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        await pilot.press("escape")
        await pilot.press("g", "s")
        await pilot.pause()

        assert len(app.stashed) == 1
        event = app.stashed[0]
        assert event.panes == []  # nothing captured; app will toast a no-op
        assert event.dismiss_bar is False


# --- stash all (gS) --------------------------------------------------------


async def test_gS_stashes_all_non_empty_panes_in_order() -> None:
    app = _CaptureApp("alpha\n---\nbeta\n---\ngamma")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        await pilot.press("escape")
        await pilot.press("g", "S")
        await pilot.pause()

        assert len(app.stashed) == 1
        event = app.stashed[0]
        assert event.source == "all"
        assert event.dismiss_bar is True
        assert [p.text for p in event.panes] == ["alpha", "beta", "gamma"]
        assert [p.pane_index for p in event.panes] == [0, 1, 2]


async def test_ctrl_gS_stashes_all_non_empty_panes_from_insert() -> None:
    app = _CaptureApp("alpha\n---\nbeta\n---\ngamma")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        await pilot.press("ctrl+g", "S")
        await pilot.pause()

        assert len(app.stashed) == 1
        event = app.stashed[0]
        assert event.source == "all"
        assert event.dismiss_bar is True
        assert [p.text for p in event.panes] == ["alpha", "beta", "gamma"]


async def test_gS_preserves_shared_frontmatter() -> None:
    app = _CaptureApp("---\nmodel: claude\n---\nfirst\n---\nsecond")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        # Multi-pane parsing lifts the frontmatter onto the stack.
        assert bar._stack.frontmatter == "---\nmodel: claude\n---"

        await pilot.press("escape")
        await pilot.press("g", "S")
        await pilot.pause()

        event = app.stashed[0]
        assert [p.text for p in event.panes] == ["first", "second"]
        assert all(p.frontmatter == "---\nmodel: claude\n---" for p in event.panes)


async def test_gS_all_empty_is_noop() -> None:
    app = _CaptureApp("")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        await pilot.press("escape")
        await pilot.press("g", "S")
        await pilot.pause()

        assert len(app.stashed) == 1
        assert app.stashed[0].panes == []
        assert app.stashed[0].dismiss_bar is False


# --- guards ----------------------------------------------------------------


async def test_stash_is_noop_in_feedback_mode() -> None:
    app = _CaptureApp("plan note", mode="feedback")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        await pilot.press("escape")
        await pilot.press("g", "s")
        await pilot.press("g", "S")
        await pilot.pause()

        # Feedback bars are not stashable: no message posted, text intact.
        assert app.stashed == []
        assert bar.all_prompt_texts() == ["plan note"]


async def test_single_pane_comma_still_reverses_char_search() -> None:
    """Stash must not steal vim's reverse char-search ``,`` after an f/t."""
    app = _CaptureApp("a) b) c) d")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()
        await pilot.press("escape")
        text_area.cursor_location = (0, 0)

        await pilot.press("f", ")")
        assert text_area.cursor_location == (0, 1)
        await pilot.press("semicolon")
        assert text_area.cursor_location == (0, 4)
        await pilot.press("comma")  # reverse char search, NOT a stash leader
        assert text_area.cursor_location == (0, 1)
        assert app.stashed == []
