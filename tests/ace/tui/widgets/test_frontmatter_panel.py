"""Activation and keymap tests for the prompt Frontmatter Panel."""

from __future__ import annotations

import pytest

from sase.ace.tui.widgets.frontmatter_panel import FrontmatterPanel
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from sase.ace.tui.widgets.vim_text_area import VimTextArea

from ._frontmatter_panel_helpers import _PromptBarApp


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


async def test_q_returns_to_previously_active_prompt_pane() -> None:
    """Rows-mode ``q`` returns to the pane used to enter the panel."""
    app = _PromptBarApp("first\n---\nsecond\n---\nthird")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        bar.focus_item(1)
        await pilot.pause()
        bar.focus_frontmatter_panel()
        await pilot.pause()
        await pilot.pause()

        await pilot.press("q")
        await pilot.pause()
        await pilot.pause()

        assert bar._stack.selected_index == 1
        assert app.focused is bar.active_text_area()
        assert bar.active_text_area()._vim_mode == "insert"


@pytest.mark.parametrize("exit_key", ("q", "escape"))
@pytest.mark.parametrize("edit_mode", ("edit", "picker", "cell", "content", "raw"))
async def test_exit_key_leaves_every_panel_editor_mode(
    edit_mode: str,
    exit_key: str,
) -> None:
    """NORMAL-mode ``q`` / ``Esc`` share the panel's deactivate semantics."""
    app = _PromptBarApp("")

    async with app.run_test(size=(100, 34)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        bar.focus_frontmatter_panel()
        await pilot.pause()
        await pilot.pause()
        panel = app.query_one(FrontmatterPanel)

        if edit_mode == "edit":
            panel.begin_add("name")
            editor = panel.query_one("#frontmatter-inline", SingleLineVimTextArea)
        elif edit_mode == "picker":
            panel._request_add_property()
            editor = panel.query_one("#frontmatter-inline", SingleLineVimTextArea)
        elif edit_mode == "cell":
            panel.begin_add("input")
            editor = panel.query_one("#frontmatter-inline", SingleLineVimTextArea)
        elif edit_mode == "content":
            panel.begin_add("xprompts")
            panel._move_cell(1)
            panel._move_cell(1)
            panel._move_cell(1)
            editor = panel.query_one("#frontmatter-content", VimTextArea)
        else:
            panel._begin_raw()
            editor = panel.query_one("#frontmatter-raw", VimTextArea)

        editor._enter_normal_mode()
        editor.focus()
        await pilot.pause()
        assert panel._edit_mode == edit_mode

        await pilot.press(exit_key)
        await pilot.pause()
        await pilot.pause()

        assert not bar._frontmatter_panel_visible()
        assert app.focused is bar.active_text_area()
        assert bar.active_text_area()._vim_mode == "insert"


async def test_q_in_child_editor_insert_mode_stays_literal() -> None:
    """The child host policy does not steal a literal ``q`` in INSERT mode."""
    app = _PromptBarApp("")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        bar.focus_frontmatter_panel()
        await pilot.pause()
        await pilot.pause()
        panel = app.query_one(FrontmatterPanel)
        panel.begin_add("name")
        editor = panel.query_one("#frontmatter-inline", SingleLineVimTextArea)
        assert editor._vim_mode == "insert"

        await pilot.press("q")
        await pilot.pause()

        assert editor.text == "q"
        assert panel._edit_mode == "edit"
        assert app.focused is editor
        assert bar._frontmatter_panel_visible()


async def test_q_keeps_unparseable_raw_yaml_open() -> None:
    """Raw ``q`` validates first and preserves an invalid buffer for repair."""
    app = _PromptBarApp("")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        bar.focus_frontmatter_panel()
        await pilot.pause()
        await pilot.pause()
        panel = app.query_one(FrontmatterPanel)
        panel._begin_raw()
        raw = panel.query_one("#frontmatter-raw", VimTextArea)
        raw.text = "description: [unterminated"
        raw._enter_normal_mode()
        raw.focus()

        await pilot.press("q")
        await pilot.pause()

        assert panel._edit_mode == "raw"
        assert bar._frontmatter_panel_visible()
        assert app.focused is raw
        assert panel._feedback_lines == 1


@pytest.mark.parametrize(("keys", "target"), ((("g", "j"), 0), (("g", "k"), 2)))
async def test_panel_gj_gk_jump_to_stack_edge(
    keys: tuple[str, str],
    target: int,
) -> None:
    """Rows-mode ``gj`` / ``gk`` target the top / bottom prompt pane."""
    app = _PromptBarApp("first\n---\nsecond\n---\nthird")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        bar.focus_item(1)
        await pilot.pause()
        bar.focus_frontmatter_panel()
        await pilot.pause()
        await pilot.pause()
        panel = app.query_one(FrontmatterPanel)

        await pilot.press(keys[0])
        assert panel.border_subtitle == "g= done · gj top pane · gk bottom pane"
        await pilot.press(keys[1])
        await pilot.pause()
        await pilot.pause()

        assert bar._stack.selected_index == target
        assert app.focused is bar.active_text_area()
        for index, item in enumerate(bar._stack.items):
            pane = app.query_one(f"#{bar._pane_id(item)}")
            assert ("active" in pane.classes) is (index == target)
            assert ("inactive" in pane.classes) is (index != target)


async def test_other_panel_g_continuation_falls_through() -> None:
    """An unclaimed panel ``g`` continuation still runs its rows command."""
    app = _PromptBarApp("")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        bar.focus_frontmatter_panel()
        await pilot.pause()
        await pilot.pause()
        panel = app.query_one(FrontmatterPanel)

        await pilot.press("g", "R")
        await pilot.pause()

        assert panel._edit_mode == "raw"
        assert app.focused is panel.query_one("#frontmatter-raw", VimTextArea)


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
        editor = panel.query_one("#frontmatter-inline", SingleLineVimTextArea)
        assert app.focused is editor

        await pilot.press("g", "=")
        await pilot.pause()

        # The chars are typed into the inline editor; the panel stays open in
        # edit mode (the in-panel ``g=`` sequence is rows-mode-only).
        assert panel._edit_mode == "edit"
        assert "g=" in editor.text
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
        raw = panel.query_one("#frontmatter-raw", VimTextArea)
        assert app.focused is raw

        await pilot.press("g", "=")
        await pilot.pause()

        # Still in raw mode with focus in the editor; the chars went into it.
        assert panel._edit_mode == "raw"
        assert app.focused is raw
        assert "g=" in raw.text
        assert bar._frontmatter_panel_visible()
