"""Widget-level tests for prompt-stash capture (``<ctrl+s>`` / ``gs``).

Covers the capture deliverable of the prompt-stash feature: the bar's normal
-mode ``g`` prefix stashes every non-empty pane (``gs``), while ``<ctrl+s>``
stashes a non-empty active pane.  Both post a presentation-only
``PromptInputBar.Stashed`` message that carries the pane text(s) + shared
frontmatter for the app to persist.  Capture removes the stashed pane(s), keeps
the bar mounted while others remain, and asks the app to dismiss it once empty.
An empty active pane opens the stash panel instead of posting ``Stashed``;
all-empty ``gs`` and non-prompt bars remain no-ops for capture.
"""

from __future__ import annotations

from textual.app import App, ComposeResult

from sase.ace.tui.widgets._prompt_input_bar_stack_models import (
    stash_cursor_for_stripped_text,
)
from sase.ace.tui.widgets.frontmatter_panel import FrontmatterPanel
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from sase.xprompt.prompt_frontmatter import PromptFrontmatter


_LOCAL_XPROMPT_NAME = "_stash_helper"
_LOCAL_XPROMPT_CONTENT = "Use saved helper rules"


class _CaptureApp(App[None]):
    """Hosts a prompt bar and records stash/restore messages."""

    ENABLE_COMMAND_PALETTE = False

    def __init__(self, initial_value: str = "", mode: str = "prompt") -> None:
        super().__init__()
        self._initial_value = initial_value
        self._mode = mode
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

    assert panel._cell_edit is not None and panel._cell_edit.ghost
    panel.query_one("#frontmatter-inline", SingleLineVimTextArea).text = name
    panel._cell_edit.values["content"] = content
    panel._commit_cell_edit()
    await pilot.pause()  # type: ignore[attr-defined]
    await pilot.press("q")  # commit symmetry keeps the panel active until done
    await pilot.pause()  # type: ignore[attr-defined]


def _assert_frontmatter_contains_local_xprompt(frontmatter: str) -> None:
    """Assert the stashed frontmatter has canonical delimiters and helper data."""
    assert frontmatter.startswith("---\n")
    assert frontmatter.endswith("---")
    assert "xprompts:\n" in frontmatter
    assert f"  {_LOCAL_XPROMPT_NAME}: {_LOCAL_XPROMPT_CONTENT}\n" in frontmatter
    model = PromptFrontmatter.parse(frontmatter)
    assert model.xprompts[_LOCAL_XPROMPT_NAME].content == _LOCAL_XPROMPT_CONTENT


# --- stripped-body cursor normalization ------------------------------------


def test_stash_cursor_keeps_multiline_offset_after_strip() -> None:
    text = "  hello\nworld  "
    assert stash_cursor_for_stripped_text(text, (0, 3)) == (0, 1)
    assert stash_cursor_for_stripped_text(text, (1, 0)) == (1, 0)


def test_stash_cursor_clamps_leading_and_trailing_whitespace() -> None:
    text = "  hello\nworld  "
    assert stash_cursor_for_stripped_text(text, (0, 0)) == (0, 0)
    assert stash_cursor_for_stripped_text(text, (0, 1)) == (0, 0)
    assert stash_cursor_for_stripped_text(text, (1, 7)) == (1, 5)
    assert stash_cursor_for_stripped_text("   ", (0, 2)) == (0, 0)


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


async def test_ctrl_s_on_empty_pane_requests_stash_panel() -> None:
    app = _CaptureApp("")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        await pilot.press("escape")
        await pilot.press("ctrl+s")
        await pilot.pause()

        assert app.stashed == []
        assert len(app.restore_requests) == 1
        assert app.restore_requests[0].mode == "prompt"


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


# --- update pinned (gS) ----------------------------------------------------


async def test_gS_captures_all_non_empty_panes_without_clearing_bar() -> None:
    app = _CaptureApp("alpha\n---\nbeta\n---\ngamma")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)

        await pilot.press("escape")
        await pilot.press("g", "S")
        await pilot.pause()

        assert len(app.update_requests) == 1
        event = app.update_requests[0]
        assert [p.text for p in event.panes] == ["alpha", "beta", "gamma"]
        assert [p.pane_index for p in event.panes] == [0, 1, 2]
        assert bar.all_prompt_texts() == ["alpha", "beta", "gamma"]
        assert app.stashed == []


