"""Widget-level tests for the prompt Frontmatter Panel (Phase 3).

Covers the Phase 3 deliverable of the prompt-frontmatter-panel epic: a typed
``---`` is inert (the panel opens only through the explicit NORMAL-mode ``g=``
keymap), the ``g=`` focus keymap and its in-panel deactivate sequence, auto-show
on existing frontmatter, the add-property picker plus inline scalar/list editing,
``d`` delete, the ``R`` raw-YAML round-trip, and the empty-on-exit removal of the
frontmatter.  The retired ``,f`` / ``Ctrl+Shift+=`` controls are kept inert.
"""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Input, TextArea

from sase.ace.tui.modals import AddableProperty, AddPropertyModal, XPromptItemModal
from sase.ace.tui.widgets.frontmatter_panel import FrontmatterPanel
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar


class _PromptBarApp(App[None]):
    """Minimal app hosting a single prompt input bar, like the stack tests."""

    ENABLE_COMMAND_PALETTE = False

    def __init__(self, initial_value: str = "", mode: str = "prompt") -> None:
        super().__init__()
        self._initial_value = initial_value
        self._mode = mode

    def compose(self) -> ComposeResult:
        yield PromptInputBar(
            initial_value=self._initial_value,
            mode=self._mode,
            id="prompt-input-bar",
        )


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


# --- typed `---` is passive ------------------------------------------------


async def test_leading_dash_newline_stays_passive() -> None:
    """``---`` + newline at the very start no longer promotes into frontmatter."""
    app = _PromptBarApp("")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)

        await pilot.press("-", "-", "-", "ctrl+j")
        await pilot.pause()
        await pilot.pause()

        # The panel stays hidden, the bar keeps its single pane, and the typed
        # delimiter is left verbatim in the body — no implicit promotion.
        assert len(app.query(".prompt-input")) == 1
        assert not bar._frontmatter_panel_visible()
        assert bar.active_text() == "---\n"


async def test_dash_after_content_stays_passive() -> None:
    """A ``---`` typed after content stays literal text, not a live split."""
    app = _PromptBarApp("foo")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)

        await pilot.press("ctrl+j", "-", "-", "-")
        await pilot.pause()
        await pilot.pause()

        # Still one pane (no split), focus stays in it, and the separator text is
        # preserved exactly as typed.
        assert len(app.query(".prompt-input")) == 1
        assert not bar._frontmatter_panel_visible()
        assert bar.active_text() == "foo\n---"
        assert app.focused is bar.active_text_area()


# --- focus + auto-show -----------------------------------------------------


async def test_g_equals_focuses_panel() -> None:
    """``g=`` shows and focuses the panel from an empty single-pane prompt."""
    app = _PromptBarApp("")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)

        await pilot.press("escape")
        await pilot.press("g", "=")
        await pilot.pause()
        await pilot.pause()

        panel = app.query_one(FrontmatterPanel)
        assert bar._frontmatter_panel_visible()
        assert app.focused is panel


async def test_ctrl_g_equals_focuses_panel_from_insert() -> None:
    """``Ctrl+G =`` shows and focuses the panel from INSERT mode."""
    app = _PromptBarApp("")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)

        await pilot.press("ctrl+g", "=")
        await pilot.pause()
        await pilot.pause()

        panel = app.query_one(FrontmatterPanel)
        assert bar._frontmatter_panel_visible()
        assert app.focused is panel


async def test_auto_show_on_existing_frontmatter() -> None:
    """Opening on a prompt that already carries frontmatter mounts the panel."""
    app = _PromptBarApp("---\ndescription: hi\n---\nfirst\n---\nsecond")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)

        assert bar._stack.frontmatter == "---\ndescription: hi\n---"
        assert bar._frontmatter_panel_visible()
        # Auto-show does not steal focus from the prompt body.
        assert app.focused is bar.active_text_area()
        panel = app.query_one(FrontmatterPanel)
        assert panel.model.description == "hi"


