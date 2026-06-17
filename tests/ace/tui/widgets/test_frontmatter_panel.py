"""Widget-level tests for the prompt Frontmatter Panel (Phase 3).

Covers the Phase 3 deliverable of the prompt-frontmatter-panel epic: a typed
``---`` is inert (the panel opens only through the explicit ``,f`` /
``Ctrl+Shift+=`` controls), the ``,f`` focus keymap, auto-show on existing
frontmatter, the add-property picker plus inline scalar/list editing, ``d``
delete, the ``R`` raw-YAML round-trip, and the empty-on-exit removal of the
frontmatter.
"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Input, TextArea

from sase.ace.tui.modals import AddPropertyModal
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


async def test_comma_f_focuses_panel() -> None:
    """``,f`` shows and focuses the panel from an empty single-pane prompt."""
    app = _PromptBarApp("")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)

        await pilot.press("escape")
        await pilot.press("comma", "f")
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


# --- add / edit / delete scalars -------------------------------------------


async def test_add_property_via_picker_and_edit() -> None:
    """``a`` opens the core-schema picker; selecting a field edits it inline."""
    app = _PromptBarApp("")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        await pilot.press("escape")
        await pilot.press("comma", "f")
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


# --- Ctrl+Shift+= toggle ---------------------------------------------------


async def test_ctrl_shift_equals_opens_panel_from_insert() -> None:
    """The chord shows and focuses an empty panel while typing (insert mode)."""
    app = _PromptBarApp("")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        assert bar.active_text_area()._vim_mode == "insert"

        await pilot.press("ctrl+shift+equals")
        await pilot.pause()
        await pilot.pause()

        panel = app.query_one(FrontmatterPanel)
        assert bar._frontmatter_panel_visible()
        assert app.focused is panel


async def test_ctrl_shift_equals_opens_panel_from_normal() -> None:
    """The chord shows and focuses the panel while browsing (normal mode)."""
    app = _PromptBarApp("")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        await pilot.press("escape")  # -> normal mode

        await pilot.press("ctrl+shift+equals")
        await pilot.pause()
        await pilot.pause()

        panel = app.query_one(FrontmatterPanel)
        assert bar._frontmatter_panel_visible()
        assert app.focused is panel


async def test_ctrl_shift_equals_again_closes_empty_panel() -> None:
    """Pressing the chord from an empty focused panel deactivates and hides it."""
    app = _PromptBarApp("")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)

        await pilot.press("ctrl+shift+equals")  # open + focus
        await pilot.pause()
        await pilot.pause()
        panel = app.query_one(FrontmatterPanel)
        assert app.focused is panel

        await pilot.press("ctrl+shift+equals")  # toggle off (panel owns focus)
        await pilot.pause()
        await pilot.pause()

        assert not bar._frontmatter_panel_visible()
        assert bar._stack.frontmatter == ""
        # Focus returns to the body, ready to type.
        assert app.focused is bar.active_text_area()
        assert bar.active_text_area()._vim_mode == "insert"


async def test_ctrl_shift_equals_toggles_focus_with_populated_panel() -> None:
    """With existing frontmatter the chord round-trips focus, keeping the panel."""
    app = _PromptBarApp("---\ndescription: keep\n---\na\n---\nb")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        # Auto-shown on existing frontmatter, with focus left on the body.
        assert bar._frontmatter_panel_visible()
        assert app.focused is bar.active_text_area()

        await pilot.press("ctrl+shift+equals")  # focus the visible panel
        await pilot.pause()
        await pilot.pause()
        panel = app.query_one(FrontmatterPanel)
        assert app.focused is panel

        await pilot.press("ctrl+shift+equals")  # back to body, keep the panel
        await pilot.pause()
        await pilot.pause()

        assert bar._frontmatter_panel_visible()
        assert bar._stack.frontmatter == "---\ndescription: keep\n---"
        assert app.focused is bar.active_text_area()


async def test_ctrl_shift_plus_alias_opens_panel() -> None:
    """The shifted-equals key path is also reported as ``ctrl+shift+plus``."""
    app = _PromptBarApp("")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)

        await pilot.press("ctrl+shift+plus")  # open + focus via the plus spelling
        await pilot.pause()
        await pilot.pause()
        panel = app.query_one(FrontmatterPanel)
        assert app.focused is panel

        await pilot.press("ctrl+shift+plus")  # toggle off from the panel
        await pilot.pause()
        await pilot.pause()
        assert not bar._frontmatter_panel_visible()
        assert app.focused is bar.active_text_area()


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


async def test_ctrl_shift_equals_noop_in_feedback_mode() -> None:
    """Feedback bars mount no panel, so the chord creates nothing."""
    app = _PromptBarApp("feedback text", mode="feedback")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)

        await pilot.press("ctrl+shift+equals")
        await pilot.pause()
        await pilot.pause()

        assert bar._frontmatter_panel() is None
        assert len(app.query(FrontmatterPanel)) == 0
        assert bar.active_text() == "feedback text"


async def test_ctrl_shift_equals_cancels_inline_edit_then_closes() -> None:
    """From an in-progress inline edit the chord cancels it, then deactivates."""
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
        editor.value = "typed but unsaved"

        await pilot.press("ctrl+shift+equals")  # cancel inline edit + close
        await pilot.pause()
        await pilot.pause()

        # The unsaved add is discarded and the empty panel closes.
        assert panel.model.is_empty
        assert not bar._frontmatter_panel_visible()
        assert app.focused is bar.active_text_area()


async def test_ctrl_shift_equals_applies_raw_then_closes() -> None:
    """From raw mode the chord applies parseable YAML, then deactivates."""
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
        raw.text = "description: from raw\n"
        await pilot.pause()

        await pilot.press("ctrl+shift+equals")  # apply raw + close
        await pilot.pause()
        await pilot.pause()

        assert panel.model.description == "from raw"
        assert "description: from raw" in bar._stack.frontmatter
        # Applied + non-empty: panel stays visible, focus returns to the body.
        assert bar._frontmatter_panel_visible()
        assert app.focused is bar.active_text_area()


async def test_ctrl_shift_equals_keeps_invalid_raw_active() -> None:
    """Unparseable raw YAML keeps the raw editor open (no silent discard)."""
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
        # A non-``_``-prefixed local xprompt name fails to parse.
        raw.text = "xprompts:\n  badname:\n    prompt: hi\n"
        await pilot.pause()

        await pilot.press("ctrl+shift+equals")
        await pilot.pause()
        await pilot.pause()

        assert panel._edit_mode == "raw"
        assert app.focused is raw
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