async def test_ctrl_gS_captures_all_non_empty_panes_from_insert() -> None:
    app = _CaptureApp("alpha\n---\nbeta")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)

        await pilot.press("ctrl+g", "S")
        await pilot.pause()

        assert len(app.update_requests) == 1
        assert [p.text for p in app.update_requests[0].panes] == ["alpha", "beta"]
        assert bar.all_prompt_texts() == ["alpha", "beta"]


async def test_gS_preserves_shared_frontmatter() -> None:
    app = _CaptureApp("---\nmodel: claude\n---\nfirst\n---\nsecond")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        await pilot.press("escape")
        await pilot.press("g", "S")
        await pilot.pause()

        event = app.update_requests[0]
        assert [p.text for p in event.panes] == ["first", "second"]
        assert all(p.frontmatter == "---\nmodel: claude\n---" for p in event.panes)


async def test_gS_empty_prompt_posts_empty_update_request() -> None:
    app = _CaptureApp("")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        await pilot.press("escape")
        await pilot.press("g", "S")
        await pilot.pause()

        assert len(app.update_requests) == 1
        assert app.update_requests[0].panes == []
        assert app.stashed == []


# --- save as xprompt (gx / Ctrl+G x) --------------------------------------


async def test_gx_captures_all_non_empty_panes_without_clearing_bar() -> None:
    app = _CaptureApp("---\ndescription: reusable\n---\nalpha\n---\nbeta")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)

        await pilot.press("escape")
        await pilot.press("g", "x")
        await pilot.pause()

        assert len(app.save_xprompt_requests) == 1
        event = app.save_xprompt_requests[0]
        assert [p.text for p in event.panes] == ["alpha", "beta"]
        assert [p.pane_index for p in event.panes] == [0, 1]
        assert all(
            p.frontmatter == "---\ndescription: reusable\n---" for p in event.panes
        )
        assert bar.all_prompt_texts() == ["alpha", "beta"]
        assert app.stashed == []


async def test_gx_single_pane_marks_event_single_pane() -> None:
    app = _CaptureApp("solo draft")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        await pilot.press("escape")
        await pilot.press("g", "x")
        await pilot.pause()

        assert len(app.save_xprompt_requests) == 1
        event = app.save_xprompt_requests[0]
        assert event.single_pane is True
        assert [p.text for p in event.panes] == ["solo draft"]
        # The active pane is also captured as the snippet source.
        assert event.snippet_body == "solo draft"


async def test_gx_multi_pane_is_not_marked_single_pane() -> None:
    app = _CaptureApp("alpha\n---\nbeta")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        await pilot.press("escape")
        await pilot.press("g", "x")
        await pilot.pause()

        assert len(app.save_xprompt_requests) == 1
        assert app.save_xprompt_requests[0].single_pane is False


async def test_gx_multi_pane_captures_active_pane_as_snippet_body() -> None:
    app = _CaptureApp("first\n---\nsecond\n---\nthird")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        assert bar._stack.selected_index == 2  # bottom pane active

        await pilot.press("escape")
        await pilot.press("g", "k")  # focus the middle pane ("second")
        await pilot.pause()
        assert bar._stack.selected_index == 1

        await pilot.press("g", "x")
        await pilot.pause()

        assert len(app.save_xprompt_requests) == 1
        event = app.save_xprompt_requests[0]
        # The xprompt source still carries every non-empty pane in launch order.
        assert [p.text for p in event.panes] == ["first", "second", "third"]
        assert [p.pane_index for p in event.panes] == [0, 1, 2]
        assert event.single_pane is False
        # The snippet source is only the active (middle) pane.
        assert event.snippet_body == "second"


