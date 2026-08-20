"""Widget-level tests for prompt-stash panel opening.

Covers the bar side of restore: ``Ctrl+G p`` posts a presentation-only
``PromptInputBar.RestoreRequested`` carrying the bar mode (so the app can
guard), empty ``Ctrl+S`` opens the stash panel, while bare normal-mode ``gp``
no longer opens it. Non-empty ``Ctrl+S`` still stashes the active pane.
``restore_stashed_entries`` appends restored drafts as new panes — dropping a
lone empty drafting pane, preserving existing panes, and adopting frontmatter
when the bar has none. Non-prompt bars never restore.
"""

from __future__ import annotations

from textual.app import App, ComposeResult

from sase.ace.tui.prompt_stash_entries import RestoredStashPane
from sase.ace.tui.widgets.frontmatter_panel import FrontmatterPanel
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar


class _RestoreApp(App[None]):
    """Hosts a prompt bar and records stash/restore messages."""

    ENABLE_COMMAND_PALETTE = False

    def __init__(self, initial_value: str = "", mode: str = "prompt") -> None:
        super().__init__()
        self._initial_value = initial_value
        self._mode = mode
        self.stash_events: list[PromptInputBar.Stashed] = []
        self.restore_requests: list[PromptInputBar.RestoreRequested] = []

    def compose(self) -> ComposeResult:
        yield PromptInputBar(
            initial_value=self._initial_value,
            mode=self._mode,
            id="prompt-input-bar",
        )

    def on_prompt_input_bar_restore_requested(
        self, event: PromptInputBar.RestoreRequested
    ) -> None:
        self.restore_requests.append(event)

    def on_prompt_input_bar_stashed(self, event: PromptInputBar.Stashed) -> None:
        self.stash_events.append(event)


# --- Ctrl+G p posts the request -------------------------------------------


async def test_ctrl_gp_posts_restore_request_from_insert() -> None:
    app = _RestoreApp("draft")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.press("ctrl+g", "p")
        await pilot.pause()

        assert len(app.restore_requests) == 1
        assert app.restore_requests[0].mode == "prompt"


async def test_ctrl_gp_posts_restore_request_from_normal() -> None:
    app = _RestoreApp("draft")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.press("escape")  # insert -> normal
        await pilot.press("ctrl+g", "p")
        await pilot.pause()

        assert len(app.restore_requests) == 1
        assert app.restore_requests[0].mode == "prompt"


async def test_bare_gp_posts_no_restore_request() -> None:
    app = _RestoreApp("draft")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.press("escape")  # insert -> normal
        await pilot.press("g", "p")
        await pilot.pause()

        assert app.restore_requests == []


async def test_ctrl_gp_forwards_feedback_mode() -> None:
    app = _RestoreApp("plan note", mode="feedback")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.press("ctrl+g", "p")
        await pilot.pause()

        # The bar still signals intent in feedback mode; the app toasts a no-op.
        assert len(app.restore_requests) == 1
        assert app.restore_requests[0].mode == "feedback"


# --- empty Ctrl+S opens the panel ------------------------------------------


async def test_empty_ctrl_s_posts_restore_request() -> None:
    app = _RestoreApp("")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()

        assert app.stash_events == []
        assert len(app.restore_requests) == 1
        assert app.restore_requests[0].mode == "prompt"


async def test_whitespace_ctrl_s_posts_restore_request() -> None:
    app = _RestoreApp("   ")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()

        assert app.stash_events == []
        assert len(app.restore_requests) == 1
        assert app.restore_requests[0].mode == "prompt"


async def test_non_empty_ctrl_s_stashes_without_restore_request() -> None:
    app = _RestoreApp("draft")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()

        assert app.restore_requests == []
        assert len(app.stash_events) == 1
        event = app.stash_events[0]
        assert event.source == "current"
        assert [pane.text for pane in event.panes] == ["draft"]


async def test_empty_ctrl_s_is_noop_in_feedback_mode() -> None:
    app = _RestoreApp("", mode="feedback")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()

        assert app.restore_requests == []
        assert app.stash_events == []


# --- restore_stashed_entries loads panes -----------------------------------


async def test_restore_into_empty_bar_drops_blank_lead_pane() -> None:
    app = _RestoreApp("")
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)

        bar.restore_stashed_entries([("alpha", ""), ("beta", "")])
        await pilot.pause()

        assert bar.all_prompt_texts() == ["alpha", "beta"]


async def test_restore_appends_to_existing_panes() -> None:
    app = _RestoreApp("keep me")
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)

        bar.restore_stashed_entries([("restored", "")])
        await pilot.pause()

        assert bar.all_prompt_texts() == ["keep me", "restored"]


async def test_restore_adopts_frontmatter_when_bar_has_none() -> None:
    app = _RestoreApp("")
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)

        bar.restore_stashed_entries(
            [("alpha", "---\nmodel: claude\n---"), ("beta", "---\nmodel: other\n---")]
        )
        await pilot.pause()

        # First restored frontmatter wins; bodies become panes.
        assert bar._stack.frontmatter == "---\nmodel: claude\n---"
        assert bar.all_prompt_texts() == ["alpha", "beta"]


