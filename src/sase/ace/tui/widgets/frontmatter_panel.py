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
- **Done** with ``esc`` / ``q`` (or the ``Ctrl+Shift+-`` toggle that opened it):
  hands focus back to the prompt body (the host bar removes the frontmatter
  entirely when the panel is left empty).

Phase 4 adds structured editing of individual ``input`` / ``xprompts`` items:
``j``/``k`` navigate into the unfolded sub-trees, and ``a``/``e``/``d`` (or
``enter``) add, edit, and delete items through small typed sub-form modals
(:class:`~sase.ace.tui.modals.input_item_modal.InputItemModal` and
:class:`~sase.ace.tui.modals.xprompt_item_modal.XPromptItemModal`).  Raw mode
remains the escape hatch for the long tail.

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
from textual.widgets import Input, Static, TextArea

from sase.ace.tui.widgets._frontmatter_panel_editing import (
    FrontmatterPanelEditingMixin,
)
from sase.ace.tui.widgets._frontmatter_panel_raw import FrontmatterPanelRawMixin
from sase.ace.tui.widgets._frontmatter_panel_rendering import (
    FrontmatterPanelRenderingMixin,
)
from sase.xprompt.frontmatter_schema import frontmatter_field_schema
from sase.xprompt.prompt_frontmatter import PromptFrontmatter

# Textual key spellings for the physical ``Ctrl+Shift+-`` chord that toggles the
# xprompt properties panel.  ``ctrl+underscore`` also names legacy ``Ctrl+-`` /
# ``Ctrl+_`` / ``Ctrl+/`` (the ``0x1f`` control byte), so the prompt body keeps
# only the disambiguated spelling; when the panel itself owns focus, either
# spelling may deactivate it.
FRONTMATTER_PANEL_BODY_TOGGLE_KEYS: frozenset[str] = frozenset({"ctrl+shift+minus"})
FRONTMATTER_PANEL_TOGGLE_KEYS: frozenset[str] = FRONTMATTER_PANEL_BODY_TOGGLE_KEYS | {
    "ctrl+underscore"
}


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
        self._editing_field: str | None = None
        self._adding_field: str | None = None
        self._content_lines = 1
        self._schema = {f.name: f for f in frontmatter_field_schema()}
        self._schema_order = [f.name for f in frontmatter_field_schema()]

    # -- composition ----------------------------------------------------------

    def compose(self) -> ComposeResult:
        """A rows view plus the (hidden) inline and raw editors."""
        yield Static("", id="frontmatter-rows")
        yield Input(id="frontmatter-inline", classes="hidden")
        yield TextArea(
            "",
            id="frontmatter-raw",
            classes="hidden",
            show_line_numbers=False,
            soft_wrap=True,
        )

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
        self._editing_field = None
        self._adding_field = None
        self._show_rows_only()
        self._refresh()

    def focus_panel(self) -> None:
        """Focus the panel for row navigation (the ``,f`` keymap target)."""
        self._edit_mode = "rows"
        self._show_rows_only()
        self.focus()
        self._refresh()

    @property
    def reserved_height(self) -> int:
        """Rows the panel needs (content + border) so the bar can size itself."""
        if self._edit_mode == "raw":
            return 12
        base = self._content_lines + 2
        if self._edit_mode == "edit":
            return base + 3  # the inline input plus its top margin
        return base

    @property
    def model(self) -> PromptFrontmatter:
        """The panel's current working model (the bar reads this to persist)."""
        return self._model

    # -- key handling ---------------------------------------------------------

    def deactivate(self) -> None:
        """Toggle the panel off (the ``Ctrl+Shift+-`` chord from inside it).

        Mirrors the per-mode ``esc`` semantics before leaving, so the chord and
        ``esc`` agree on how an in-progress edit is resolved:

        - **rows**: post :class:`Closed` straight away;
        - **inline edit**: cancel the in-progress edit, then post :class:`Closed`;
        - **raw**: try to apply the YAML first and only post :class:`Closed` if it
          parsed (a parse failure keeps focus in raw mode rather than silently
          discarding the invalid edit).
        """
        if self._edit_mode == "edit":
            self._cancel_inline_edit()
            self._close()
            return
        if self._edit_mode == "raw":
            self._commit_raw()
            if self._edit_mode == "rows":
                self._close()
            return
        self._close()

    def on_key(self, event: events.Key) -> None:
        """Dispatch panel keys, deferring to child editors while editing."""
        if event.key in FRONTMATTER_PANEL_TOGGLE_KEYS:
            # The ``Ctrl+Shift+-`` toggle deactivates the panel from any mode,
            # ahead of the per-mode dispatch below (and the child editors).
            event.stop()
            event.prevent_default()
            self.deactivate()
            return
        if self._edit_mode == "edit":
            if event.key == "escape":
                event.stop()
                self._cancel_inline_edit()
            return
        if self._edit_mode == "raw":
            if event.key == "escape":
                event.stop()
                self._commit_raw()
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
            self._add_at_selection()
        elif key == "d":
            self._delete_selected()
        elif key == "R":
            self._begin_raw()
        elif key in ("escape", "q"):
            self._close()
        else:
            handled = False
        if handled:
            event.stop()

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
