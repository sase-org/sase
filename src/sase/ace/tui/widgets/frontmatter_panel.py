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
- **Done** with ``esc`` / ``q``: hands focus back to the prompt body (the host
  bar removes the frontmatter entirely when the panel is left empty).

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

import re
from typing import Any

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Input, Static, TextArea

from sase.xprompt.frontmatter_schema import (
    FrontmatterDiagnostic,
    FrontmatterFieldKind,
    frontmatter_field_schema,
    validate_frontmatter,
)
from sase.xprompt.models import UNSET, InputArg, XPrompt
from sase.xprompt.prompt_frontmatter import PromptFrontmatter

# Words accepted as booleans when editing ``skill`` / ``snippet`` inline, mirroring
# the bool input-type rule text from core ("true/false, yes/no, on/off, 1/0").
_TRUE_WORDS = frozenset({"true", "yes", "on", "1"})
_FALSE_WORDS = frozenset({"false", "no", "off", "0"})

# A top-level YAML key line in the serialized block (column-0 ``key:``), used to
# attribute a core diagnostic's line back to the field row it belongs under.
_TOP_LEVEL_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):")

# Width of the key column so value summaries align, matching the design mockups.
_KEY_COLUMN = 13

_SUBTITLE_POPULATED = "a add · e edit · d delete · R raw · h/l fold · esc done"
_SUBTITLE_EMPTY = "a add · R raw · esc done"
_SUBTITLE_EDIT = "enter save · esc cancel"
_SUBTITLE_RAW = "esc apply · live-validated"