async def test_restore_adopted_xprompts_sync_to_frontmatter_panel() -> None:
    app = _RestoreApp("")
    frontmatter = "---\nxprompts:\n  _stash_helper: Use restored helper\n---"
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)

        bar.restore_stashed_entries([("alpha", frontmatter)])
        await pilot.pause()
        await pilot.pause()

        assert bar._stack.frontmatter == frontmatter
        assert bar._stack.frontmatter_model.xprompts["_stash_helper"].content == (
            "Use restored helper"
        )
        panel = app.query_one("#frontmatter-panel", FrontmatterPanel)
        assert not panel.has_class("hidden")
        assert panel.model.xprompts["_stash_helper"].content == "Use restored helper"
        assert bar.all_prompt_texts() == ["alpha"]


async def test_restore_multiline_cursor_into_empty_bar() -> None:
    app = _RestoreApp("")
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)

        bar.restore_stashed_entries(
            [
                RestoredStashPane(
                    text="hello\nworld",
                    cursor=(1, 2),
                    is_focus_target=True,
                )
            ]
        )
        await pilot.pause()
        await pilot.pause()

        assert bar.all_prompt_texts() == ["hello\nworld"]
        assert bar._stack.selected_index == 0
        text_area = bar.active_text_area()
        assert text_area.cursor_location == (1, 2)
        assert text_area._vim_mode == "insert"


async def test_restore_appends_into_non_empty_bar_and_focuses_target() -> None:
    app = _RestoreApp("keep me")
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)

        bar.restore_stashed_entries(
            [
                RestoredStashPane(
                    text="restored",
                    cursor=(0, 3),
                    is_focus_target=True,
                )
            ]
        )
        await pilot.pause()
        await pilot.pause()

        assert bar.all_prompt_texts() == ["keep me", "restored"]
        assert bar._stack.selected_index == 1
        assert bar.active_text_area().cursor_location == (0, 3)


async def test_restore_bundle_focuses_middle_pane() -> None:
    app = _RestoreApp("")
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)

        bar.restore_stashed_entries(
            [
                RestoredStashPane(text="alpha"),
                RestoredStashPane(
                    text="beta\nline",
                    cursor=(1, 2),
                    is_focus_target=True,
                ),
                RestoredStashPane(text="gamma"),
            ]
        )
        await pilot.pause()
        await pilot.pause()

        assert bar.all_prompt_texts() == ["alpha", "beta\nline", "gamma"]
        assert bar._stack.selected_index == 1
        assert bar.active_text() == "beta\nline"
        assert bar.active_text_area().cursor_location == (1, 2)
        assert bar.active_text_area()._vim_mode == "insert"


async def test_restore_clamps_out_of_range_cursor() -> None:
    app = _RestoreApp("")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)

        bar.restore_stashed_entries(
            [
                RestoredStashPane(
                    text="hi",
                    cursor=(99, 99),
                    is_focus_target=True,
                )
            ]
        )
        await pilot.pause()
        await pilot.pause()

        assert bar.active_text_area().cursor_location == (0, 2)


async def test_restore_legacy_row_focuses_final_pane_at_end() -> None:
    app = _RestoreApp("keep")
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)

        bar.restore_stashed_entries(
            [RestoredStashPane(text="alpha"), RestoredStashPane(text="beta")]
        )
        await pilot.pause()
        await pilot.pause()

        assert bar.all_prompt_texts() == ["keep", "alpha", "beta"]
        assert bar._stack.selected_index == 2
        text_area = bar.active_text_area()
        assert text_area.cursor_location == (0, 4)
        assert text_area._vim_mode == "insert"


async def test_restore_is_noop_in_feedback_mode() -> None:
    app = _RestoreApp("plan note", mode="feedback")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)

        bar.restore_stashed_entries([("nope", "")])
        await pilot.pause()

        assert bar.all_prompt_texts() == ["plan note"]


# --- restart capture helper ------------------------------------------------


async def test_capture_stashable_panes_returns_multi_pane_draft() -> None:
    app = _RestoreApp("alpha\n---\nbeta")
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        bar._stack.frontmatter = "---\ndescription: draft\n---"

        panes = bar.capture_stashable_panes()

        assert [(pane.text, pane.frontmatter, pane.pane_index) for pane in panes] == [
            ("alpha", "---\ndescription: draft\n---", 0),
            ("beta", "---\ndescription: draft\n---", 1),
        ]
        assert bar.all_prompt_texts() == ["alpha", "beta"]


async def test_capture_stashable_panes_keeps_frontmatter_only_draft() -> None:
    app = _RestoreApp("")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        bar._stack.frontmatter = "---\ndescription: draft\n---"

        panes = bar.capture_stashable_panes()

        assert [(pane.text, pane.frontmatter, pane.pane_index) for pane in panes] == [
            ("", "---\ndescription: draft\n---", 0)
        ]


async def test_capture_stashable_panes_empty_prompt_returns_empty() -> None:
    app = _RestoreApp("   ")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)

        assert bar.capture_stashable_panes() == []


async def test_capture_stashable_panes_is_noop_in_feedback_mode() -> None:
    app = _RestoreApp("plan note", mode="feedback")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)

        assert bar.capture_stashable_panes() == []
