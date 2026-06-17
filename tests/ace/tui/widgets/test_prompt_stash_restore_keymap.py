"""Widget-level tests for prompt-stash restore/load (``gP`` / ``gp``).

Covers the bar side of restore/load: the normal-mode ``g`` prefix posts a
presentation-only ``PromptInputBar.RestoreRequested`` carrying the bar mode (so
the app can guard) and a ``destructive`` flag — ``gP`` requests a destructive
pop-and-load while ``gp`` requests a non-destructive copy.  ``restore_stashed_entries``
appends restored drafts as new panes — dropping a lone empty drafting pane,
preserving existing panes, and adopting frontmatter when the bar has none.
Non-prompt bars never restore.
"""

from __future__ import annotations

from textual.app import App, ComposeResult

from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar


class _RestoreApp(App[None]):
    """Hosts a prompt bar and records its RestoreRequested messages."""

    ENABLE_COMMAND_PALETTE = False

    def __init__(self, initial_value: str = "", mode: str = "prompt") -> None:
        super().__init__()
        self._initial_value = initial_value
        self._mode = mode
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


# --- gP posts the request --------------------------------------------------


async def test_gP_posts_destructive_restore_request_in_prompt_mode() -> None:
    app = _RestoreApp("draft")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.press("escape")  # insert -> normal
        await pilot.press("g", "P")
        await pilot.pause()

        assert len(app.restore_requests) == 1
        assert app.restore_requests[0].mode == "prompt"
        assert app.restore_requests[0].destructive is True


async def test_gp_posts_non_destructive_load_request_in_prompt_mode() -> None:
    app = _RestoreApp("draft")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.press("escape")  # insert -> normal
        await pilot.press("g", "p")
        await pilot.pause()

        assert len(app.restore_requests) == 1
        assert app.restore_requests[0].mode == "prompt"
        assert app.restore_requests[0].destructive is False


async def test_gP_forwards_feedback_mode() -> None:
    app = _RestoreApp("plan note", mode="feedback")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.press("escape")
        await pilot.press("g", "P")
        await pilot.pause()

        # The bar still signals intent in feedback mode; the app toasts a no-op.
        assert len(app.restore_requests) == 1
        assert app.restore_requests[0].mode == "feedback"
        assert app.restore_requests[0].destructive is True


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


async def test_restore_is_noop_in_feedback_mode() -> None:
    app = _RestoreApp("plan note", mode="feedback")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)

        bar.restore_stashed_entries([("nope", "")])
        await pilot.pause()

        assert bar.all_prompt_texts() == ["plan note"]
