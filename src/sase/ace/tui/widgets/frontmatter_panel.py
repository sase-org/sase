"""The prompt Frontmatter Panel widget (Phase 3 of the frontmatter-panel epic).

A persistent, navigable, focusable panel rendered directly above the prompt
stack (``#prompt-stack``).  It is the visible editing surface over the structured
:class:`~sase.xprompt.prompt_frontmatter.PromptFrontmatter` model built in Phase
2: it renders one row per set field with a type-styled value summary and a status
chip, validates live through the shared ``sase-core`` engine (so its guidance
never drifts from the xprompt LSP), and offers the common-case editors plus a raw
YAML escape hatch.

Phase 3 scope (this widget):

- **Navigate** set fields with ``j``/``k`` (and arrows); fold the read-only
  ``input`` / ``xprompts`` sub-trees with ``h``/``l``.
- **Add** a field with ``a`` (core-schema picker, handled by the host bar) and
  edit scalars / lists inline; **delete** the focused field with ``d``.
- **Raw** YAML mode with ``R``: edit the canonical serialized frontmatter in a
  single text area, validated live by core; on exit it re-parses into the model.
- **Done** with ``esc`` / ``q`` (or the ``g=`` toggle that opened it): hands
  focus back to the prompt body (the host bar removes the frontmatter entirely
  when the panel is left empty).

Structured values are edited in place: ``j``/``k`` navigate into unfolded
sub-trees, ``o``/``A`` inserts a ghost row, and ``e``/``enter`` opens the row's
cell strip without obscuring the prompt body. Raw mode remains the escape hatch
for the long tail and passthrough fields.

The widget owns a working copy of the model and announces edits to the host bar
via :class:`FrontmatterPanel.Changed`; leaving the panel posts
:class:`FrontmatterPanel.Closed`.  The bar persists the model back onto the
prompt stack's byte-stable ``frontmatter`` string, keeping ``parse_multi_prompt``
the launch source of truth.
"""

from __future__ import annotations

from typing import Any

from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Static

from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from sase.ace.tui.widgets.vim_text_area import VimTextArea
from sase.ace.tui.widgets._frontmatter_panel_editing import (
    FrontmatterPanelEditingMixin,
)
from sase.ace.tui.widgets._frontmatter_panel_raw import FrontmatterPanelRawMixin
from sase.ace.tui.widgets._frontmatter_panel_rendering import (
    FrontmatterPanelRenderingMixin,
)
from sase.xprompt.frontmatter_schema import frontmatter_field_schema
from sase.xprompt.prompt_frontmatter import PromptFrontmatter


