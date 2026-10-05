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
from sase.macro.models import InputType


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
        assert (
            panel._cell_edit is not None and panel._cell_edit.active_cell == "choices"
        )
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


async def test_macro_content_uses_bounded_multiline_editor() -> None:
    app = _PromptBarApp("")
    async with app.run_test(size=(100, 34)) as pilot:
        panel = await _open_panel(pilot, app)
        panel.begin_add("macros")
        editor = panel.query_one("#frontmatter-inline", SingleLineVimTextArea)
        editor.text = "rules"
        panel._move_cell(1)
        panel._move_cell(1)
        panel._move_cell(1)
        assert panel._edit_mode == "content"
        content = panel.query_one("#frontmatter-content", VimTextArea)
        content.text = "line one\nline two"
        panel._commit_cell_edit()
        assert panel.model.macros["_rules"].content == "line one\nline two"
        assert panel._edit_mode == "rows"


async def test_cancel_ghost_does_not_add_item() -> None:
    app = _PromptBarApp("")
    async with app.run_test(size=(100, 32)) as pilot:
        panel = await _open_panel(pilot, app)
        panel._begin_cell_edit("input", ghost=True)
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


async def _begin_input_edit(panel: FrontmatterPanel, name: str) -> None:
    panel._begin_cell_edit("input", item_name=name)
    assert panel._cell_edit is not None


def _sync_editor(panel: FrontmatterPanel) -> None:
    assert panel._cell_edit is not None
    editor = panel.query_one("#frontmatter-inline", SingleLineVimTextArea)
    editor.text = panel._cell_edit.values[panel._cell_edit.active_cell]


async def test_create_inline_enum_via_choices_cell() -> None:
    app = _PromptBarApp("---\ninput:\n  service: word\n---\nbody")
    async with app.run_test(size=(100, 32)) as pilot:
        panel = await _open_panel(pilot, app)
        panel._begin_cell_edit("input", ghost=True)
        assert panel._cell_edit is not None
        panel._cell_edit.values["name"] = "status"
        panel._cell_edit.values["type"] = "enum"
        panel._cell_edit.values["choices"] = "[wip, draft, ready]"
        panel._cell_edit.values["default"] = "wip"
        panel._cell_edit.values["description"] = "work state"
        editor = panel.query_one("#frontmatter-inline", SingleLineVimTextArea)
        editor.text = panel._cell_edit.values[panel._cell_edit.active_cell]
        panel._commit_cell_edit()
        arg = panel.model.get_input("status")
        assert arg is not None
        assert [c.value for c in arg.choices] == ["wip", "draft", "ready"]
        assert arg.default == "wip"


async def test_invalid_choices_show_feedback_and_do_not_commit() -> None:
    app = _PromptBarApp("---\ninput:\n  service: word\n---\nbody")
    async with app.run_test(size=(100, 32)) as pilot:
        panel = await _open_panel(pilot, app)
        for bad in ("", "[a, a]", "- yes"):
            panel._begin_cell_edit("input", ghost=True)
            assert panel._cell_edit is not None
            panel._cell_edit.values["name"] = "status"
            panel._cell_edit.values["type"] = "enum"
            panel._cell_edit.values["choices"] = bad
            _sync_editor(panel)
            panel._commit_cell_edit()
            assert panel.model.get_input("status") is None
            assert panel._feedback != "" and panel._feedback != "Saved"
            panel._cancel_active_edit()


async def test_non_member_default_and_choices_on_non_enum_rejected() -> None:
    app = _PromptBarApp("---\ninput:\n  service: word\n---\nbody")
    async with app.run_test(size=(100, 32)) as pilot:
        panel = await _open_panel(pilot, app)
        panel._begin_cell_edit("input", ghost=True)
        assert panel._cell_edit is not None
        panel._cell_edit.values["name"] = "status"
        panel._cell_edit.values["type"] = "enum"
        panel._cell_edit.values["choices"] = "[wip, draft]"
        panel._cell_edit.values["default"] = "nope"
        _sync_editor(panel)
        panel._commit_cell_edit()
        assert panel.model.get_input("status") is None
        assert "expects one of" in panel._feedback or "not one of" in panel._feedback
        panel._cancel_active_edit()

        panel._begin_cell_edit("input", ghost=True)
        assert panel._cell_edit is not None
        panel._cell_edit.values["name"] = "title"
        panel._cell_edit.values["type"] = "word"
        panel._cell_edit.values["choices"] = "[a, b]"
        _sync_editor(panel)
        panel._commit_cell_edit()
        assert panel.model.get_input("title") is None
        assert "only allowed on type 'enum'" in panel._feedback
        panel._cancel_active_edit()


