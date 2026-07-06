"""Property editing tests for the prompt Frontmatter Panel."""

from __future__ import annotations

import pytest

from sase.ace.tui.modals import AddableProperty, AddPropertyModal, XPromptItemModal
from sase.ace.tui.widgets.frontmatter_panel import FrontmatterPanel
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from sase.ace.tui.widgets.vim_text_area import VimTextArea

from ._frontmatter_panel_helpers import _PromptBarApp


def _modal_properties(panel: FrontmatterPanel) -> list[AddableProperty]:
    return [
        AddableProperty(
            name=descriptor.name,
            description=descriptor.description,
            kind=descriptor.kind.value,
            example=descriptor.example,
            allowed_values=descriptor.allowed_values,
        )
        for descriptor in panel.addable_properties()
    ]


# --- add / edit / delete scalars -------------------------------------------


async def test_add_property_via_picker_and_edit() -> None:
    """``a`` opens the core-schema picker; selecting a field edits it inline."""
    app = _PromptBarApp("")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        await pilot.press("escape")
        await pilot.press("g", "=")
        await pilot.pause()
        await pilot.pause()
        panel = app.query_one(FrontmatterPanel)

        await pilot.press("a")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, AddPropertyModal)

        await pilot.press("enter")  # pick the first field (``name``)
        await pilot.pause()
        await pilot.pause()
        assert panel._editing_field == "name"

        await pilot.press("d", "e", "m", "o")
        await pilot.press("enter")
        await pilot.pause()

        assert panel.model.name == "demo"
        assert bar._stack.frontmatter == "---\nname: demo\n---"


async def test_add_property_accelerator_picks_scalar_field() -> None:
    """A property accelerator immediately selects that field without leaking text."""
    app = _PromptBarApp("")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        await pilot.press("escape")
        await pilot.press("g", "=")
        await pilot.pause()
        await pilot.pause()
        panel = app.query_one(FrontmatterPanel)

        await pilot.press("a")
        await pilot.pause()
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, AddPropertyModal)
        assert {choice.prop.name: choice.key for choice in modal._choices}[
            "tags"
        ] == "t"

        await pilot.press("t")
        await pilot.pause()
        await pilot.pause()

        editor = panel.query_one("#frontmatter-inline", SingleLineVimTextArea)
        assert panel._editing_field == "tags"
        assert app.focused is editor
        assert editor.text == ""
        assert bar._frontmatter_panel_visible()


async def test_add_property_accelerator_opens_structured_modal() -> None:
    """A structured property accelerator opens the matching sub-form modal."""
    app = _PromptBarApp("")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        await pilot.press("escape")
        await pilot.press("g", "=")
        await pilot.pause()
        await pilot.pause()

        await pilot.press("a")
        await pilot.pause()
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, AddPropertyModal)
        assert {choice.prop.name: choice.key for choice in modal._choices}[
            "xprompts"
        ] == "x"

        await pilot.press("x")
        await pilot.pause()
        await pilot.pause()

        assert isinstance(app.screen, XPromptItemModal)
        assert bar._frontmatter_panel_visible()


async def test_a_on_existing_xprompts_header_opens_property_picker() -> None:
    """``a`` stays the property picker even on a structured field header."""
    app = _PromptBarApp(
        "---\nxprompts:\n  _rules: Follow the checklist\n---\nfirst\n---\nsecond"
    )

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        bar.focus_frontmatter_panel()
        await pilot.pause()
        await pilot.pause()
        panel = app.query_one(FrontmatterPanel)

        assert panel._selected_nav() == ("field", "xprompts")
        await pilot.press("a")
        await pilot.pause()
        await pilot.pause()

        assert isinstance(app.screen, AddPropertyModal)


def test_add_property_accelerators_are_unique_and_exclude_set_fields() -> None:
    """Unset fields keep deterministic unique accelerator keys."""
    empty_panel = FrontmatterPanel("")
    modal = AddPropertyModal(_modal_properties(empty_panel))
    keys_by_name = {choice.prop.name: choice.key for choice in modal._choices}

    assert keys_by_name == {
        "name": "n",
        "description": "d",
        "tags": "t",
        "input": "i",
        "xprompts": "x",
        "skill": "s",
        "snippet": "p",
    }
    assert len(set(keys_by_name.values())) == len(keys_by_name)

    populated_panel = FrontmatterPanel("---\nname: demo\ntags: cli\n---")
    addable_names = [
        descriptor.name for descriptor in populated_panel.addable_properties()
    ]
    assert "name" not in addable_names
    assert "tags" not in addable_names
    populated_modal = AddPropertyModal(_modal_properties(populated_panel))
    assert [choice.prop.name for choice in populated_modal._choices] == addable_names