async def test_gx_multi_pane_with_one_empty_pane_is_not_single_pane() -> None:
    app = _CaptureApp("alpha")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        await pilot.press("escape")
        await pilot.press("g", "-")  # append an empty bottom pane (2-pane stack)
        await pilot.pause()
        await pilot.press("escape")  # the new pane lands in insert mode
        await pilot.press("g", "x")
        await pilot.pause()

        assert len(app.save_xprompt_requests) == 1
        event = app.save_xprompt_requests[0]
        # Only one pane has text, but the stack holds two panes -> not single.
        assert event.single_pane is False
        assert [p.text for p in event.panes] == ["alpha"]
        # The active pane is the new empty bottom pane, so the snippet source is
        # blank even though the xprompt body ("alpha") is not.
        assert event.snippet_body == ""


async def test_ctrl_gx_captures_frontmatter_only_draft() -> None:
    app = _CaptureApp("")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        bar._stack.set_frontmatter_model(
            PromptFrontmatter(description="frontmatter only")
        )

        await pilot.press("ctrl+g", "x")
        await pilot.pause()

        assert len(app.save_xprompt_requests) == 1
        event = app.save_xprompt_requests[0]
        assert len(event.panes) == 1
        assert event.panes[0].text == ""
        assert event.panes[0].frontmatter == "---\ndescription: frontmatter only\n---"
        # No active pane body -> blank snippet source even with frontmatter.
        assert event.snippet_body == ""


# --- guards ----------------------------------------------------------------


async def test_stash_is_noop_in_feedback_mode() -> None:
    app = _CaptureApp("plan note", mode="feedback")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        await pilot.press("escape")
        await pilot.press("ctrl+s")
        await pilot.press("g", "s")
        await pilot.press("g", "S")
        await pilot.press("g", "x")
        await pilot.pause()

        # Feedback bars are not stashable: no message posted, text intact.
        assert app.stashed == []
        assert app.update_requests == []
        assert app.save_xprompt_requests == []
        assert bar.all_prompt_texts() == ["plan note"]


async def test_ctrl_s_captures_multiline_cursor_on_active_pane() -> None:
    app = _CaptureApp("hello\nworld")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        bar.active_text_area().cursor_location = (1, 2)

        await pilot.press("ctrl+s")
        await pilot.pause()

        pane = app.stashed[0].panes[0]
        assert pane.active is True
        assert pane.cursor == (1, 2)
        assert pane.text == "hello\nworld"


async def test_gs_marks_non_final_active_pane() -> None:
    app = _CaptureApp("first\n---\nsecond line\n---\nthird")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        await pilot.press("escape")
        await pilot.press("g", "k")
        await pilot.pause()
        bar.active_text_area().cursor_location = (0, 3)

        await pilot.press("g", "s")
        await pilot.pause()

        panes = app.stashed[0].panes
        assert [pane.text for pane in panes] == ["first", "second line", "third"]
        assert [pane.active for pane in panes] == [False, True, False]
        assert panes[1].cursor == (0, 3)
        assert panes[0].cursor is None
        assert panes[2].cursor is None


async def test_capture_normalizes_cursor_against_stripped_body() -> None:
    app = _CaptureApp("  hello\nworld  ")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        bar.active_text_area().cursor_location = (0, 3)

        panes = bar.capture_stashable_panes()

        assert panes[0].text == "hello\nworld"
        assert panes[0].active is True
        assert panes[0].cursor == (0, 1)


async def test_capture_frontmatter_only_targets_empty_pane_at_origin() -> None:
    app = _CaptureApp("")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        bar._stack.frontmatter = "---\ndescription: draft\n---"

        panes = bar.capture_stashable_panes()

        assert len(panes) == 1
        assert panes[0].text == ""
        assert panes[0].active is True
        assert panes[0].cursor == (0, 0)


async def test_capture_omits_cursor_when_active_pane_is_empty() -> None:
    app = _CaptureApp("alpha")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        await pilot.press("escape")
        await pilot.press("g", "-")
        await pilot.pause()
        assert bar._stack.selected_index == 1
        assert not bar._stack.selected_item.text.strip()

        panes = bar.capture_stashable_panes()

        assert [pane.text for pane in panes] == ["alpha"]
        assert panes[0].active is False
        assert panes[0].cursor is None


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
