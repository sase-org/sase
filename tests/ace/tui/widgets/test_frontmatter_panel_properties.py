"""Property editing tests for the in-place Frontmatter Panel."""

from __future__ import annotations

from sase.ace.tui.widgets.frontmatter_panel import FrontmatterPanel
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from sase.ace.tui.widgets.vim_text_area import VimTextArea

from ._frontmatter_panel_helpers import _PromptBarApp


async def _open_panel(app: _PromptBarApp, pilot: object) -> FrontmatterPanel:
    bar = app.query_one(PromptInputBar)
    bar.focus_frontmatter_panel()
    await pilot.pause()  # type: ignore[attr-defined]
    await pilot.pause()  # type: ignore[attr-defined]
    return app.query_one(FrontmatterPanel)


async def test_add_property_picker_is_inline_and_commits_scalar() -> None:
    app = _PromptBarApp("")
    async with app.run_test(size=(90, 30)) as pilot:
        panel = await _open_panel(app, pilot)
        bar = app.query_one(PromptInputBar)

        await pilot.press("a")
        await pilot.pause()
        assert app.screen is app.screen_stack[0]
        assert panel._edit_mode == "picker"
        editor = panel.query_one("#frontmatter-inline", SingleLineVimTextArea)
        editor.text = "name"
        await pilot.press("enter")
        await pilot.pause()
        assert panel._editing_field == "name"

        editor.text = "demo"
        await pilot.press("enter")
        await pilot.pause()
        assert panel.model.name == "demo"
        assert bar._stack.frontmatter == "---\nname: demo\n---"
        assert panel._edit_mode == "rows"
        assert app.focused is panel


async def test_structured_header_enter_toggles_fold() -> None:
    app = _PromptBarApp("---\ninput:\n  service: word\n---\nbody")
    async with app.run_test(size=(90, 30)) as pilot:
        panel = await _open_panel(app, pilot)
        assert panel._selected_nav() == ("field", "input")
        await pilot.press("enter")
        assert "input" in panel._folded
        assert panel.model.get_input("service") is not None
        await pilot.press("enter")
        assert "input" not in panel._folded


async def test_delete_then_undo_restores_field() -> None:
    app = _PromptBarApp("---\ndescription: keep me\n---\nbody")
    async with app.run_test(size=(90, 30)) as pilot:
        panel = await _open_panel(app, pilot)
        await pilot.press("d")
        assert panel.model.description is None
        await pilot.press("u")
        assert panel.model.description == "keep me"


async def test_passthrough_extra_is_visible_and_raw_only() -> None:
    app = _PromptBarApp("---\nname: demo\noutput: {type: json_schema}\n---\nbody")
    async with app.run_test(size=(90, 30)) as pilot:
        panel = await _open_panel(app, pilot)
        assert panel.model.extras == {"output": {"type": "json_schema"}}
        await pilot.press("j", "e")
        assert panel._edit_mode == "rows"
        assert "raw" in panel._feedback


async def test_raw_parse_failure_is_discardable() -> None:
    app = _PromptBarApp("---\nname: demo\n---\nbody")
    async with app.run_test(size=(90, 30)) as pilot:
        panel = await _open_panel(app, pilot)
        await pilot.press("R")
        raw = panel.query_one("#frontmatter-raw", VimTextArea)
        raw.text = "---\nname: [unterminated\n---"
        raw._enter_normal_mode()
        await pilot.press("escape")
        assert panel._edit_mode == "raw"
        await pilot.press("ctrl+c")
        assert panel._edit_mode == "rows"
        assert panel.model.name == "demo"


async def test_bool_payload_state_does_not_sniff_boolean_words() -> None:
    app = _PromptBarApp("---\nskill: false\n---\nbody")
    async with app.run_test(size=(90, 30)) as pilot:
        panel = await _open_panel(app, pilot)
        await pilot.press("e")
        assert panel._cell_edit is not None
        editor = panel.query_one("#frontmatter-inline", SingleLineVimTextArea)
        editor.text = "providers…"
        panel._move_cell(1)
        editor.text = "on"
        panel._commit_cell_edit()
        assert panel.model.skill == ["on"]
