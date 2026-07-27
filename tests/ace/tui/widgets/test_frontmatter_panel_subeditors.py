"""Cell-strip editing for frontmatter structured items."""

from __future__ import annotations

from textual.app import App, ComposeResult

from sase.ace.tui.widgets.frontmatter_panel import FrontmatterPanel
from sase.ace.tui.widgets.frontmatter_panel import (
    _CONTENT_ROWS,
    _FEEDBACK_MAX_HEIGHT,
    _INLINE_ROWS,
    _PANEL_BORDER_ROWS,
    _PANEL_BOTTOM_MARGIN,
    _PANEL_MAX_HEIGHT,
    _RAW_MAX_HEIGHT,
    _ROWS_MAX_HEIGHT,
)
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from sase.ace.tui.widgets.vim_text_area import VimTextArea
from sase.xprompt.models import InputType


class _PromptBarApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def __init__(self, initial_value: str = "") -> None:
        super().__init__()
        self._initial_value = initial_value

    def compose(self) -> ComposeResult:
        yield PromptInputBar(initial_value=self._initial_value, id="prompt-input-bar")


async def _open_panel(pilot: object, app: _PromptBarApp) -> FrontmatterPanel:
    bar = app.query_one(PromptInputBar)
    bar.focus_frontmatter_panel()
    await pilot.pause()  # type: ignore[attr-defined]
    await pilot.pause()  # type: ignore[attr-defined]
    return app.query_one(FrontmatterPanel)


async def test_add_input_uses_ghost_cells_and_stays_in_panel() -> None:
    app = _PromptBarApp("---\ninput:\n  service: word\n---\nbody")
    async with app.run_test(size=(100, 32)) as pilot:
        panel = await _open_panel(pilot, app)
        await pilot.press("o")
        assert panel._cell_edit is not None and panel._cell_edit.ghost
        editor = panel.query_one("#frontmatter-inline", SingleLineVimTextArea)
        editor.text = "dry_run"
        panel._move_cell(1)
        editor.text = "bool"
        panel._move_cell(1)
        editor.text = "false"
        panel._commit_cell_edit()

        dry_run = panel.model.get_input("dry_run")
        assert dry_run is not None and dry_run.default is False
        assert panel._edit_mode == "rows"
        await pilot.pause()
        assert app.focused is panel


async def test_edit_input_type_uses_core_catalog() -> None:
    app = _PromptBarApp("---\ninput:\n  service: word\n---\nbody")
    async with app.run_test(size=(100, 32)) as pilot:
        panel = await _open_panel(pilot, app)
        await pilot.press("j", "e")
        assert panel._cell_edit is not None
        panel._move_cell(1)
        editor = panel.query_one("#frontmatter-inline", SingleLineVimTextArea)
        editor.text = "int"
        panel._commit_cell_edit()
        assert panel.model.get_input("service").type is InputType.INT  # type: ignore[union-attr]


async def test_reorder_and_undo_input_items() -> None:
    app = _PromptBarApp("---\ninput:\n  a: word\n  b: int\n---\nbody")
    async with app.run_test(size=(100, 32)) as pilot:
        panel = await _open_panel(pilot, app)
        await pilot.press("j", "J")
        assert [arg.name for arg in panel.model.inputs] == ["b", "a"]
        await pilot.press("u")
        assert [arg.name for arg in panel.model.inputs] == ["a", "b"]


async def test_xprompt_content_uses_bounded_multiline_editor() -> None:
    app = _PromptBarApp("")
    async with app.run_test(size=(100, 34)) as pilot:
        panel = await _open_panel(pilot, app)
        panel.begin_add("xprompts")
        editor = panel.query_one("#frontmatter-inline", SingleLineVimTextArea)
        editor.text = "rules"
        panel._move_cell(1)
        panel._move_cell(1)
        panel._move_cell(1)
        assert panel._edit_mode == "content"
        content = panel.query_one("#frontmatter-content", VimTextArea)
        content.text = "line one\nline two"
        panel._commit_cell_edit()
        assert panel.model.xprompts["_rules"].content == "line one\nline two"
        assert panel._edit_mode == "rows"


async def test_cancel_ghost_does_not_add_item() -> None:
    app = _PromptBarApp("")
    async with app.run_test(size=(100, 32)) as pilot:
        panel = await _open_panel(pilot, app)
        panel.begin_add("input")
        panel._cancel_active_edit()
        assert panel.model.inputs == []
        assert panel.model.is_empty


async def test_reserved_height_matches_every_visible_child_combination() -> None:
    """Every mode includes feedback and honors the CSS-backed height clamps."""
    app = _PromptBarApp("")
    async with app.run_test(size=(100, 34)) as pilot:
        panel = await _open_panel(pilot, app)

        for mode in ("rows", "edit", "picker", "cell", "content", "raw"):
            for content_lines in (2, _ROWS_MAX_HEIGHT + 5):
                for feedback_lines in (0, 3, _FEEDBACK_MAX_HEIGHT + 2):
                    panel._edit_mode = mode
                    panel._content_lines = content_lines
                    panel._raw_content_lines = _RAW_MAX_HEIGHT + 5
                    panel._feedback_lines = min(feedback_lines, _FEEDBACK_MAX_HEIGHT)
                    if mode == "raw":
                        children = _RAW_MAX_HEIGHT
                    else:
                        children = min(content_lines, _ROWS_MAX_HEIGHT)
                    if mode in {"edit", "picker", "cell"}:
                        children += _INLINE_ROWS
                    elif mode == "content":
                        children += _CONTENT_ROWS
                    children += min(feedback_lines, _FEEDBACK_MAX_HEIGHT)
                    expected = (
                        min(_PANEL_BORDER_ROWS + children, _PANEL_MAX_HEIGHT)
                        + _PANEL_BOTTOM_MARGIN
                    )
                    assert panel.reserved_height == expected


async def test_feedback_height_is_tracked_and_clamped() -> None:
    """Feedback visibility updates the cached reservation immediately."""
    app = _PromptBarApp("")
    async with app.run_test(size=(100, 34)) as pilot:
        panel = await _open_panel(pilot, app)

        panel._feedback = "Saved"
        panel._refresh()
        assert panel._feedback_lines == 1

        panel._feedback = "\n".join(str(index) for index in range(8))
        panel._refresh()
        assert panel._feedback_lines == _FEEDBACK_MAX_HEIGHT

        panel._feedback = "wrapped feedback " * 30
        panel._refresh()
        assert 1 < panel._feedback_lines <= _FEEDBACK_MAX_HEIGHT

        panel._feedback = ""
        panel._refresh()
        assert panel._feedback_lines == 0


async def test_raw_height_includes_editor_border() -> None:
    """The cached raw term measures the editor box, not only document lines."""
    app = _PromptBarApp("")
    async with app.run_test(size=(100, 34)) as pilot:
        panel = await _open_panel(pilot, app)
        panel._begin_raw()
        raw = panel.query_one("#frontmatter-raw", VimTextArea)
        raw.text = "one\ntwo\nthree"
        await pilot.pause()

        assert panel._raw_content_lines >= 5
