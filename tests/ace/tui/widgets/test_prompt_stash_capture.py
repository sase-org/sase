"""Widget-level tests for prompt-stash capture (``<ctrl+s>`` / ``gs``).

Covers the capture deliverable of the prompt-stash feature: the bar's normal
-mode ``g`` prefix stashes every non-empty pane (``gs``), while ``<ctrl+s>``
stashes the active pane.  Both post a presentation-only
``PromptInputBar.Stashed`` message that carries the pane text(s) + shared
frontmatter for the app to persist.  Capture removes the stashed pane(s), keeps
the bar mounted while others remain, and asks the app to dismiss it once empty.
Empty panes and non-prompt bars are no-ops.
"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Input, TextArea

from sase.ace.tui.modals.xprompt_item_modal import XPromptItemModal
from sase.ace.tui.widgets.frontmatter_panel import FrontmatterPanel
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.xprompt.prompt_frontmatter import PromptFrontmatter


_LOCAL_XPROMPT_NAME = "_stash_helper"
_LOCAL_XPROMPT_CONTENT = "Use saved helper rules"


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


async def _add_local_xprompt_from_panel(
    pilot: object,
    app: _CaptureApp,
    *,
    name: str = _LOCAL_XPROMPT_NAME,
    content: str = _LOCAL_XPROMPT_CONTENT,
) -> None:
    """Author one local ``xprompts:`` helper through the real panel sub-editor."""
    bar = app.query_one(PromptInputBar)
    bar.focus_frontmatter_panel()
    await pilot.pause()  # type: ignore[attr-defined]
    await pilot.pause()  # type: ignore[attr-defined]

    panel = app.query_one(FrontmatterPanel)
    panel.begin_add("xprompts")
    await pilot.pause()  # type: ignore[attr-defined]
    await pilot.pause()  # type: ignore[attr-defined]

    modal = app.screen
    assert isinstance(modal, XPromptItemModal)
    modal.query_one("#xprompt-item-name", Input).value = name
    modal.query_one("#xprompt-item-content", TextArea).text = content
    await pilot.pause()  # type: ignore[attr-defined]
    modal.action_save()
    await pilot.pause()  # type: ignore[attr-defined]
    await pilot.pause()  # type: ignore[attr-defined]


def _assert_frontmatter_contains_local_xprompt(frontmatter: str) -> None:
    """Assert the stashed frontmatter has canonical delimiters and helper data."""
    assert frontmatter.startswith("---\n")
    assert frontmatter.endswith("---")
    assert "xprompts:\n" in frontmatter
    assert f"  {_LOCAL_XPROMPT_NAME}: {_LOCAL_XPROMPT_CONTENT}\n" in frontmatter
    model = PromptFrontmatter.parse(frontmatter)
    assert model.xprompts[_LOCAL_XPROMPT_NAME].content == _LOCAL_XPROMPT_CONTENT


# --- stash current (Ctrl+S) ------------------------------------------------


async def test_ctrl_s_stashes_single_pane_and_asks_to_dismiss() -> None:
    app = _CaptureApp("solo draft")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        await pilot.press("escape")  # insert -> normal
        await pilot.press("ctrl+s")
        await pilot.pause()

        assert len(app.stashed) == 1
        event = app.stashed[0]
        assert event.source == "current"
        assert event.dismiss_bar is True  # last pane -> empty -> dismiss
        assert [p.text for p in event.panes] == ["solo draft"]
        assert event.panes[0].pane_index == 0
        assert event.panes[0].frontmatter == ""


async def test_ctrl_s_stashes_single_pane_from_insert() -> None:
    app = _CaptureApp("solo draft")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        await pilot.press("ctrl+s")
        await pilot.pause()

        assert len(app.stashed) == 1
        event = app.stashed[0]
        assert event.source == "current"
        assert event.dismiss_bar is True
        assert [p.text for p in event.panes] == ["solo draft"]


async def test_ctrl_s_in_multi_pane_keeps_bar_and_removes_only_active() -> None:
    app = _CaptureApp("first\n---\nsecond\n---\nthird")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        assert bar._stack.selected_index == 2  # bottom pane active

        await pilot.press("escape")
        await pilot.press("ctrl+s")  # stash "third"
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


async def test_ctrl_s_on_empty_pane_is_noop_with_empty_message() -> None:
    app = _CaptureApp("")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        await pilot.press("escape")
        await pilot.press("ctrl+s")
        await pilot.pause()

        assert len(app.stashed) == 1
        event = app.stashed[0]
        assert event.panes == []  # nothing captured; app will toast a no-op
        assert event.dismiss_bar is False


# --- stash all (gs) --------------------------------------------------------


async def test_gs_stashes_all_non_empty_panes_in_order() -> None:
    app = _CaptureApp("alpha\n---\nbeta\n---\ngamma")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        await pilot.press("escape")
        await pilot.press("g", "s")
        await pilot.pause()

        assert len(app.stashed) == 1
        event = app.stashed[0]
        assert event.source == "all"
        assert event.dismiss_bar is True
        assert [p.text for p in event.panes] == ["alpha", "beta", "gamma"]
        assert [p.pane_index for p in event.panes] == [0, 1, 2]


async def test_ctrl_gs_stashes_all_non_empty_panes_from_insert() -> None:
    app = _CaptureApp("alpha\n---\nbeta\n---\ngamma")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        await pilot.press("ctrl+g", "s")
        await pilot.pause()

        assert len(app.stashed) == 1
        event = app.stashed[0]
        assert event.source == "all"
        assert event.dismiss_bar is True
        assert [p.text for p in event.panes] == ["alpha", "beta", "gamma"]


async def test_gs_preserves_shared_frontmatter() -> None:
    app = _CaptureApp("---\nmodel: claude\n---\nfirst\n---\nsecond")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        # Multi-pane parsing lifts the frontmatter onto the stack.
        assert bar._stack.frontmatter == "---\nmodel: claude\n---"

        await pilot.press("escape")
        await pilot.press("g", "s")
        await pilot.pause()

        event = app.stashed[0]
        assert [p.text for p in event.panes] == ["first", "second"]
        assert all(p.frontmatter == "---\nmodel: claude\n---" for p in event.panes)


async def test_gs_preserves_panel_authored_xprompt_properties() -> None:
    app = _CaptureApp("alpha\n---\nbeta")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        await _add_local_xprompt_from_panel(pilot, app)

        await pilot.press("escape")  # insert -> normal after panel save
        await pilot.press("g", "s")
        await pilot.pause()

        event = app.stashed[0]
        assert event.source == "all"
        assert [p.text for p in event.panes] == ["alpha", "beta"]
        assert all(p.frontmatter == event.panes[0].frontmatter for p in event.panes)
        for pane in event.panes:
            _assert_frontmatter_contains_local_xprompt(pane.frontmatter)


async def test_ctrl_gs_preserves_panel_authored_xprompts_from_insert() -> None:
    app = _CaptureApp("alpha\n---\nbeta")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        await _add_local_xprompt_from_panel(pilot, app)

        await pilot.press("ctrl+g", "s")
        await pilot.pause()

        event = app.stashed[0]
        assert event.source == "all"
        assert [p.text for p in event.panes] == ["alpha", "beta"]
        for pane in event.panes:
            _assert_frontmatter_contains_local_xprompt(pane.frontmatter)


async def test_gs_all_empty_is_noop() -> None:
    app = _CaptureApp("")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        await pilot.press("escape")
        await pilot.press("g", "s")
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
        await pilot.press("ctrl+s")
        await pilot.press("g", "s")
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