class FrontmatterPanel(Vertical):
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

    # -- rendering ------------------------------------------------------------

    def _refresh(self) -> None:
        """Rebuild the rows renderable, status chip, and subtitle."""
        rows = self.query_one("#frontmatter-rows", Static)
        renderable, line_count = self._build_rows()
        rows.update(renderable)
        self._content_lines = line_count
        self._refresh_chrome()

    def _refresh_chrome(self) -> None:
        """Update the border title chip and the keymap subtitle for the mode."""
        diagnostics = self._diagnostics()
        errors = sum(1 for d in diagnostics if d.is_error)
        if self._model.is_empty:
            chip = "[dim]⟨ ⟩[/]"
        elif errors:
            chip = f"[bold red]⟨! {errors}⟩[/]"
        else:
            chip = "[bold green]⟨✓⟩[/]"
        self.border_title = f"frontmatter  {chip}"
        if self._edit_mode == "edit":
            self.border_subtitle = _SUBTITLE_EDIT
        elif self._edit_mode == "raw":
            self.border_subtitle = _SUBTITLE_RAW
        elif self._model.is_empty:
            self.border_subtitle = _SUBTITLE_EMPTY
        else:
            self.border_subtitle = _SUBTITLE_POPULATED

    def _build_rows(self) -> tuple[Text, int]:
        """Return the rows renderable and its rendered line count."""
        if self._model.is_empty and self._adding_field is None:
            text = self._empty_state()
            return text, len(text.plain.splitlines()) or 1

        field_errors = self._diagnostics_by_field()
        selected = None if self._edit_mode == "raw" else self._selected_nav()
        lines: list[Text] = []
        for field in self._row_fields():
            lines.extend(self._render_field(field, selected=selected))
            for message in field_errors.get(field, ()):  # inline core guidance
                error = Text("      ")
                error.append(message, style="red")
                lines.append(error)
        group = Text("\n").join(lines)
        return group, len(lines) or 1

    def _row_fields(self) -> list[str]:
        """Present fields plus the in-progress add row (canonical order)."""
        fields = list(self._fields)
        if self._adding_field is not None and self._adding_field not in fields:
            fields.append(self._adding_field)
        return fields

    def _nav_rows(self) -> list[tuple[str, str]]:
        """Flat list of navigable rows: field headers and unfolded sub-items.

        Each entry is ``("field", name)`` for a property row, or
        ``("input", arg_name)`` / ``("xprompt", name)`` for a sub-item of an
        unfolded structured field.  Selection (:attr:`_selected`) indexes into
        this list so ``j``/``k`` step through items as well as fields.
        """
        rows: list[tuple[str, str]] = []
        for field in self._row_fields():
            rows.append(("field", field))
            schema = self._schema.get(field)
            if schema is None or schema.kind is not FrontmatterFieldKind.STRUCTURED:
                continue
            if field in self._folded:
                continue
            if field == "input":
                rows.extend(("input", arg.name) for arg in self._model.inputs)
            elif field == "xprompts":
                rows.extend(("xprompt", name) for name in self._model.xprompts)
        return rows

    @staticmethod
    def _empty_state() -> Text:
        """The just-triggered empty panel guidance."""
        text = Text()
        text.append("No properties yet.\n", style="dim")
        text.append("Press ", style="dim")
        text.append("a", style="bold #87D7FF")
        text.append(" to add:  ", style="dim")
        text.append(
            "name · description · tags · input · xprompts · skill · snippet",
            style="dim",
        )
        return text

    def _render_field(
        self, field: str, *, selected: tuple[str, str] | None
    ) -> list[Text]:
        """Render one field row (plus its sub-items when unfolded)."""
        schema = self._schema.get(field)
        structured = (
            schema is not None and schema.kind is FrontmatterFieldKind.STRUCTURED
        )
        header_selected = selected == ("field", field)
        marker = "▸ " if header_selected else "  "
        key_style = "bold reverse #87D7FF" if header_selected else "bold #87D7FF"
        row = Text(marker)
        row.append(field.ljust(_KEY_COLUMN), style=key_style)
        if structured:
            folded = field in self._folded
            row.append("▸ " if folded else "▾ ", style="cyan")
            count = (
                len(self._model.inputs)
                if field == "input"
                else len(self._model.xprompts)
            )
            label = "item" if count == 1 else "items"
            row.append(f"{count} {label}", style="dim")
            rows = [row]
            if not folded:
                rows.extend(self._render_sub_items(field, selected=selected))
            return rows
        row.append(self._value_summary(field))
        return [row]

    def _render_sub_items(
        self, field: str, *, selected: tuple[str, str] | None
    ) -> list[Text]:
        """Render the sub-item lines for ``input`` / ``xprompts``."""
        lines: list[Text] = []
        if field == "input":
            for arg in self._model.inputs:
                lines.append(
                    self._input_item_line(arg, selected=selected == ("input", arg.name))
                )
        else:
            for name, xprompt in self._model.xprompts.items():
                lines.append(
                    self._xprompt_item_line(
                        name, xprompt, selected=selected == ("xprompt", name)
                    )
                )
        if not lines:
            empty = Text("    • ")
            empty.append("(none)", style="dim italic")
            lines.append(empty)
        return lines

    @staticmethod
    def _input_item_line(arg: InputArg, *, selected: bool = False) -> Text:
        """One ``input`` sub-item: name, type, required/default, description."""
        line = Text("    • ")
        line.append(arg.name, style="reverse #87D7FF" if selected else "#87D7FF")
        line.append(f"  {arg.type.value}", style="green")
        if arg.default is UNSET:
            line.append("  (required)", style="yellow")
        else:
            line.append(f"  = {arg.default!r}", style="dim")
        if arg.description:
            line.append(f"  {arg.description}", style="dim")
        return line

    @staticmethod
    def _xprompt_item_line(
        name: str, xprompt: XPrompt, *, selected: bool = False
    ) -> Text:
        """One ``xprompts`` sub-item: name and a content/description preview."""
        line = Text("    • ")
        line.append(name, style="reverse #87D7FF" if selected else "#87D7FF")
        preview = xprompt.description or xprompt.content
        preview = " ".join(preview.split())
        if len(preview) > 48:
            preview = f"{preview[:45]}…"
        if preview:
            line.append(f'  "{preview}"', style="dim")
        return line

    def _value_summary(self, field: str) -> Text:
        """Type-styled summary of a scalar / list / bool field's value."""
        value = self._editable_text(field)
        if not value:
            return Text("(empty)", style="dim italic")
        return Text(value, style="white")

    # -- diagnostics ----------------------------------------------------------

    def _diagnostics(self) -> list[FrontmatterDiagnostic]:
        """Core validation diagnostics for the current model (may be empty)."""
        try:
            return self._model.diagnostics()
        except Exception:
            return []

    def _diagnostics_by_field(self) -> dict[str, list[str]]:
        """Map each error diagnostic to the top-level field row it falls under."""
        diagnostics = [d for d in self._diagnostics() if d.is_error]
        if not diagnostics:
            return {}
        serialized = self._model.serialize()
        line_field: dict[int, str] = {}
        current = ""
        for index, line in enumerate(serialized.splitlines()):
            match = _TOP_LEVEL_KEY_RE.match(line)
            if match and match.group(1) in self._schema:
                current = match.group(1)
            line_field[index] = current
        by_field: dict[str, list[str]] = {}
        for diagnostic in diagnostics:
            field = line_field.get(diagnostic.range.start.line, "")
            if field:
                by_field.setdefault(field, []).append(diagnostic.message)
        return by_field

    # -- key handling ---------------------------------------------------------

    def on_key(self, event: events.Key) -> None:
        """Dispatch panel keys, deferring to child editors while editing."""
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

    # -- add / edit / delete --------------------------------------------------

    def addable_properties(self) -> list[tuple[str, str]]:
        """``(name, description)`` of every unset field, in canonical order.

        The host bar uses this to populate the add-property picker so the panel
        keeps the core schema (and its descriptions) as the single source.
        Structured fields (``input`` / ``xprompts``) are offered too; picking one
        opens its sub-form modal to author the first item.
        """
        return [
            (name, self._schema[name].description)
            for name in self._schema_order
            if name not in self._fields
        ]

    def begin_add(self, field: str) -> None:
        """Start adding *field*: a sub-form modal for structured, else inline."""
        if field not in self._schema or field in self._fields:
            return
        if self._schema[field].kind is FrontmatterFieldKind.STRUCTURED:
            self._add_structured_item(field)
            return
        self._adding_field = field
        self._selected = len(self._nav_rows()) - 1
        self._begin_inline_edit(field, initial="", adding=True)

    def _request_add_property(self) -> None:
        """Ask the host bar to open the add-property picker."""
        self.post_message(self.AddRequested())

    def _add_at_selection(self) -> None:
        """Handle ``a``: add an item inside a sub-tree, else add a property."""
        nav = self._selected_nav()
        if nav is not None:
            kind, key = nav
            if kind == "input" or (kind == "field" and key == "input"):
                self._add_structured_item("input")
                return
            if kind == "xprompt" or (kind == "field" and key == "xprompts"):
                self._add_structured_item("xprompts")
                return
        self._request_add_property()

    def _edit_selected(self) -> None:
        """Edit the selection: inline scalar, structured item, or add-on-header."""
        nav = self._selected_nav()
        if nav is None:
            return
        kind, key = nav
        if kind == "input":
            self._edit_input_item(key)
            return
        if kind == "xprompt":
            self._edit_xprompt_item(key)
            return
        schema = self._schema.get(key)
        if schema is None:
            return
        if schema.kind is FrontmatterFieldKind.STRUCTURED:
            # ``enter``/``e`` on a structured header adds a new item to it.
            self._add_structured_item(key)
            return
        self._begin_inline_edit(key, initial=self._editable_text(key))

    def _delete_selected(self) -> None:
        """Delete the selection: a whole field, or one structured sub-item."""
        nav = self._selected_nav()
        if nav is None:
            return
        kind, key = nav
        if kind == "input":
            self._model.remove_input(key)
        elif kind == "xprompt":
            self._model.remove_xprompt(key)
        else:
            self._clear_field(key)
        self._fields = self._model.present_fields()
        self._clamp_selection()
        self._refresh()
        self._emit_changed()

    # -- structured sub-item editors ------------------------------------------

    def _add_structured_item(self, field: str) -> None:
        """Open the sub-form modal to add a new ``input`` / ``xprompts`` item."""
        if field == "input":
            self._open_input_modal(existing=None)
        else:
            self._open_xprompt_modal(existing=None)

    def _edit_input_item(self, name: str) -> None:
        """Open the input sub-form modal prefilled with the named input."""
        arg = self._model.get_input(name)
        if arg is not None:
            self._open_input_modal(existing=arg)

    def _edit_xprompt_item(self, name: str) -> None:
        """Open the xprompt sub-form modal prefilled with the named helper."""
        xprompt = self._model.get_xprompt(name)
        if xprompt is not None:
            self._open_xprompt_modal(existing=(name, xprompt))

    def _open_input_modal(self, *, existing: InputArg | None) -> None:
        """Push the input sub-form and apply its result back onto the model."""
        from sase.ace.tui.modals import InputItemModal

        used = [
            arg.name
            for arg in self._model.inputs
            if existing is None or arg.name != existing.name
        ]

        def _done(result: InputArg | None) -> None:
            if result is not None:
                if existing is not None and existing.name != result.name:
                    self._model.remove_input(existing.name)
                self._model.set_input(result)
                self._fields = self._model.present_fields()
                self._folded.discard("input")
                self._select_nav(("input", result.name))
                self._refresh()
                self._emit_changed()
            self._return_focus()

        self.app.push_screen(InputItemModal(existing=existing, used_names=used), _done)

    def _open_xprompt_modal(self, *, existing: tuple[str, XPrompt] | None) -> None:
        """Push the xprompt sub-form and apply its result back onto the model."""
        from sase.ace.tui.modals import XPromptItemModal

        used = [
            name
            for name in self._model.xprompts
            if existing is None or name != existing[0]
        ]

        def _done(result: tuple[str, XPrompt] | None) -> None:
            if result is not None:
                name, xprompt = result
                if existing is not None and existing[0] != name:
                    self._model.remove_xprompt(existing[0])
                self._model.set_xprompt(xprompt)
                self._fields = self._model.present_fields()
                self._folded.discard("xprompts")
                self._select_nav(("xprompt", name))
                self._refresh()
                self._emit_changed()
            self._return_focus()

        self.app.push_screen(
            XPromptItemModal(existing=existing, used_names=used), _done
        )

    def _return_focus(self) -> None:
        """Re-focus the panel for row navigation after a sub-form closes."""
        self._edit_mode = "rows"
        self._show_rows_only()
        self._clamp_selection()
        self._refresh()
        self.focus()

    def _begin_inline_edit(
        self, field: str, *, initial: str, adding: bool = False
    ) -> None:
        """Reveal the inline ``Input`` prefilled with *initial* and focus it."""
        self._edit_mode = "edit"
        self._editing_field = field
        if not adding:
            self._adding_field = None
        editor = self.query_one("#frontmatter-inline", Input)
        editor.value = initial
        editor.border_title = field
        editor.remove_class("hidden")
        self._refresh()
        editor.focus()
        editor.cursor_position = len(editor.value)

    def _cancel_inline_edit(self) -> None:
        """Abort the inline edit; discard a freshly added (unsaved) field."""
        self._adding_field = None
        self._finish_inline_edit()

    def _finish_inline_edit(self) -> None:
        """Hide the inline editor and return to row navigation."""
        self._edit_mode = "rows"
        self._editing_field = None
        editor = self.query_one("#frontmatter-inline", Input)
        editor.add_class("hidden")
        self._fields = self._model.present_fields()
        self._selected = min(self._selected, max(0, len(self._row_fields()) - 1))
        self._refresh()
        self.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Apply the inline edit on ``enter`` and persist the change."""
        if event.input.id != "frontmatter-inline":
            return
        event.stop()
        field = self._editing_field
        if field is not None:
            self._apply_inline_value(field, event.value)
        self._adding_field = None
        self._finish_inline_edit()
        self._emit_changed()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Swallow inline-editor change events so they never reach the bar."""
        if event.input.id == "frontmatter-inline":
            event.stop()

    # -- raw YAML mode --------------------------------------------------------

    def _begin_raw(self) -> None:
        """Enter raw-YAML mode: edit the canonical serialized frontmatter."""
        self._edit_mode = "raw"
        self._adding_field = None
        editor = self.query_one("#frontmatter-raw", TextArea)
        editor.text = self._model.serialize()
        rows = self.query_one("#frontmatter-rows", Static)
        rows.add_class("hidden")
        self.query_one("#frontmatter-inline", Input).add_class("hidden")
        editor.remove_class("hidden")
        self._refresh_chrome()
        editor.focus()
        self._update_raw_chip(editor.text)

    def _commit_raw(self) -> None:
        """Re-parse the raw YAML into the model and return to the rows view.

        Unparseable structure (e.g. a non-underscore local xprompt name) keeps
        the user in raw mode with the core message rather than dropping data.
        """
        editor = self.query_one("#frontmatter-raw", TextArea)
        text = editor.text
        try:
            model = PromptFrontmatter.parse(text)
        except Exception as exc:  # surface, do not silently discard
            self.border_subtitle = f"⚠ {exc}"
            return
        self._model = model
        self._fields = self._model.present_fields()
        self._selected = min(self._selected, max(0, len(self._fields) - 1))
        self._show_rows_only()
        self._edit_mode = "rows"
        self._refresh()
        self.focus()
        self._emit_changed()

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """Live-validate the raw editor and keep its change off the bar."""
        if event.text_area.id != "frontmatter-raw":
            return
        event.stop()
        if self._edit_mode == "raw":
            self._update_raw_chip(event.text_area.text)

    def _update_raw_chip(self, text: str) -> None:
        """Refresh the status chip from a live ``validate_frontmatter`` pass."""
        try:
            diagnostics = validate_frontmatter(text) if text.strip() else []
        except Exception:
            diagnostics = []
        errors = sum(1 for d in diagnostics if d.is_error)
        if not text.strip():
            chip = "[dim]⟨ ⟩[/]"
        elif errors:
            chip = f"[bold red]⟨! {errors}⟩[/]"
        else:
            chip = "[bold green]⟨✓⟩[/]"
        self.border_title = f"frontmatter (raw)  {chip}"

    # -- helpers --------------------------------------------------------------

    def _show_rows_only(self) -> None:
        """Show the rows view; hide the inline and raw editors."""
        self.query_one("#frontmatter-rows", Static).remove_class("hidden")
        self.query_one("#frontmatter-inline", Input).add_class("hidden")
        self.query_one("#frontmatter-raw", TextArea).add_class("hidden")

    def _close(self) -> None:
        """Leave the panel, handing focus back to the host (the prompt body)."""
        self.post_message(self.Closed(is_empty=self._model.is_empty))

    def _emit_changed(self) -> None:
        """Tell the host bar to persist the working model onto the stack."""
        self.post_message(self.Changed(self._model))

    def _editable_text(self, field: str) -> str:
        """Render a scalar / list / bool field's value as inline-editable text."""
        if field == "name":
            return self._model.name or ""
        if field == "description":
            return self._model.description or ""
        if field == "tags":
            return ", ".join(self._model.tags)
        if field == "skill":
            return self._bool_or_seq_text(self._model.skill)
        if field == "snippet":
            return self._bool_or_seq_text(self._model.snippet)
        return ""

    @staticmethod
    def _bool_or_seq_text(value: object) -> str:
        """Render a ``bool`` / list / string field value for inline editing."""
        if value is None:
            return ""
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (list, tuple)):
            return ", ".join(str(item) for item in value)
        return str(value)

    def _apply_inline_value(self, field: str, raw_text: str) -> None:
        """Write the inline-edited *raw_text* back onto the model field."""
        text = raw_text.strip()
        if not text:
            self._clear_field(field)
            return
        if field == "name":
            self._model.name = text
        elif field == "description":
            self._model.description = text
        elif field == "tags":
            self._model.tags = [t.strip() for t in text.split(",") if t.strip()]
        elif field == "skill":
            self._model.skill = self._parse_bool_or_list(text)
        elif field == "snippet":
            self._model.snippet = self._parse_bool_or_scalar(text)

    def _clear_field(self, field: str) -> None:
        """Unset *field* on the model (removes it from the serialized output)."""
        if field == "name":
            self._model.name = None
        elif field == "description":
            self._model.description = None
        elif field == "tags":
            self._model.tags = []
        elif field == "input":
            self._model.inputs = []
        elif field == "xprompts":
            self._model.xprompts = {}
        elif field == "skill":
            self._model.skill = None
        elif field == "snippet":
            self._model.snippet = None

    @staticmethod
    def _parse_bool_word(text: str) -> bool | None:
        """Return ``True``/``False`` for a boolean word, else ``None``."""
        lowered = text.strip().lower()
        if lowered in _TRUE_WORDS:
            return True
        if lowered in _FALSE_WORDS:
            return False
        return None

    def _parse_bool_or_list(self, text: str) -> bool | list[str]:
        """Parse ``skill``: a boolean word, else a comma-separated provider list."""
        boolean = self._parse_bool_word(text)
        if boolean is not None:
            return boolean
        return [part.strip() for part in text.split(",") if part.strip()]

    def _parse_bool_or_scalar(self, text: str) -> bool | str:
        """Parse ``snippet``: a boolean word, else a literal trigger string."""
        boolean = self._parse_bool_word(text)
        if boolean is not None:
            return boolean
        return text.strip()
