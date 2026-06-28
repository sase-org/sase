"""Prompt input bar stash-then-load tests."""

from __future__ import annotations

from textual.app import App, ComposeResult

from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar


class _RecordingPromptBarApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def __init__(self, initial_value: str) -> None:
        super().__init__()
        self._initial_value = initial_value
        self.stashed: list[PromptInputBar.Stashed] = []

    def compose(self) -> ComposeResult:
        yield PromptInputBar(
            initial_value=self._initial_value,
            id="prompt-input-bar",
        )

    def on_prompt_input_bar_stashed(self, event: PromptInputBar.Stashed) -> None:
        self.stashed.append(event)


async def test_stash_all_and_load_xprompt_markdown_stashes_preload_bundle(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.widgets.frontmatter_panel.frontmatter_field_schema",
        lambda: [],
    )
    app = _RecordingPromptBarApp("alpha\n---\nbeta")
    markdown = "---\ndescription: loaded\n---\nloaded one\n---\nloaded two"

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        bar._stack.frontmatter = "---\ndescription: draft\n---"
        bar.stash_all_and_load_xprompt_markdown(markdown)
        await pilot.pause()
        await pilot.pause()

        assert len(app.stashed) == 1
        event = app.stashed[0]
        assert event.source == "all"
        assert event.dismiss_bar is False
        assert [pane.text for pane in event.panes] == ["alpha", "beta"]
        assert {pane.frontmatter for pane in event.panes} == {
            "---\ndescription: draft\n---"
        }
        assert bar.all_prompt_texts() == ["loaded one", "loaded two"]
        assert bar._stack.frontmatter == "---\ndescription: loaded\n---"


async def test_stash_all_and_load_xprompt_markdown_empty_bar_posts_nothing(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.widgets.frontmatter_panel.frontmatter_field_schema",
        lambda: [],
    )
    app = _RecordingPromptBarApp("")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        bar.stash_all_and_load_xprompt_markdown("loaded")
        await pilot.pause()

        assert app.stashed == []
        assert bar.active_text() == "loaded"