class FrontmatterPanel(
    FrontmatterPanelRawMixin,
    FrontmatterPanelEditingMixin,
    FrontmatterPanelRenderingMixin,
    Vertical,
):
    """Structured editor for a prompt's YAML frontmatter, above the prompt stack."""

    can_focus = True

    class Changed(Message):
        """Posted when the panel mutates the model so the bar can persist it."""

        def __init__(self, model: PromptFrontmatter) -> None:
            super().__init__()
            self.model = model

    class Closed(Message):
        """Posted when the user leaves the panel (``esc`` / ``q``).

        ``is_empty`` tells the bar whether the model is now empty so it can drop
        the frontmatter entirely (no stray ``---\\n---``) and hide the panel.
        """

        def __init__(self, *, is_empty: bool) -> None:
            super().__init__()
            self.is_empty = is_empty

    class AddRequested(Message):
        """Posted on ``a`` so the host bar can push the add-property modal."""

    def __init__(self, frontmatter: str = "", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._model = PromptFrontmatter.parse(frontmatter)
        self._fields: list[str] = self._model.present_fields()
        self._selected = 0
        self._folded: set[str] = set()
        # "rows" (navigate), "edit" (inline scalar/list), or "raw" (YAML escape).
        self._edit_mode = "rows"
        # Pending panel-local ``g`` prefix (rows mode only); ``g=`` deactivates.
        self._pending_g = False
        # Pending prompt-local ``Ctrl+G`` prefix; ``Ctrl+G Ctrl+C`` forwards a
        # whole-stack cancel to the host bar even when the panel owns focus.
        self._pending_ctrl_g = False
        self._editing_field: str | None = None
        self._adding_field: str | None = None
        self._cell_edit: Any | None = None
        self._picker_matches: list[str] = []
        self._picker_selected = 0
        self._picker_accelerators: dict[str, str] = {}
        self._feedback = ""
        self._undo_stack: list[PromptFrontmatter] = []
        self._raw_diagnostics_generation = 0
        self._content_lines = 1
        schema = frontmatter_field_schema()
        self._schema = {f.name: f for f in schema}
        self._schema_order = [f.name for f in schema]

    # -- composition ----------------------------------------------------------

    def compose(self) -> ComposeResult:
        """A rows view plus the (hidden) inline and raw editors."""
        yield Static("", id="frontmatter-rows")
        yield SingleLineVimTextArea(id="frontmatter-inline", classes="hidden")
        yield VimTextArea(
            "",
            id="frontmatter-raw",
            classes="hidden",
            show_line_numbers=False,
            soft_wrap=True,
        )
        yield VimTextArea(
            "",
            id="frontmatter-content",
            classes="hidden",
            show_line_numbers=False,
            soft_wrap=True,
        )
        yield Static("", id="frontmatter-feedback", classes="hidden")

    def on_mount(self) -> None:
        """Render the initial rows once mounted."""
        self._refresh()

    # -- host-facing API ------------------------------------------------------

    def set_frontmatter(self, frontmatter: str) -> None:
        """Reset the working model from *frontmatter* and re-render the rows.

        Called by the host bar on auto-show / focus so the panel always reflects
        the prompt stack's current frontmatter string before the user edits it.
        """
        self._model = PromptFrontmatter.parse(frontmatter)
        self._fields = self._model.present_fields()
        self._selected = min(self._selected, max(0, len(self._fields) - 1))
        self._edit_mode = "rows"
        self._pending_g = False
        self._pending_ctrl_g = False
        self._editing_field = None
        self._adding_field = None
        self._cell_edit = None
        self._picker_matches = []
        self._picker_selected = 0
        self._picker_accelerators = {}
        self._feedback = ""
        self._undo_stack.clear()
        self._show_rows_only()
        self._refresh()

    def focus_panel(self) -> None:
        """Focus the panel for row navigation (the ``g=`` show/focus target)."""
        self._edit_mode = "rows"
        self._pending_g = False
        self._pending_ctrl_g = False
        self._show_rows_only()
        self.focus()
        self._refresh()

    @property
    def reserved_height(self) -> int:
        """Rows the panel occupies above the stack, including its bottom margin."""
        bottom_margin = 1
        if self._edit_mode == "raw":
            return 15 + bottom_margin
        base = self._content_lines + 2
        if self._edit_mode in {"edit", "picker", "cell"}:
            return base + 3 + bottom_margin  # inline input plus its top margin
        if self._edit_mode == "content":
            return base + 7 + bottom_margin
        return base + bottom_margin

    @property
    def model(self) -> PromptFrontmatter:
        """The panel's current working model (the bar reads this to persist)."""
        return self._model

    # -- key handling ---------------------------------------------------------

    def deactivate(self) -> None:
        """Toggle the panel off (the in-panel ``g=`` sequence from inside it).

        Mirrors the per-mode ``esc`` semantics before leaving, so ``g=`` and
        ``esc`` agree on how an in-progress edit is resolved:

        - **rows**: post :class:`Closed` straight away;
        - **inline edit**: cancel the in-progress edit, then post :class:`Closed`;
        - **raw**: try to apply the YAML first and only post :class:`Closed` if it
          parsed (a parse failure keeps focus in raw mode rather than silently
          discarding the invalid edit).
        """
        if self._edit_mode in {"edit", "picker", "cell", "content"}:
            self._pending_ctrl_g = False
            self._cancel_active_edit()
            self._close()
            return
        if self._edit_mode == "raw":
            self._pending_ctrl_g = False
            self._commit_raw()
            if self._edit_mode == "rows":
                self._close()
            return
        self._pending_ctrl_g = False
        self._close()

    def on_key(self, event: events.Key) -> None:
        """Dispatch panel keys, deferring to child editors while editing."""
        if self._handle_ctrl_g_prefix(event):
            return
        if self._edit_mode in {"edit", "picker", "cell"}:
            # Inline editing: literal text entry is preserved (``g`` / ``=`` type
            # into the child editor); only NORMAL-mode ``esc`` is intercepted here.
            self._pending_g = False
            if self._edit_mode == "picker" and event.character:
                editor = self.query_one("#frontmatter-inline", SingleLineVimTextArea)
                field = self._picker_accelerators.get(event.character.casefold())
                if field is not None and not editor.text:
                    event.stop()
                    event.prevent_default()
                    self._picker_matches = [field]
                    self._picker_selected = 0
                    self._commit_picker()
                    return
            if self._edit_mode == "cell" and event.key in ("tab", "shift+tab"):
                event.stop()
                event.prevent_default()
                self._move_cell(-1 if event.key == "shift+tab" else 1)
                return
            if self._edit_mode == "cell" and event.key in ("space", "h", "l"):
                inline_editor = self.query_one(
                    "#frontmatter-inline", SingleLineVimTextArea
                )
                if inline_editor._vim_mode == "normal" and self._cycle_active_cell(
                    -1 if event.key == "h" else 1
                ):
                    event.stop()
                    event.prevent_default()
                    return
            if event.key == "escape":
                inline_editor = self.query_one(
                    "#frontmatter-inline", SingleLineVimTextArea
                )
                if (
                    inline_editor._vim_mode != "normal"
                    or inline_editor._has_pending_normal_state()
                ):
                    return
                event.stop()
                self._cancel_active_edit()
            return
        if self._edit_mode == "content":
            self._pending_g = False
            if event.key == "ctrl+s":
                event.stop()
                event.prevent_default()
                self._commit_cell_edit()
                return
            if event.key == "shift+tab":
                event.stop()
                event.prevent_default()
                self._move_cell(-1)
                return
            if event.key == "escape":
                content_editor = self.query_one("#frontmatter-content", VimTextArea)
                if (
                    content_editor._vim_mode != "normal"
                    or content_editor._has_pending_normal_state()
                ):
                    return
                event.stop()
                self._cancel_active_edit()
            return
        if self._edit_mode == "raw":
            # Raw YAML editing: likewise literal; only NORMAL-mode ``esc`` commits.
            self._pending_g = False
            if event.key == "ctrl+c":
                event.stop()
                event.prevent_default()
                self._discard_raw()
                return
            if event.key == "escape":
                raw_editor = self.query_one("#frontmatter-raw", VimTextArea)
                if (
                    raw_editor._vim_mode != "normal"
                    or raw_editor._has_pending_normal_state()
                ):
                    return
                event.stop()
                self._commit_raw()
            return
        # Rows (navigate) mode owns a panel-local ``g`` prefix so the same ``g=``
        # sequence that opened the panel from the body also closes it from
        # inside.  ``g`` alone is a pending prefix; ``g=`` deactivates with the
        # per-mode ``esc`` semantics, while any other continuation is dispatched
        # as its own rows command so navigation keys are never swallowed.
        if self._pending_g:
            self._pending_g = False
            if (event.character or event.key) == "=":
                event.stop()
                event.prevent_default()
                self.deactivate()
                return
            # Fall through: handle the continuation as an ordinary rows key.
        elif event.character == "g":
            event.stop()
            self._pending_g = True
            return
        handled = True
        key = event.key
        if key in ("j", "down"):
            self._move(1)
        elif key in ("k", "up"):
            self._move(-1)
        elif key in ("l", "right"):
            self._set_fold(False)
        elif key in ("h", "left"):
            self._set_fold(True)
        elif key in ("enter", "e"):
            self._edit_selected()
        elif key == "a":
            self._request_add_property()
        elif key in ("A", "o"):
            self._add_item_at_selection()
        elif key == "d":
            self._delete_selected()
        elif key == "u":
            self._undo()
        elif key == "J":
            self._move_selected_item(1)
        elif key == "K":
            self._move_selected_item(-1)
        elif key == "R":
            self._begin_raw()
        elif key in ("escape", "q"):
            self._close()
        else:
            handled = False
        if handled:
            event.stop()

    def _handle_ctrl_g_prefix(self, event: events.Key) -> bool:
        """Forward the explicit ``Ctrl+G Ctrl+C`` chord to the host prompt bar."""
        if self._pending_ctrl_g:
            self._pending_ctrl_g = False
            if event.key == "escape":
                event.stop()
                event.prevent_default()
                return True
            if event.key == "ctrl+c":
                event.stop()
                event.prevent_default()
                bar = self._host_prompt_bar()
                action = getattr(bar, "action_cancel_all", None)
                if callable(action):
                    action()
                return True
            return False

        if event.key != "ctrl+g":
            return False
        event.stop()
        event.prevent_default()
        self._pending_ctrl_g = True
        return True

    def _host_prompt_bar(self) -> object | None:
        """Return the containing prompt bar without importing it at module load."""
        node = self.parent
        while node is not None:
            if callable(getattr(node, "action_cancel_all", None)):
                return node
            node = node.parent
        return None

    def _schedule_layout_update(self) -> None:
        """Ask the host bar to remeasure after a panel mode-height change."""
        node = self.parent
        while node is not None:
            schedule = getattr(node, "_schedule_height_update", None)
            if callable(schedule):
                schedule()
                return
            node = node.parent

    def _move(self, delta: int) -> None:
        """Move the row selection by *delta* (clamped over nav rows)."""
        rows = self._nav_rows()
        if not rows:
            return
        self._selected = max(0, min(self._selected + delta, len(rows) - 1))
        self._refresh()

    def _selected_nav(self) -> tuple[str, str] | None:
        """The selected nav row (``(kind, key)``), or ``None`` when empty."""
        rows = self._nav_rows()
        if not rows:
            return None
        self._selected = max(0, min(self._selected, len(rows) - 1))
        return rows[self._selected]

    def _clamp_selection(self) -> None:
        """Clamp :attr:`_selected` into the current nav-row range."""
        self._selected = max(0, min(self._selected, max(0, len(self._nav_rows()) - 1)))

    def _select_nav(self, target: tuple[str, str]) -> None:
        """Move the selection onto *target* if it is currently navigable."""
        for index, row in enumerate(self._nav_rows()):
            if row == target:
                self._selected = index
                return

    def _set_fold(self, folded: bool) -> None:
        """Fold / unfold the structured sub-tree the selection belongs to."""
        nav = self._selected_nav()
        if nav is None:
            return
        kind, key = nav
        field = key if kind == "field" else ("input" if kind == "input" else "xprompts")
        if field not in ("input", "xprompts"):
            return
        if folded:
            self._folded.add(field)
            self._select_nav(("field", field))  # keep selection on the header
        else:
            self._folded.discard(field)
        self._refresh()
