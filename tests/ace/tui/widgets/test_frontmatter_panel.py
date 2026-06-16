"""Widget-level tests for the prompt Frontmatter Panel (Phase 3).

Covers the Phase 3 deliverable of the prompt-frontmatter-panel epic: the leading
``---``-newline trigger (distinct from a multi-agent segment separator), the
``,f`` focus keymap, auto-show on existing frontmatter, the add-property picker
plus inline scalar/list editing, ``d`` delete, the ``R`` raw-YAML round-trip, and
the empty-on-exit removal of the frontmatter.
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


# --- trigger ---------------------------------------------------------------


async def test_leading_dash_newline_opens_panel() -> None:
    """``---`` then a newline at the very start promotes into frontmatter mode."""
    app = _PromptBarApp("")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)

        await pilot.press("-", "-", "-")
        await pilot.pause()
        # A bare leading ``---`` must NOT split into two empty panes; it waits.
        assert len(app.query(".prompt-input")) == 1
        assert not bar._frontmatter_panel_visible()

        await pilot.press("ctrl+j")  # the newline (Enter submits in this bar)
        await pilot.pause()
        await pilot.pause()

        panel = app.query_one(FrontmatterPanel)
        assert bar._frontmatter_panel_visible()
        assert app.focused is panel
        # The typed ``---\n`` is lifted off the body, leaving an empty pane.
        assert bar.active_text() == ""
        assert len(app.query(".prompt-input")) == 1


async def test_dash_after_content_still_splits() -> None:
    """A ``---`` typed after content stays a multi-agent segment separator."""
    app = _PromptBarApp("foo")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)

        await pilot.press("ctrl+j", "-", "-", "-")
        await pilot.pause()
        await pilot.pause()

        assert len(app.query(".prompt-input")) == 2
        assert not bar._frontmatter_panel_visible()


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