async def test_named_type_row_shows_named_type() -> None:
    app = _PromptBarApp("---\ninput:\n  effort: effort\n---\nbody")
    async with app.run_test(size=(100, 32)) as pilot:
        panel = await _open_panel(pilot, app)
        line = panel._input_item_line(
            panel.model.get_input("effort"),  # type: ignore[arg-type]
            name_width=6,
            type_width=6,
        )
        assert "effort" in line.plain
        await _begin_input_edit(panel, "effort")
        assert panel._cell_edit is not None
        assert panel._cell_edit.values["type"] == "effort"
        panel._cell_edit.values["description"] = "how hard"
        _sync_editor(panel)
        panel._commit_cell_edit()
        arg = panel.model.get_input("effort")
        assert arg is not None and arg.named_type == "effort"


async def test_edit_description_keeps_enum_metadata_and_repeatable() -> None:
    frontmatter = (
        "---\ninput:\n  status:\n    type: enum\n    choices:\n"
        "      - value: wip\n        label: Wip\n        description: Work\n"
        "      - value: ready\n    default: wip\n---\nbody"
    )
    app = _PromptBarApp(frontmatter)
    async with app.run_test(size=(100, 32)) as pilot:
        panel = await _open_panel(pilot, app)
        before = panel.model.get_input("status")
        assert before is not None and len(before.choices) == 2
        await _begin_input_edit(panel, "status")
        assert panel._cell_edit is not None
        assert "wip" in panel._cell_edit.values["choices"]
        panel._cell_edit.values["description"] = "updated"
        _sync_editor(panel)
        panel._commit_cell_edit()
        after = panel.model.get_input("status")
        assert after is not None
        assert after.description == "updated"
        assert [c.value for c in after.choices] == ["wip", "ready"]
        assert after.choices[0].label == "Wip"


async def test_local_macro_compact_edit_keeps_enum_choices() -> None:
    frontmatter = (
        "---\nmacros:\n  _helper:\n    content: hi\n    input:\n"
        "      status:\n        type: enum\n        choices:\n"
        "          - wip\n          - draft\n        default: wip\n---\nbody"
    )
    app = _PromptBarApp(frontmatter)
    async with app.run_test(size=(100, 32)) as pilot:
        panel = await _open_panel(pilot, app)
        panel._begin_cell_edit("macros", item_name="_helper")
        assert panel._cell_edit is not None
        panel._cell_edit.values["content"] = "hello"
        _sync_editor(panel)
        panel._commit_cell_edit()
        macro = panel.model.get_macro("_helper")
        assert macro is not None
        assert [c.value for c in macro.inputs[0].choices] == ["wip", "draft"]


async def test_new_compact_enum_rejected_with_actionable_message() -> None:
    from sase.ace.tui.widgets.frontmatter_panel import FrontmatterPanel as _P

    with __import__("pytest").raises(ValueError, match="raw-YAML"):
        _P._parse_compact_inputs("x:enum")


async def test_save_reopen_round_trips_choice_metadata() -> None:
    app = _PromptBarApp("---\ninput:\n  service: word\n---\nbody")
    async with app.run_test(size=(100, 32)) as pilot:
        panel = await _open_panel(pilot, app)
        panel._begin_cell_edit("input", ghost=True)
        assert panel._cell_edit is not None
        panel._cell_edit.values["name"] = "status"
        panel._cell_edit.values["type"] = "enum"
        panel._cell_edit.values["choices"] = (
            "[{value: ready, label: Ready, description: Ship it}, wip]"
        )
        _sync_editor(panel)
        panel._commit_cell_edit()
        serialized = panel.model.serialize()
        assert "Ship it" in serialized
        from sase.macro.prompt_frontmatter import PromptFrontmatter

        reopened = PromptFrontmatter.parse(serialized)
        arg = reopened.get_input("status")
        assert arg is not None
        assert arg.choices[0].description == "Ship it"