async def test_reserved_height_counts_panel_bottom_margin() -> None:
    """Rows mode reserves content, round border, and the panel bottom margin."""
    app = _PromptBarApp("---\ndescription: hi\n---\nfirst\n---\nsecond")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        panel = app.query_one(FrontmatterPanel)
        assert panel._edit_mode == "rows"
        assert panel._content_lines == 1
        assert panel.reserved_height == panel._content_lines + 3


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

        editor = panel.query_one("#frontmatter-inline", Input)
        assert panel._editing_field == "tags"
        assert app.focused is editor
        assert editor.value == ""
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
        editor = panel.query_one("#frontmatter-inline", Input)
        assert app.focused is editor

        # Replace the value: select-none, just clear and retype via the model.
        editor.value = "new"
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
        editor = panel.query_one("#frontmatter-inline", Input)
        editor.value = "refactor, backend"
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
        raw = panel.query_one("#frontmatter-raw", TextArea)
        assert app.focused is raw

        raw.text = "description: from raw\ntags:\n- x\n- y\n"
        await pilot.pause()
        await pilot.press("escape")  # apply
        await pilot.pause()

        assert panel._edit_mode == "rows"
        assert panel.model.description == "from raw"
        assert panel.model.tags == ["x", "y"]
        assert "description: from raw" in bar._stack.frontmatter


# --- close behavior --------------------------------------------------------


async def test_close_empty_removes_frontmatter() -> None:
    """Leaving an empty panel drops the frontmatter and returns to the body."""
    app = _PromptBarApp("")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        bar.focus_frontmatter_panel()
        await pilot.pause()
        await pilot.pause()

        await pilot.press("escape")  # nothing added -> close empty
        await pilot.pause()
        await pilot.pause()

        assert not bar._frontmatter_panel_visible()
        assert bar._stack.frontmatter == ""
        assert app.focused is bar.active_text_area()


async def test_close_populated_keeps_panel_visible() -> None:
    """Leaving a populated panel keeps it shown and refocuses the body."""
    app = _PromptBarApp("---\ndescription: keep\n---\na\n---\nb")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        bar.focus_frontmatter_panel()
        await pilot.pause()
        await pilot.pause()

        await pilot.press("escape")
        await pilot.pause()
        await pilot.pause()

        assert bar._frontmatter_panel_visible()
        assert bar._stack.frontmatter == "---\ndescription: keep\n---"
        assert app.focused is bar.active_text_area()


# --- g= toggle (body + in-panel) -------------------------------------------


async def test_g_equals_again_closes_empty_panel_from_inside() -> None:
    """``g=`` from inside an empty focused panel deactivates and hides it."""
    app = _PromptBarApp("")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)

        await pilot.press("escape")
        await pilot.press("g", "=")  # open + focus from the body
        await pilot.pause()
        await pilot.pause()
        panel = app.query_one(FrontmatterPanel)
        assert app.focused is panel

        await pilot.press("g", "=")  # toggle off from inside (panel owns focus)
        await pilot.pause()
        await pilot.pause()

        assert not bar._frontmatter_panel_visible()
        assert bar._stack.frontmatter == ""
        # Focus returns to the previously active prompt pane, ready to type.
        assert app.focused is bar.active_text_area()
        assert bar.active_text_area()._vim_mode == "insert"


async def test_g_equals_toggles_focus_with_populated_panel() -> None:
    """With existing frontmatter ``g=`` round-trips focus, keeping the panel."""
    app = _PromptBarApp("---\ndescription: keep\n---\na\n---\nb")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        # Auto-shown on existing frontmatter, with focus left on the body.
        assert bar._frontmatter_panel_visible()
        assert app.focused is bar.active_text_area()

        await pilot.press("escape")
        await pilot.press("g", "=")  # focus the visible panel from the body
        await pilot.pause()
        await pilot.pause()
        panel = app.query_one(FrontmatterPanel)
        assert app.focused is panel

        await pilot.press("g", "=")  # back to the body, keep the panel
        await pilot.pause()
        await pilot.pause()

        assert bar._frontmatter_panel_visible()
        assert bar._stack.frontmatter == "---\ndescription: keep\n---"
        assert app.focused is bar.active_text_area()


