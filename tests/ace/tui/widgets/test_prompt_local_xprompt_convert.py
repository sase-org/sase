"""Prompt-pane conversion through the panel ghost-row flow."""

from __future__ import annotations

from textual.app import App, ComposeResult

from sase.ace.tui.widgets.frontmatter_panel import FrontmatterPanel
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea


class _ConvertApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def __init__(
        self, initial_value: str = "", *, initial_xprompt_markdown: str | None = None
    ) -> None:
        super().__init__()
        self._initial_value = initial_value
        self._markdown = initial_xprompt_markdown

    def compose(self) -> ComposeResult:
        yield PromptInputBar(
            initial_value=self._initial_value,
            initial_xprompt_markdown=self._markdown,
            id="prompt-input-bar",
        )


async def _open_ghost(
    app: _ConvertApp, pilot: object
) -> tuple[PromptInputBar, FrontmatterPanel]:
    bar = app.query_one(PromptInputBar)
    await pilot.press("escape", "g", "L")  # type: ignore[attr-defined]
    await pilot.pause()  # type: ignore[attr-defined]
    panel = app.query_one(FrontmatterPanel)
    assert panel._cell_edit is not None and panel._cell_edit.ghost
    return bar, panel


async def test_gL_prefills_body_and_commits_invocation() -> None:
    app = _ConvertApp("Do the thing")
    async with app.run_test(size=(100, 32)) as pilot:
        bar, panel = await _open_ghost(app, pilot)
        assert panel._cell_edit.values["content"] == "Do the thing"
        panel.query_one("#frontmatter-inline", SingleLineVimTextArea).text = "rules"
        panel._commit_cell_edit()
        assert panel.model.xprompts["_rules"].content == "Do the thing"
        assert bar.active_text_area().text == "#_rules"


async def test_gL_infers_jinja_inputs() -> None:
    app = _ConvertApp("Review {{ topic }} carefully")
    async with app.run_test(size=(100, 32)) as pilot:
        bar, panel = await _open_ghost(app, pilot)
        assert panel._cell_edit.values["inputs"] == "topic:text"
        panel.query_one("#frontmatter-inline", SingleLineVimTextArea).text = "review"
        panel._commit_cell_edit()
        assert "#_review(topic=" in bar.active_text_area().text


async def test_gL_converts_placeholders_to_inputs_and_invocation_slots() -> None:
    app = _ConvertApp("Review <the plan> for <target-file>")
    async with app.run_test(size=(100, 32)) as pilot:
        bar, panel = await _open_ghost(app, pilot)
        assert panel._cell_edit.values["content"] == (
            "Review {{ the_plan }} for {{ target_file }}"
        )
        assert panel._cell_edit.values["inputs"] == ("the_plan:text, target_file:text")
        panel.query_one("#frontmatter-inline", SingleLineVimTextArea).text = "review"
        panel._commit_cell_edit()
        saved = panel.model.xprompts["_review"]
        assert saved.content == "Review {{ the_plan }} for {{ target_file }}"
        assert [arg.name for arg in saved.inputs] == ["the_plan", "target_file"]
        assert bar.active_text_area().text == "#_review(the_plan=, target_file=)"


async def test_gL_preserves_existing_helpers() -> None:
    markdown = "---\nxprompts:\n  _existing: old helper\n---\nBrand new body"
    app = _ConvertApp(initial_xprompt_markdown=markdown)
    async with app.run_test(size=(100, 32)) as pilot:
        _bar, panel = await _open_ghost(app, pilot)
        panel.query_one("#frontmatter-inline", SingleLineVimTextArea).text = "new"
        panel._commit_cell_edit()
        assert list(panel.model.xprompts) == ["_existing", "_new"]


async def test_gL_cancel_leaves_body_unchanged() -> None:
    app = _ConvertApp("Do the thing")
    async with app.run_test(size=(100, 32)) as pilot:
        bar, panel = await _open_ghost(app, pilot)
        panel._cancel_active_edit()
        assert bar.active_text_area().text == "Do the thing"
        assert panel.model.xprompts == {}