@pytest.mark.parametrize("cancel_key", ["escape", "q"])
async def test_add_property_picker_cancel_returns_focus_to_panel(
    cancel_key: str,
) -> None:
    """Cancelling the picker returns focus to panel row navigation."""
    app = _PromptBarApp("")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        await pilot.press("escape")
        await pilot.press("g", "=")
        await pilot.pause()
        await pilot.pause()
        panel = app.query_one(FrontmatterPanel)

        await pilot.press("a")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, AddPropertyModal)

        await pilot.press(cancel_key)
        await pilot.pause()
        await pilot.pause()

        assert not isinstance(app.screen, AddPropertyModal)
        assert app.focused is panel
        assert panel._edit_mode == "rows"
        assert bar._frontmatter_panel_visible()


async def test_edit_existing_scalar_inline() -> None:
    """``e`` edits the selected scalar; the new value persists to the stack."""
    app = _PromptBarApp("---\ndescription: old\n---\na\n---\nb")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        bar.focus_frontmatter_panel()
        await pilot.pause()
        await pilot.pause()
        panel = app.query_one(FrontmatterPanel)

        await pilot.press("e")  # edit selected (description)
        await pilot.pause()
        editor = panel.query_one("#frontmatter-inline", SingleLineVimTextArea)
        assert app.focused is editor

        # Replace the value: select-none, just clear and retype via the model.
        editor.text = "new"
        await pilot.press("enter")
        await pilot.pause()

        assert panel.model.description == "new"
        assert "description: new" in bar._stack.frontmatter


async def test_edit_tags_list_inline() -> None:
    """A comma-separated tags edit becomes a YAML list on the model."""
    app = _PromptBarApp("")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        bar.focus_frontmatter_panel()
        await pilot.pause()
        await pilot.pause()
        panel = app.query_one(FrontmatterPanel)

        panel.begin_add("tags")
        await pilot.pause()
        editor = panel.query_one("#frontmatter-inline", SingleLineVimTextArea)
        editor.text = "refactor, backend"
        await pilot.press("enter")
        await pilot.pause()

        assert panel.model.tags == ["refactor", "backend"]


async def test_delete_field() -> None:
    """``d`` removes the selected field and clears it from the stack string."""
    app = _PromptBarApp("---\ndescription: gone\n---\na\n---\nb")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        bar.focus_frontmatter_panel()
        await pilot.pause()
        await pilot.pause()
        panel = app.query_one(FrontmatterPanel)

        assert panel._fields == ["description"]
        await pilot.press("d")
        await pilot.pause()

        assert panel.model.is_empty
        assert bar._stack.frontmatter == ""


# --- raw YAML mode ---------------------------------------------------------


async def test_raw_mode_round_trip() -> None:
    """``R`` edits canonical YAML; ``esc`` re-parses it into the model."""
    app = _PromptBarApp("")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        bar.focus_frontmatter_panel()
        await pilot.pause()
        await pilot.pause()
        panel = app.query_one(FrontmatterPanel)

        await pilot.press("R")
        await pilot.pause()
        raw = panel.query_one("#frontmatter-raw", VimTextArea)
        assert app.focused is raw

        raw.text = "description: from raw\ntags:\n- x\n- y\n"
        await pilot.pause()
        await pilot.press("escape", "escape")  # INSERT -> NORMAL, then apply
        await pilot.pause()

        assert panel._edit_mode == "rows"
        assert panel.model.description == "from raw"
        assert panel.model.tags == ["x", "y"]
        assert "description: from raw" in bar._stack.frontmatter


# --- folding ---------------------------------------------------------------


async def test_fold_unfold_structured_subtree() -> None:
    """``h``/``l`` fold and unfold a read-only ``input`` sub-tree."""
    app = _PromptBarApp("---\ninput:\n  service: word\n---\nfirst\n---\nsecond")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        bar.focus_frontmatter_panel()
        await pilot.pause()
        await pilot.pause()
        panel = app.query_one(FrontmatterPanel)

        assert panel._fields == ["input"]
        await pilot.press("h")  # fold
        await pilot.pause()
        assert "input" in panel._folded
        await pilot.press("l")  # unfold
        await pilot.pause()
        assert "input" not in panel._folded