async def test_g_equals_noop_in_feedback_mode() -> None:
    """Feedback bars mount no panel, so ``g=`` creates nothing."""
    app = _PromptBarApp("feedback text", mode="feedback")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)

        await pilot.press("escape")
        await pilot.press("g", "=")
        await pilot.pause()
        await pilot.pause()

        assert bar._frontmatter_panel() is None
        assert len(app.query(FrontmatterPanel)) == 0
        # ``g=`` dispatched through the prompt ``g`` prefix table (a no-op here),
        # so nothing was typed into the body either.
        assert bar.active_text() == "feedback text"


# --- retired panel-toggle keys are inert -----------------------------------


@pytest.mark.parametrize(
    "old_key",
    ("ctrl+shift+equals", "ctrl+shift+equal", "ctrl+shift+plus", "ctrl+plus"),
)
async def test_old_frontmatter_chords_no_longer_open_panel(old_key: str) -> None:
    """The retired ``Ctrl+Shift+=`` family no longer opens the properties panel.

    The toggle migrated to the NORMAL-mode ``g=`` keymap, so the old shifted
    -equals chords are inert from both insert and normal mode and never show the
    panel.
    """
    app = _PromptBarApp("")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        assert not bar._frontmatter_panel_visible()

        # From insert (the chord used to work while typing) ...
        await pilot.press(old_key)
        await pilot.pause()
        await pilot.pause()
        assert not bar._frontmatter_panel_visible()

        # ... and from normal (it used to work while browsing too).
        await pilot.press("escape")
        await pilot.press(old_key)
        await pilot.pause()
        await pilot.pause()
        assert not bar._frontmatter_panel_visible()


async def test_comma_f_no_longer_opens_panel() -> None:
    """The retired prompt comma leader ``,f`` no longer opens the panel."""
    app = _PromptBarApp("")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        assert not bar._frontmatter_panel_visible()

        await pilot.press("escape")
        await pilot.press("comma", "f")
        await pilot.pause()
        await pilot.pause()

        # ``,`` is a prompt-local no-op now and ``f`` falls through to vim's
        # char-search; neither shows the properties panel.
        assert not bar._frontmatter_panel_visible()


async def test_ctrl_shift_minus_no_longer_opens_panel() -> None:
    """The retired ``Ctrl+Shift+-`` chord no longer opens the properties panel."""
    app = _PromptBarApp("")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        assert not bar._frontmatter_panel_visible()

        await pilot.press("ctrl+shift+minus")
        await pilot.pause()
        await pilot.pause()

        # The old minus chord is inert: the panel stays hidden and no extra pane
        # is added.
        assert not bar._frontmatter_panel_visible()
        assert len(app.query(".prompt-input")) == 1


# --- g / = stay literal while editing inside the panel ---------------------


async def test_g_equals_is_literal_during_inline_edit() -> None:
    """In inline edit mode ``g`` / ``=`` type into the editor, not deactivate."""
    app = _PromptBarApp("")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        bar.focus_frontmatter_panel()
        await pilot.pause()
        await pilot.pause()
        panel = app.query_one(FrontmatterPanel)

        panel.begin_add("name")
        await pilot.pause()
        editor = panel.query_one("#frontmatter-inline", Input)
        assert app.focused is editor

        await pilot.press("g", "=")
        await pilot.pause()

        # The chars are typed into the inline editor; the panel stays open in
        # edit mode (the in-panel ``g=`` sequence is rows-mode-only).
        assert panel._edit_mode == "edit"
        assert "g=" in editor.value
        assert bar._frontmatter_panel_visible()


async def test_g_equals_is_literal_during_raw_edit() -> None:
    """In raw YAML mode ``g`` / ``=`` type into the editor, not deactivate."""
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
        raw = panel.query_one("#frontmatter-raw", TextArea)
        assert app.focused is raw

        await pilot.press("g", "=")
        await pilot.pause()

        # Still in raw mode with focus in the editor; the chars went into it.
        assert panel._edit_mode == "raw"
        assert app.focused is raw
        assert "g=" in raw.text
        assert bar._frontmatter_panel_visible()


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
