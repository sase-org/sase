"""Add, edit, delete, and inline value helpers for ``FrontmatterPanel``."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from textual.widgets import Input

from sase.xprompt.frontmatter_schema import FrontmatterFieldKind
from sase.xprompt.models import InputArg, XPrompt

if TYPE_CHECKING:
    from textual.containers import Vertical as _MixinBase

    from sase.xprompt.prompt_frontmatter import PromptFrontmatter

else:
    _MixinBase = object

# Words accepted as booleans when editing ``skill`` / ``snippet`` inline,
# mirroring the bool input-type rule text from core
# ("true/false, yes/no, on/off, 1/0").
_TRUE_WORDS = frozenset({"true", "yes", "on", "1"})
_FALSE_WORDS = frozenset({"false", "no", "off", "0"})


class _FrontmatterFieldDescriptor(Protocol):
    """Schema descriptor shape consumed by the add-property picker."""

    name: str
    kind: FrontmatterFieldKind
    required: bool
    description: str
    allowed_values: str | None
    example: str


class FrontmatterPanelEditingMixin(_MixinBase):
    """Model mutation, inline editing, and structured sub-form behavior."""

    if TYPE_CHECKING:
        AddRequested: type[Any]
        Changed: type[Any]
        Closed: type[Any]
        _adding_field: str | None
        _edit_mode: str
        _editing_field: str | None
        _fields: list[str]
        _folded: set[str]
        _model: PromptFrontmatter
        _schema: dict[str, Any]
        _schema_order: list[str]
        _selected: int

        def _clamp_selection(self) -> None: ...
        def _nav_rows(self) -> list[tuple[str, str]]: ...
        def _refresh(self) -> None: ...
        def _row_fields(self) -> list[str]: ...
        def _select_nav(self, target: tuple[str, str]) -> None: ...
        def _selected_nav(self) -> tuple[str, str] | None: ...

    def addable_properties(self) -> list[_FrontmatterFieldDescriptor]:
        """Core schema descriptors for every unset field, in canonical order.

        The host bar uses this to populate the add-property picker so the panel
        keeps the core schema (and its guidance text) as the single source.
        Structured fields (``input`` / ``xprompts``) are offered too; picking one
        opens its sub-form modal to author the first item.
        """
        return [
            self._schema[name]
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
                self._emit_changed()
                self._commit_to_body()
                return
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
                self._emit_changed()
                self._commit_to_body()
                return
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

    def _commit_to_body(self) -> None:
        """Restore rows view after a sub-form save and focus the prompt body."""
        self._edit_mode = "rows"
        self._show_rows_only()
        self._clamp_selection()
        self._refresh()
        self._close()

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

    def _show_rows_only(self) -> None:
        """Show the rows view; hide the inline and raw editors."""
        from textual.widgets import Static, TextArea

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
